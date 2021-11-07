#!/usr/bin/python3
import os

from metatools.fastpull.blos import BaseLayerObjectStore, BLOSNotFoundError, BLOSResponse, BLOSError
from metatools.fastpull.spider import WebSpider, FetchRequest, FetchResponse


class FastPullError(Exception):
	pass


class FastPullInvalidRequest(FastPullError):
	pass


class FastPullIntegrityError(FastPullError):

	def __init__(self, invalid_hashes):
		self.invalid_hashes = invalid_hashes


class FastPullFetchError(FastPullError):
	pass


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

	async def get_file_by_url(self, request: FetchRequest) -> BLOSResponse:

		# First, check if we have an existing association for this URL in this scope. The URL
		# will then be linked by sha512 hash to a specific object stored in the BLOS:

		existing = self.fastpull.collection.findOne({"url": request.url, "scope": self.scope})

		# IF expected hashes are supplied, then we expect the sha512 to be part of this set,
		# and we will expect that any existing association with this URL to a file will have
		# a sha512 that matches what was supplied. We will perform more detailed integrity
		# checking later if we are OK here -- in particular when the object is pulled from the
		# BLOS -- but this is the first, easiest and most obvious initial check to perform
		# before we get too involved:

		if request.expected_hashes is not None:
			if 'sha512' not in request.expected_hashes:
				raise FastPullInvalidRequest('Please include sha512 in expected hashes.')
			if existing and request.expected_hashes['sha512'] != existing['sha512']:
				raise FastPullIntegrityError(invalid_hashes={
					'sha512': {
						'supplied': request.expected_hashes['sha512'],
						'recorded': existing['sha512']
					}
				})
			# This will potentially supply extra hashes to for retrieval, which will be
			# used by the BLOS to perform more exhaustive verification.
			blos_index = request.expected_hashes
		else:
			# No supplied hashes were provided, so create this index for later retrieval
			blos_index = {'sha512': existing['sha512']}

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

		else:

			# We have attempted to find the existing resource in fastpull, so we can grab it
			# from the BLOS. That failed. So now we want to use the WebSpider to download the
			# resource. If successful, we will insert the downloaded file into the BLOS for
			# good measure, and return the BLOSResponse to the caller so they get the file
			# they were after.

			resp: FetchResponse = await self.fastpull.spider.download(request, cleanup=False)
			if resp.success:
				# TODO: include extra info like URL, etc. maybe allow misc metadata to flow from
				#       fetch request all the way into the BLOS.
				# This intentionally may throw a BLOSError of some kind, and we want that:
				blos_response = self.fastpull.blos.insert_object(resp.temp_path)
				# Tell the spider it can unlink the temporary file:
				self.fastpull.spider.cleanup(resp)
				return blos_response
			else:
				raise FastPullFetchError()

	# TODO:

	def remove_record(self, authoritative_url):
		"""
		This will remove a record from the scope for the specified URL, if one exists. A
		FastPullUpdateFailure will be raised if the record does not exist.
		"""
		pass

	def update_record(self, authoritative_url):
		pass


class FastPullIntegrityDatabase:

	def __init__(self, fastpull_path=None, spider=None):
		self.blos: BaseLayerObjectStore = BaseLayerObjectStore(fastpull_path)
		self.spider = spider
		self.scopes = {}

	def get_scope(self, scope_id):
		if scope_id not in self.scopes:
			self.scopes[scope_id] = IntegrityScope(self, scope_id)
		return self.scopes[scope_id]
