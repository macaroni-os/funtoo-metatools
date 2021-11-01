#!/usr/bin/python3
import os
from enum import Enum

import pymongo
from pymongo import MongoClient

from metatools.fastpull.download import WebSpider


class FastPullError(Exception):
	pass


class FastPullIntegrityError(FastPullError):
	pass


class FastPullRetrievalFailure(FastPullError):
	pass


class FastPullUpdateFailure(FastPullError):
	pass


class FastPullIntegrityDatabase:

	def __init__(self, fpos: FastPullObjectStore):
		self.fpos = fpos

# TODO: add mongoisms.


class FastPullIntegrityScope:

	# https://docs.mongodb.com/manual/core/index-multikey/
	# ^^ perform multikey index on URL or just handle *authoritative URLS* (I think this is better.)

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

		# THIS WAS PULLED OVER FROM THE BLOSObjectStore() get_url method -- and uses the BLOSObjectStore's
		# spider object. But maybe we should move it over here.

		"""
		This method is used by the integrity database to request an object that has not yet been downloaded.
		``get_url`` will leverage ``self.spider`` to download the requested resource and if successful, store
		the result in the FPOS, and return a reference to this new object.

		``url`` specifies the URL for the resource requested.
		``mirrors`` is an optional list of alternate URLs for the requested resource.

		If successful, a FastPullObject will be returned representing the result of the fetch. If the fetch fails
		for whatever reason, a FastPullObjectStoreError exception will be raised containing information regarding
		what failed.
		"""
		# TODO -- handle exceptions....
		temp_path, final_data = await self.spider.download(url, mirrors=mirrors)
		fastpull_path = self.fastpull_path(final_data["hashes"]["sha512"])

		try:
			os.makedirs(os.path.dirname(fastpull_path), exist_ok=True)
			os.link(temp_path, fastpull_path)
		except FileExistsError:
			pass
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

	def remove_record(self, authoritative_url):
		"""
		This will remove a record from the scope for the specified URL, if one exists. A
		FastPullUpdateFailure will be raised if the record does not exist.
		"""

	def update_record(self, authoritative_url, new_object: BLOSObject):
		"""
		This method will update an existing record for authoritative_url, causing it to reference
		a new FastPullObject in the FPOS. This can be used to fix up the underlying file when the
		wrong file has been downloaded originally. A FastPullUpdateFailure() will be raised for
		any error condition if the operation is not successful.
		"""
