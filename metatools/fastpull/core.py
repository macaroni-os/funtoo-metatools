#!/usr/bin/python3
import logging
from datetime import datetime

import pymongo

from metatools.config.mongodb import get_collection
from metatools.fastpull.blos import BLOSNotFoundError, BLOSObject
from metatools.fastpull.spider import FetchRequest, Download


class IntegrityScope:

	def __init__(self, parent, scope, validate_hashes=None):
		if validate_hashes is None:
			validate_hashes = {"sha512"}
		self.validate_hashes = validate_hashes
		self.parent = parent
		self.scope = scope

	async def _get_file_by_url_new(self, request: FetchRequest) -> BLOSObject:
		"""
		The ``_new`` in the name means that this function is designed to retrieve a reference to a file, but
		we don't have any expected cryptographic hashes for the file (thus, it is 'new'.)

		While this method accepts a FetchRequest, really, we may not do any fetching at all -- but we're ready
		to do some fetching if we need to.

		We'll first look at our IntegrityScope and see if we have an existing reference ('ref') to this file,
		by looking it up by the ``request.url``. We may have a record for it in our IntegrityScope, in which case we can
		try to retrieve it from the BLOS, using the ``sha512`` hash as a 'link' to the file in the BLOS. If we have
		a ref, but the BLOS object is missing for some reason, we will raise an exception as this can indicate
		a problem with our BLOS and we should not try to fix this automatically.

		If we have no local copy in the BLOS, we will definitely have to start a fresh download. We will leverage
		the data in the FetchRequest and use the Spider to launch a streaming HTTP download. This will also transparently
		handle the situation where we are *currently downloading* this file, for another asyncio task, and will
		internally wait for this download to finish rather than launching a new download.

		If our request actually initiated a fresh download, then when the download completes, the
		``self.parent.fetch_completion_callback`` we specified will cause some actions to happen. The downloaded
		file will be injected into the BLOS.

		Whether we initiated the download or not, we will get back the result of this pipeline and get the
		BLOSObject for the inserted object returned to us. We will pass this object back to the caller.

		If there is some kind of FetchError that could not be managed, it will be raised by the Spider, so that
		the root cause of the fetch error can be propagated to the caller.
		"""
		existing_ref = self.parent.get(self.scope, request.url)
		if existing_ref:
			try:
				obj = self.parent.blos.get_object(hashes={'sha512': existing_ref['sha512']})
				logging.info(f"IntegrityScope:{self.scope}._get_file_by_url_new: existing object found for ref {request.url}")
				return obj
			except BLOSNotFoundError as bnfe:
				logging.error(f"IntegrityScope:{self.scope}._get_file_by_url_new: ref {request.url} (sha512: {existing_ref['sha512']} NOT FOUND in BLOS. This can indicate a BLOS problem or corruption, so aborting rather than fixing.")
				raise bnfe
		blos_obj = await self.parent.spider.download(request, completion_pipeline=[self.parent.fetch_completion_callback])
		assert isinstance(blos_obj, BLOSObject)
		self.parent.put(self.scope, request.url, blos_object=blos_obj)
		return blos_obj

	async def _get_file_by_url_with_expected_hashes(self, request: FetchRequest) -> BLOSObject:
		"""
		This method attempts to return a reference to a file (``BLOSObject``) associated with the URL
		in ``request.url``, and also performs additional verification to ensure that ``request.expected_hashes``
		match the hashes we see along the way. So various additional checks are performed, making it more
		complex than just retrieving a file for which we don't have any expected hashes.
		"""
		# TODO:
		raise NotImplementedError()

	async def get_file_by_url(self, request: FetchRequest) -> BLOSObject:
		"""


		           This design is intended to allow for a very predicatable mechanism for calling
		           ``get_file_by_url``, with minimal surprises for the caller. If higher-level code
		           wants to raise exceptions, they can create one from the information in any failed
		           FetchResponses.

		This method will attempt to return a BLOSObject reference to binary data which is associated with
		a URL, referenced by ``request.url``, in this ``IntegrityScope``. Typically, this means that a
		tarball is being requested, and we may have this tarball already available locally, or we may
		need to use the ``Spider`` to download it. This is the method used to retrieve ``Artifact``s
		from the interwebs.

		The ``FetchRequest`` ``request`` *may* include expected hashes for this particular object, in
		which case these hashes will be used to verify the integrity of the result by lower layers, and
		an exception will be raised if the expected hashes do not match the actual hashes.

		If the object associated with the URL is available locally, a ``BLOSObject`` will be returned
		that references this object (assuming hashes match, if supplied.)

		In the case that the URL has not yet been retrieved and, it will be downloaded, and inserted into
		the BLOS, and a reference to this inserted file will be returned (assuming hashes match, if
		supplied.)

		If the file is currently in the process of being downloaded, but this download has not completed
		yet, this call will block until the download has completed, and then a reference to the resultant
		BLOSObject will be returned (assuming hashes match, if supplied.)

		The specific flow that will be followed is:

		1. We will see if we have a reference for this URL in our IntegrityScope. If we do, we assume
		   that we should be able to retrieve a BLOSObject, so we will attempt to retrieve a local copy
		   of the object from the BLOS. If this fails, we will fall back to downloading it (following step 2, below.)

	    2. If we do not have a reference to this URL in our IntegrityScope, we will see if there are
	       any expected hashes. If there are, we will attempt to bypass starting a download and first
	       see if we can retrieve the object from the BLOS directly. If we don't have expected hashes,
	       then we will use the Spider to start the download of this file and retrieve the BLOSObject.

	    A callback will be passed to the Spider download so that once the download has completed
	    successfully, the temporary file will be inserted into the BLOS only once. The BLOSObject
	    associated with this file will be returned to all active callers of this method that are waiting
	    for the object to be retrieved. This allows the object to be requested multiple times even
	    after a download has started without causing the file to be downloaded more than once, or
	    inserted into the BLOS more than once.

		"""

		if request.expected_hashes:
			return await self._get_file_by_url_with_expected_hashes(request)
		else:
			return await self._get_file_by_url_new(request)

		# assert request.url is not None
		#
		# try:
		#
		# 	# First, check if we have an existing association for this URL in this scope. The URL
		# 	# will then be linked by sha512 hash to a specific object stored in the BLOS:
		#
		# 	existing = self.parent.get(self.scope, request.url)
		#
		# 	# IF expected hashes are supplied, then we expect the sha512 to be part of this set,
		# 	# and we will expect that any existing association with this URL to a file will have
		# 	# a sha512 that matches what was supplied. We will perform more detailed integrity
		# 	# checking later if we are OK here -- in particular when the object is pulled from the
		# 	# BLOS -- but this is the first, easiest and most obvious initial check to perform
		# 	# before we get too involved:
		#
		# 	blos_index = None
		# 	if request.expected_hashes:
		# 		if 'sha512' not in request.expected_hashes:
		# 			raise FastPullInvalidRequest('Please include sha512 in expected hashes.')
		# 		if existing and request.expected_hashes['sha512'] != existing['sha512']:
		# 			raise FastPullIntegrityError(invalid_hashes={
		# 				'sha512': {
		# 					'supplied': request.expected_hashes['sha512'],
		# 					'recorded': existing['sha512']
		# 				}
		# 			})
		# 		# This will potentially supply extra hashes to for retrieval, which will be
		# 		# used by the BLOS to perform more exhaustive verification.
		# 		blos_index = request.expected_hashes
		#
		# 	if existing:
		#
		# 		if blos_index is None:
		# 			blos_index = {'sha512': existing['sha512']}
		#
		# 		# If we have gotten here, we know that any supplied sha512 hash matches the index
		# 		# in fastpull. Now let's attempt to retrieve the object and return the BLOSResponse
		# 		# as our return value. If this fails, we will fall back to downloading the
		# 		# resource, inserting it into the BLOS, and returning the BLOSResponse from that.
		#
		# 		try:
		# 			obj = self.parent.blos.get_object(hashes=blos_index)
		# 			logging.info(f"IntegrityScope:{self.scope}.get_file_by_url: existing object found for {request.url}")
		# 			return obj
		# 		except BLOSNotFoundError:
		# 			logging.info(f"IntegrityScope:{self.scope}.get_file_by_url: not found {request.url} in BLOS, so will refetch.")
		# 			existing = False
		#
		# 	if not existing:
		# 		return await self.parent.fetch_object(request)
		# except Exception as e:
		# 	logging.error(f"IntegrityScope.get_file_by_url:{threading.get_ident()} Error while downloading {request.url}")
		# 	raise e

	def remove_record(self, authoritative_url):
		"""
		This will remove a record from the scope for the specified URL, if one exists. A
		FastPullUpdateFailure will be raised if the record does not exist.
		"""
		pass

	def update_record(self, authoritative_url):
		pass


