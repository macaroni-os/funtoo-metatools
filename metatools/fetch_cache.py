#!/usr/bin/env python3

from datetime import datetime
import pymongo

from metatools.config.mongodb import get_collection


class FetchCache:

	async def write(self, method_name, fetchable, body=None, metadata_only=False):
		pass

	async def read(self, method_name, fetchable, max_age=None, refresh_interval=None):
		pass

	async def record_fetch_failure(self, method_name, fetchable, failure_reason):
		pass


class MongoDBFetchCache(FetchCache):

	fc = None

	def __init__(self):
		self.fc = get_collection('fetch_cache')
		self.fc.create_index([("method_name", pymongo.ASCENDING), ("url", pymongo.ASCENDING)])
		self.fc.create_index("last_failure_on", partialFilterExpression={"last_failure_on": {"$exists": True}})

	async def write(self, method_name, fetchable, body=None, metadata_only=False):
		"""
		This method is called when we have successfully fetched something. In the case of a network resource such as
		a Web page, we will record the result of our fetching in the 'result' field so it is cached for later. In the
		case that we're recording that we successfully downloaded an Artifact (tarball), we don't store the tarball
		in MongoDB but we do store its metadata (hashes and filesize.)
	
		If metadata_only is True, we are simply updating metadata rather than the content in the fetch cache.
	
		"""
		url = fetchable
		metadata = None
		now = datetime.utcnow()
		selector = {"method_name": method_name, "url": url}
		if not metadata_only:
			self.fc.update_one(
				selector,
				{"$set": {"last_attempt": now, "fetched_on": now, "metadata": metadata, "body": body}},
				upsert=True,
			)
		else:
			self.fc.update_one(
				selector,
				{
					"$set": {
						"last_attempt": now,
						"fetched_on": now,
						"metadata": metadata,
					}
				},
				upsert=True,
			)

	async def read(self, method_name, fetchable, max_age=None, refresh_interval=None):
		"""
		Attempt to see if the network resource or Artifact is in our fetch cache. We will return the entire MongoDB
		document. In the case of a network resource, this includes the cached value in the 'result' field. In the
		case of an Artifact, the 'metadata' field will include its hashes and filesize.
	
		``max_age`` and ``refresh_interval`` parameters are used to set criteria for what is acceptable for the
		caller. If criteria don't match, None is returned instead of the MongoDB document.
	
		In the case the document is not found or does not meet criteria, we will raise a CacheMiss exception.
		"""
		# Fetchable can be a simple string (URL) or an Artifact. They are a bit different:
		if type(fetchable) == str:
			url = fetchable
		else:
			url = fetchable.url

		# content_kwargs is stored at None if there are none, not an empty dict:
		looking_for = {"method_name": method_name, "url": url}

		result = self.fc.find_one(looking_for)
		if result is None or "fetched_on" not in result:
			raise CacheMiss()
		elif refresh_interval is not None:
			if datetime.utcnow() - result["fetched_on"] <= refresh_interval:
				return result
			else:
				raise CacheMiss()
		elif max_age is not None and datetime.utcnow() - result["fetched_on"] > max_age:
			raise CacheMiss()
		else:
			return result

	async def record_fetch_failure(self, method_name, fetchable, failure_reason):
		"""
		It is important to document when fetches fail, and that is what this method is for.
		"""
		# Fetchable can be a simple string (URL) or an Artifact. They are a bit different:
		if type(fetchable) == str:
			url = fetchable
		else:
			url = fetchable.url
		now = datetime.utcnow()
		self.fc.update_one(
			{"method_name": method_name, "url": url},
			{
				"$set": {"last_attempt": now, "last_failure_on": now},
				"$push": {"failures": {"attempted_on": now, "failure_reason": failure_reason}},
			},
			upsert=True
		)


class CacheMiss(Exception):
	pass
