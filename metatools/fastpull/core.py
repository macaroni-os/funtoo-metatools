#!/usr/bin/python3
import logging
import os

from metatools.fastpull.blos import BaseLayerObjectStore, BLOSError, BLOSNotFoundError, BLOSResponse
from metatools.fastpull.spider import WebSpider, FetchRequest, FetchResponse


# TODO: add mongoisms.


class IntegrityScope:

	# https://docs.mongodb.com/manual/core/index-multikey/
	# ^^ perform multikey index on URL or just handle *authoritative URLS* (I think this is better.)

	def __init__(self, parent, scope, validate_hashes=None):
		# This is a link to the FastPullIntegrityDatabase
		if validate_hashes is None:
			validate_hashes = {"sha512"}
		self.validate_hashes = validate_hashes
		self.fastpull = parent
		self.scope = scope

	def get_file_by_url(self, request: FetchRequest) -> BLOSResponse:

		# First, check if we have an existing association for this URL in this scope. The URL
		# will then be linked by sha512 hash to a specific object stored in the BLOS:

		existing = self.fastpull.collection.findOne({"url": request.url, "scope": self.scope})

		# Now, if we retrieved an existing record, we need to perform a small amount of
		# internal integrity checking. This is not the "major integrity check" which is
		# performed by the BLOS, but we potentially have a supplied sha512 hash the
		# requester is expecting, and this should match the sha512 index we have in our
		# existing fastpull record we just retrieved. If these do not match then we know
		# right away that something is askew:

		if request.expected_hashes is not None:
			if 'sha512' not in request.expected_hashes:
				raise FastPullInvalidRequest('Please include sha512 in expected hashes.')
			if request.expected_hashes['sha512'] != existing['sha512']:
				raise FastPullIntegrityError("TODO")
			blos_index = request.expected_hashes
		else:
			# No supplied hashes were provided, so create this index for later retrieval
			blos_index = { 'sha512' : existing['sha512'] }

		if existing:

			# If we have gotten here, we know that any supplied sha512 hash matches the index
			# in fastpull. Now let's attempt to retrieve the object and return the BLOSResponse
			# as our return value. If this fails, we will fall back to downloading the
			# resource, inserting it into the BLOS, and returning the BLOSResponse from that.

			try:

				obj = self.fastpull.blos.get_object(hashes=blos_index)
				return obj
			except BLOSNotFoundError:
				existing = False

		if not existing:

			# We have attempted to find the existing resource in fastpull, so we can grab it
			# from the BLOS. That failed. So now we want to use the WebSpider to download the
			# resource. If successful, we will insert the downloaded file into the BLOS for
			# good measure, and return the BLOSResponse to the caller so they get the file
			# they were after.

			resp : FetchResponse = await self.fastpull.spider.download(request)
			if resp.success:
				# TODO: include extra info like URL, etc. maybe allow misc metadata to flow from
				# fetch request all the way into the BLOS.
				self.fastpull.blos.insert_object(resp.temp_path)
				# Insert into BLOS, return BLOSObject
			else:
				raise FastPullFetchError()

			# TODO -- handle exceptions....
			temp_path, final_data = await self.fastpull.spider.download(authoritative_url, mirrors=mirrors)
			fastpull_path = self.fastpull_path(final_data["hashes"]["sha512"])

		else:
			# download and store record, and store in BLOS



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


class FastPullIntegrityDatabase:

	def __init__(self, fastpull_path, spider_temp_path):
		self.blos : BaseLayerObjectStore = BaseLayerObjectStore(fastpull_path)
		self.spider = WebSpider(spider_temp_path)
		self.scopes = {}

	def get_scope(self, scope_id):
		if scope_id not in self.scopes:
			self.scopes[scope_id] = IntegrityScope(self, scope_id)
		return self.scopes[scope_id]