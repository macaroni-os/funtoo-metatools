#!/usr/bin/python3
import os
import pymongo
from pymongo import MongoClient

from metatools.fastpull.download import WebSpider


class FastPullObjectStoreError(Exception):
	pass


class FastPullObject:

	def __init__(self, fpos, sha512):
		self.fpos = fpos
		self.sha512 = sha512

	def get_disk_path(self):
		return os.path.join(self.fpos.fastpull_path, self.sha512[:2], self.sha512[2:4], self.sha512[4:6], self.sha512)

	@property
	def exists(self):
		return os.path.exists(self.get_disk_path())

	# TODO: get size, verify size, verify hash


class FastPullObjectStore:

	fastpull_path = None
	spider = None

	def __init__(self, fastpull_path, temp_path):
		mc = MongoClient()
		fp = self.c = mc.db.fastpull
		fp.create_index([("hashes.sha512", pymongo.ASCENDING)])
		fp.create_index([("rand_id", pymongo.ASCENDING)])

		self.temp_path = temp_path
		self.fastpull_path = fastpull_path
		self.spider = WebSpider(temp_path)

	def get_object(self, sha512):
		"""
		Returns a FastPullObject representing the object by cryptographic hash if it exists, else None.
		"""
		fp = FastPullObject(self, sha512)
		if fp.exists:
			return fp
		else:
			return None

	def insert_object(self, temp_file, final_data=None):
		"""
		This will be used to directly add an object to fastpull, by pointing to the file to insert, and its
		final data. If no final data is provided, it will be calculated based on the contents of the temp_file.
		This file will be linked into place inside fastpull.
		"""
		pass

	def populate_object(self, authoritative_url, url_list=None):
		"""
		This method will attempt to populate the fastpull database by requesting an object by attempting every
		URL in url_list in succession. url_list is intended to support alternative mirrors for a single file, and
		the URLs in url_list should reference a file that is considered to be 'the same resource'.

		If successful, a FastPullObject will be returned representing the result of the fetch. If the fetch fails
		for whatever reason, a FastPullObjectStoreError exception will be raised containing information regarding
		what failed.
		"""
		pass

		temp_path, final_data = await self.spider.download(authoritative_url)

		fastpull_path = self.fastpull_path(final_data["hashes"]["sha512"])

		try:
			os.makedirs(os.path.dirname(fastpull_path), exist_ok=True)
			os.link(temp_path, fastpull_path)
		except FileExistsError:
		# FL-8301: address possible race condition
		except FileNotFoundError:
			# This should not happen -- means someone cleaned up our temp_path during download. In this case, the
			# download should likely fail.
			raise FastPullObjectStoreError("Temp file {temp_path} appears to have been removed underneath us!")


		# TODO: this is likely a good place for GPG verification. Implement.
		finally:
			if os.path.exists(temp_path):
				try:
					os.unlink(temp_path)
				except FileNotFoundError:
					# FL-8301: address possible race condition
					pass

class FastPullError(Exception):
	pass


class FastPullIntegrityError(FastPullError):
	pass


class FastPullRetrievalFailure(FastPullError):
	pass


class FastPullUpdateFailure(FastPullError):
	pass


class FastPullIntegrityDatabase:

	def __init__(self, fpos : FastPullObjectStore):
		self.fpos = fpos

	# TODO: add mongoisms.


class FastPullIntegrityScope:

	def __init__(self, fpid: FastPullIntegrityDatabase, scope):
		self.fpid = fpid
		self.scope = scope

	def get_file_by_url(self, authoritative_url, url_list=None, expected=None):
		"""
		This method is used to retrieve a file by URL, for a specific integrity scope.

		The authoritative_url represents the 'official URL' for the resource.

		url_list specifies a list of optional URLs, such as mirrors, to retrieve the resource.

		expected may be dictionary in the following format -- with all fields optional -- to specify
		expected values for hashes and size::

			{
				"sha512" : <sha512>,
				"size" : size_in_bytes
			}

		In case of failure, a FastPullIntegrityError will be raised if hashes or size do
		not match expected values, and a FastPullRetrievalError will be raised if the resource
		could not be retrieved at all.
		"""
		pass

	def remove_record(self, authoritative_url):
		"""
		This will remove a record from the scope for the specified URL, if one exists. A
		FastPullUpdateFailure will be raised if the record does not exist.
		"""

	def update_record(self, authoritative_url, new_object:FastPullObject):
		"""
		This method will update an existing record for authoritative_url, causing it to reference
		a new FastPullObject in the FPOS. This can be used to fix up the underlying file when the
		wrong file has been downloaded originally. A FastPullUpdateFailure() will be raised for
		any error condition if the operation is not successful.
		"""