class IntegrityDatabase:

	# TODO: this integrity database needs to have a DB initialized for storing references to the BLOS!
	#       The scope will use this to perform queries. Or we can provide methods here that will do the
	#       heavy lifting.

	def __init__(self, blos=None, spider=None, hashes: set = None):
		assert hashes
		self.hashes = hashes
		self.blos = blos
		self.collection = c = get_collection('fastpull')

		# The fastpull database uses sha512 as a 'linking mechanism' to the Base Layer Object Store (BLOS). So only
		# one hash needs to be recorded, since this is not an exhaustive integrity check (that is performed by the
		# BLOS itself upon retrieval). This is stored in the 'sha512' key, which is not placed inside 'hashes' like
		# it is in the BLOS. But we do not create an index for it, since we don't encourage retrieval of objects from
		# fastpull by their hash. They should be retrieved by target URL (and scope).

		c.create_index([("scope", pymongo.ASCENDING), ("url", pymongo.ASCENDING)], unique=True)
		self.spider = spider
		self.scopes = {}

	def get_scope(self, scope_id):
		if scope_id not in self.scopes:
			self.scopes[scope_id] = IntegrityScope(self, scope_id)
		logging.info(f"FastPull Integrity Scope: {scope_id}")
		return self.scopes[scope_id]

	def get(self, scope, url):
		return self.collection.find_one({"url": url, "scope": scope})

	def put(self, scope, url, blos_object: BLOSObject = None):
		logging.info(f"Scope.put: scope='{scope}' url='{url}' sha512='{blos_object.authoritative_hashes['sha512']}'")
		try:
			self.collection.update_one(
				{"url": url, "scope": scope},
				{"$set": {"sha512": blos_object.authoritative_hashes['sha512'], "updated_on": datetime.utcnow()}},
				upsert=True
			)
		except pymongo.errors.DuplicateKeyError:
			raise KeyError(f"Duplicate key error when inserting {scope} {url}")

	def fetch_completion_callback(self, download: Download) -> None:
		"""
		This method is intended to be called *once* when an actual in-progress download of a tarball (by
		the Spider) has completed. It performs several important finalization actions upon successful
		download:

		1. The downloaded file will be stored in the BLOS, and the resultant BLOSObject will be assigned to
		``response.blos_object``.

		2. The Spider will be told to clean up the temporary file, as it will not be accessed directly by
		   anyone -- only the permanent file inserted into the BLOS will be handed back (via
		   ``response.blos_object``.
		"""

		blos_object = self.blos.insert_object(download.temp_path)
		self.spider.cleanup(download)
		return blos_object

	# async def fetch_object(self, request: FetchRequest):
	#
	# 	# TODO: the new logic should tell the spider to download the file -- we should not
	# 	# have the caller interact directly with the spider. We should pass the BLOS to indicate
	# 	# that the spider should store the file in the BLOS when complete, if possible, and
	# 	# return the BLOSResponse to the caller.
	#
	#
	# 	# We have attempted to find the existing resource in fastpull, so we can grab it
	# 	# from the BLOS. That failed. So now we want to use the WebSpider to download the
	# 	# resource. If successful, we will insert the downloaded file into the BLOS for
	# 	# good measure, and return the BLOSResponse to the caller so they get the file
	# 	# they were after.
	# 	# TODO: this is not working
	# 	logging.info(
	# 		f"IntegrityScope:{self.scope}.get_file_by_url:{threading.get_ident()} existing not found; will call spider for {request.url}")
	#
	# 	# TODO: BAD: WE DON'T WANT TO INSERT INTO THE BLOS HERE! THE SPIDER SHOULD ALREADY TAKE CARE OF THAT FOR US.
	# 	#       OTHERWISE WE GET A RACE CONDITION IF WE HAVE MULTIPLE futures WAITING ON THE SAME FILE. FIRST BLOS
	# 	#       INSERT WILL SUCCEED BUT SECOND WILL FAIL SINCE WE ALREADY TOLD THE SPIDER TO CLEAN UP THE FILE.
	# 	#       So we can move the code below into the BLOS, and have the BLOS start the download, and populate the
	# 	#       BLOS, and then return the BLOSResponse. We should not be tyring to connect the spider and the BLOS
	# 	#       together ourselves.
	#
	# 	# TODO: record a record in our integrity scope! Also include fetch time, etc.
	# 	resp: FetchResponse = await self.fastpull.spider.download(request)
	# 	if resp.success:
	# 		logging.info(f"IntegrityScope:{self.scope}.get_file_by_url: success for {request.url}")
	# 		# TODO: include extra info like URL, etc. maybe allow misc metadata to flow from
	# 		#       fetch request all the way into the BLOS.
	# 		# This intentionally may throw a BLOSError of some kind, and we want that:
	# 		blos_object = self.fastpull.blos.insert_object(resp.temp_path)
	# 		self.fastpull.put(self.scope, request.url, blos_object=blos_object)
	# 		# Tell the spider it can unlink the temporary file:
	# 		self.fastpull.spider.cleanup(resp)
	# 		return blos_object
	# 	else:
	# 		logging.info(f"IntegrityScope:{self.scope}.get_file_by_url: failure for {request.url}")
	# 		raise FastPullFetchError()
