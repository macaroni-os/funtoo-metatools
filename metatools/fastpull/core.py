#!/usr/bin/python3
import logging
from datetime import datetime

import pymongo

from metatools.config.mongodb import get_collection
from metatools.fastpull.blos import BaseLayerObjectStore, BLOSNotFoundError, BLOSResponse
from metatools.fastpull.spider import FetchRequest, FetchResponse


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

		assert request.url is not None

		try:

			# First, check if we have an existing association for this URL in this scope. The URL
			# will then be linked by sha512 hash to a specific object stored in the BLOS:

			existing = self.fastpull.get(self.scope, request.url)

			# IF expected hashes are supplied, then we expect the sha512 to be part of this set,
			# and we will expect that any existing association with this URL to a file will have
			# a sha512 that matches what was supplied. We will perform more detailed integrity
			# checking later if we are OK here -- in particular when the object is pulled from the
			# BLOS -- but this is the first, easiest and most obvious initial check to perform
			# before we get too involved:

			blos_index = None
			if request.expected_hashes:
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

			if existing:

				if blos_index is None:
					blos_index = {'sha512': existing['sha512']}

				# If we have gotten here, we know that any supplied sha512 hash matches the index
				# in fastpull. Now let's attempt to retrieve the object and return the BLOSResponse
				# as our return value. If this fails, we will fall back to downloading the
				# resource, inserting it into the BLOS, and returning the BLOSResponse from that.

				try:
					obj = self.fastpull.blos.get_object(hashes=blos_index)
					logging.info(f"IntegrityScope:{self.scope}.get_file_by_url: existing object found for {request.url}")
					return obj
				except BLOSNotFoundError:
					existing = False

			if not existing:
				logging.info(f"IntegrityScope:{self.scope}.get_file_by_url: existing not found; will spider for {request.url}")
				# We have attempted to find the existing resource in fastpull, so we can grab it
				# from the BLOS. That failed. So now we want to use the WebSpider to download the
				# resource. If successful, we will insert the downloaded file into the BLOS for
				# good measure, and return the BLOSResponse to the caller so they get the file
				# they were after.

				# TODO: record a record in our integrity scope! Also include fetch time, etc.
				resp: FetchResponse = await self.fastpull.spider.download(request)
				if resp.success:
					logging.info(f"IntegrityScope:{self.scope}.get_file_by_url: success for {request.url}")
					# TODO: include extra info like URL, etc. maybe allow misc metadata to flow from
					#       fetch request all the way into the BLOS.
					# This intentionally may throw a BLOSError of some kind, and we want that:
					blos_response = self.fastpull.blos.insert_object(resp.temp_path)
					self.fastpull.put(self.scope, request.url, blos_response=blos_response)
					# Tell the spider it can unlink the temporary file:
					self.fastpull.spider.cleanup(resp)
					return blos_response
				else:
					logging.info(f"IntegrityScope:{self.scope}.get_file_by_url: failure for {request.url}")
					raise FastPullFetchError()
		except Exception as e:
			logging.error(f"IntegrityScope.get_file_by_url: Error while downloading {request.url}")
			raise e

	def remove_record(self, authoritative_url):
		"""
		This will remove a record from the scope for the specified URL, if one exists. A
		FastPullUpdateFailure will be raised if the record does not exist.
		"""
		pass

	def update_record(self, authoritative_url):
		pass


class FastPullIntegrityDatabase:

	# TODO: this integrity database needs to have a DB initialized for storing references to the BLOS!
	#       The scope will use this to perform queries. Or we can provide methods here that will do the
	#       heavy lifting.

	def __init__(self, blos_path=None, spider=None, hashes: set = None):
		assert hashes
		self.hashes = hashes
		self.collection = c = get_collection('fastpull')

		# The fastpull database uses sha512 as a 'linking mechanism' to the Base Layer Object Store (BLOS). So only
		# one hash needs to be recorded, since this is not an exhaustive integrity check (that is performed by the
		# BLOS itself upon retrieval). This is stored in the 'sha512' key, which is not placed inside 'hashes' like
		# it is in the BLOS. But we do not create an index for it, since we don't encourage retrieval of objects from
		# fastpull by their hash. They should be retrieved by target URL (and scope).

		c.create_index([("scope", pymongo.ASCENDING), ("url", pymongo.ASCENDING)], unique=True)
		self.blos: BaseLayerObjectStore = BaseLayerObjectStore(blos_path, hashes=self.hashes)
		self.spider = spider
		self.scopes = {}

	def get_scope(self, scope_id):
		if scope_id not in self.scopes:
			self.scopes[scope_id] = IntegrityScope(self, scope_id)
		logging.info(f"FastPull Integrity Scope: {scope_id}")
		return self.scopes[scope_id]

	def get(self, scope, url):
		return self.collection.find_one({"url": url, "scope": scope})

	def put(self, scope, url, blos_response: BLOSResponse = None):
		logging.info(f"Scope.put: scope='{scope}' url='{url}' sha512='{blos_response.authoritative_hashes['sha512']}'")
		try:
			self.collection.update_one(
				{"url": url, "scope": scope},
				{"$set": {"sha512": blos_response.authoritative_hashes['sha512'], "updated_on": datetime.utcnow()}},
				upsert=True
			)
		except pymongo.errors.DuplicateKeyError:
			raise KeyError(f"Duplicate key error when inserting {scope} {url}")
