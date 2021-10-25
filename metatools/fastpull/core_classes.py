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

	def update_record(self, authoritative_url, new_object: BLOSObject):
		"""
		This method will update an existing record for authoritative_url, causing it to reference
		a new FastPullObject in the FPOS. This can be used to fix up the underlying file when the
		wrong file has been downloaded originally. A FastPullUpdateFailure() will be raised for
		any error condition if the operation is not successful.
		"""
