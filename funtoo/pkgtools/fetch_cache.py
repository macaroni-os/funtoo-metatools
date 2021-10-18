#!/usr/bin/env python3
from datetime import datetime
import dyne.org.funtoo.metatools.pkgtools as pkgtools

"""

We use MongoDB to cache HTTP requests for standard REST and other live data. We also use it to record stats for
artifacts (SRC_URI files) we have downloaded. This is handy for identifying downloads that have failed for some
reason. However, Artifacts don't get cached in MongoDB but are instead written to disk. But we do cache metadata
of the downloaded artifact -- its message digests and size at the time the download was done. This allows us to

1) detect when one of the archives was modified on disk; and
2) regenerate ebuilds even if we don't have archives available (feature not yet implemented, but possible)

"""


async def fetch_cache_write(method_name, fetchable, content_kwargs=None, body=None, metadata_only=False):
	"""
	This method is called when we have successfully fetched something. In the case of a network resource such as
	a Web page, we will record the result of our fetching in the 'result' field so it is cached for later. In the
	case that we're recording that we successfully downloaded an Artifact (tarball), we don't store the tarball
	in MongoDB but we do store its metadata (hashes and filesize.)

	Note that ``content_kwargs`` is a new feature, where we will cache specific keyword arguments, such as encoding,
	used for the fetch. These keyword arguments can potentially alter the results of the cached value.

	If metadata_only is True, we are simply updating metadata rather than the content in the fetch cache.

	"""
	# Fetchable can be a simple string (URL) or an Artifact. They are a bit different:
	if type(fetchable) == str:
		url = fetchable
		metadata = None
	else:
		url = fetchable.url
		metadata = fetchable.as_metadata()
	now = datetime.utcnow()
	selector = {"method_name": method_name, "url": url, "content_kwargs": None}
	if not metadata_only:
		pkgtools.model.fetch_cache.update_one(
			selector,
			{"$set": {"last_attempt": now, "fetched_on": now, "metadata": metadata, "body": body}},
			upsert=True,
		)
	else:
		pkgtools.model.fetch_cache.update_one(
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


async def fetch_cache_read(method_name, fetchable, content_kwargs=None, max_age=None, refresh_interval=None):
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
	looking_for = {"method_name": method_name, "url": url, "content_kwargs": content_kwargs if content_kwargs else None}

	result = pkgtools.model.fetch_cache.find_one(looking_for)
	if result is None or "fetched_on" not in result:
		raise pkgtools.fetch.CacheMiss()
	elif refresh_interval is not None:
		if datetime.utcnow() - result["fetched_on"] <= refresh_interval:
			return result
		else:
			raise pkgtools.fetch.CacheMiss()
	elif max_age is not None and datetime.utcnow() - result["fetched_on"] > max_age:
		raise pkgtools.fetch.CacheMiss()
	else:
		return result


async def record_fetch_failure(method_name, fetchable, content_kwargs, failure_reason):
	"""
	It is important to document when fetches fail, and that is what this method is for.
	"""
	# Fetchable can be a simple string (URL) or an Artifact. They are a bit different:
	if type(fetchable) == str:
		url = fetchable
	else:
		url = fetchable.url
	now = datetime.utcnow()
	pkgtools.model.fetch_cache.update_one(
		{"method_name": method_name, "url": url, "content_kwargs" : content_kwargs},
		{
			"$set": {"last_attempt": now, "last_failure_on": now},
			"$push": {"failures": {"attempted_on": now, "failure_reason": failure_reason}},
		},
		upsert=True,
	)
