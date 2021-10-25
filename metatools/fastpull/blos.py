#!/usr/bin/python3
import os
from enum import Enum

import pymongo
from pymongo import MongoClient

from metatools.fastpull.download import WebSpider


# TODO: connect to spider, and add necessary mongo access.


class BLOSError(Exception):
	pass


class BLOSHashError(BLOSError):

	def __init__(self, expected: dict = None, actual: dict = None):
		self.expected = expected
		self.actual = actual


class BLOSMissingIndexError(BLOSError):
	pass


class BLOSCorruptionError(BLOSError):
	"""
	This will be raised in circumstances where the SHA512 of the on-disk file is recalculated, and
	the SHA512 of the file contents does not match the index in the BLOS. To maintain integrity of
	the BLOS, this file will automatically be removed. But this exception will still be raised to
	notify the caller of the issue.
	"""

	def __init__(self, contents_sha512=None, index_sha512=None):
		self.contents_sha512 = contents_sha512
		self.index_sha512 = index_sha512


class BLOSObject:

	def __init__(self, fpos, sha512):
		self.fpos = fpos
		self.sha512 = sha512

	def get_disk_path(self):
		return os.path.join(self.fpos.fastpull_path, self.sha512[:2], self.sha512[2:4], self.sha512[4:6], self.sha512)

	@property
	def exists(self):
		return os.path.exists(self.get_disk_path())


# TODO: Add BLOS Response object that shows what hashes were actually verified, so this can be explicitly confirmed by the
#       caller.


class BackFillStrategy(Enum):
	NONE = 0
	DESIRED = 1
	ALL = 2


class BaseLayerObjectStore:
	fastpull_path = None
	spider = None
	req_client_hashes = {"sha512"}
	req_blos_hashes = {"sha512"}
	desired_hashes = {"sha512"}
	disk_verify = {"sha512"}

	backfill = BackFillStrategy.DESIRED

	def __init__(self, fastpull_path=None, spider=None):
		mc = MongoClient()
		fp = self.c = mc.db.fastpull
		fp.create_index([("hashes.sha512", pymongo.ASCENDING)])
		fp.create_index([("rand_id", pymongo.ASCENDING)])

		self.fastpull_path = fastpull_path
		self.spider = spider

		# The hashes we require in MongoDB records include those we demand in all client 'get
		# object' requests:
		self.req_blos_hashes = self.req_client_hashes | self.req_blos_hashes | {"size"}

		self.disk_verify = self.disk_verify | {"size"}

		# The hashes we desire include those we require, plus those we need to verify on disk.
		self.desired_hashes = self.req_blos_hashes | self.desired_hashes | self.disk_verify

		"""
		``self.disk_verify``

		This is a set of hashes we will check in the actual file on disk before returning the object, 
		to ensure the integrity of the on-disk file. Filesize (aka the 'size hash') is always turned on 
		since it's an inexpensive operation.

		These on-disk values will be checked against our MongoDB BLOS record. 

		By default we will verify disk contents using SHA512 on every read. Setting this to an empty set
		causes only filesize to be checked and will improve retrieval performance at the cost of integrity.
		Increasing the number of hashes will theoretically improve integrity checking at the cost of 
		performance. Any hash we want to check on disk will automatically also get stored in the MongoDB
		records for all new BLOS objects, since this is a requirement for future validation.

		```self.req_client_hashes```

		These are the specific hashes that must be specified for object retrieval to succeed. "size"
		can be used to specify filesize of the object, even though it is not a hash. By default we 
		only need a sha512 (not filesize) in the request. Note that these are just the *required*
		hashes for the client request to succeed, so:

		1. *All specified hashes* in ``self.req_client_hashes`` must be provided in each 'get object'
		   request, and we will use these hashes to verif
		
		2. *Any additional hashes provided* will also be used for verification, if we happen to have
		   them in our MongoDB BLOS record -- AND WILL BE IGNORED OTHERWISE. "size" is one that is
		   supported by default if you want to add that, since we always record that in MongoDB.
		   If you do, then any object you retrieve will need to include a sha512 and size for the
		   request to even be processed by the BLOS. 

		Consider the capitalized phrase "AND WILL BE IGNORED OTHERWISE" above. This may seem 
		'insecure', but the BLOS is intended to be configured to enforce a desired security 
		policy. That security policy is controlled by these settings, not what hashes the
		client happens to send to it.

		Anything 'extra' you provide beyond this configured security level is 'bonus' and will not 
		be ignored if the extra supplied hashes happen to exist in the MongoDB record -- we won't 
		knowingly return an object that appears to have a hash mismatch -- but if the BLOS is not
		calculating these hashes due to configuration, then it will not have the internal data to
		verify these hashes, and will IGNORE THEM.

		For day-to-day use of the BLOS, this means you can give it "all the hashes you've got" and 
		let it take care of enforcing its security policies. This is actually a good thing, as it
		allows you to have your code just use the BLOS and let the BLOS be a 'control point' for 
		enforcing security policies.

		If you don't like default BLOS settings, then that is a good indication that you should 
		change its default security policies to reflect what you want. That's why these settings 
		exist and are verbosely documented :)

		```self.req_blos_hashes```

		This is similar to ``self.req_client_hashes`` but refers to the MongoDB BLOS records -- if these
		fields don't exist, then the MongoDB BLOS record is considered incomplete. "size" is assumed
		and doesn't need to be specified. Anything in ``self.req_client_hashes`` is added to this
		set, because we need hashes in our MongoDB BLOS records to properly satisfy the integrity
		checks we perform between client and BLOS.

		```self.desired_hashes```

		Ideally, what hashes do we want to have in our MongoDB BLOS records? That's what is specified
		here. Filesize is assumed and doesn't need to be included via 'size'. By default we will want
		sha512 too, plus any hashes listed in ``self.disk_verify`` since we will need those for disk
		verification.

		Consider this what you want the BLOS to store and be capable of using for its own disk
		integrity checks, even if those disk integrity checks may not yet be turned on.

		How we behave when a BLOS record doesn't contain the required hashes is controlled by the 
		following setting.

		``self.backfill``

		Do we expect our MongoDB BLOS records to be complete and correct, or do we allow the BLOS
		to automatically add missing hashes to its records? This is controlled by the backfill
		strategy. This should normally be set to the default setting of::

		  BackFillStrategy.DESIRED

		This default setting of ``BackFillStrategy.DESIRED`` means that if any of our desired hashes
		in ``self.desired_hashes`` (and augmented by ``self.disk_verify``) are missing from our
		MongoDB BLOS record, go ahead and add them to our BLOS record to further expand our collections
		of hashes used for integrity checks. This will be done in real-time as objects are retrieved.

		``BackFillStrategy.ALL`` should not generally be used but can be used when you have wiped
		your MongoDB BLOS, and want to offer a bunch of existing files. The MongoDB BLOS fields will
		be reconstructed in their entirety as objects are requested by SHA512. It's tempting to
		say 'this is not secure', and may not be, unless you totally trust your files on disk,
		which you might. Under regular circumstances you do not need to enable this option -- it's
		only to hold on to old disk data when you've lost your MongoDB data.

		``BackFillStrategy.NONE`` is a super-strict option and means that all MongoDB BLOS records
		should not be auto-upgraded at all. If ``self.desired_hashes`` has been 'enhanced' to
		include more hashes not found in MongoDB BLOS records, then administrator action will be
		required to add missing hash data before the BLOS is usable again. All object retrieval
		requests will fail until this is done. 

		For example, if::

		   desired_hashes = ( "size", "sha512", "blake2b" )
		   req_client_hashes = ( "sha512" )

		Then will we automatically add blake2b hashes to MongoDB BLOS records as objects are retrieved?
		This setting works in conjunction with ``self.desired_hashes``.

		"""

	def get_object(self, hashes: dict):
		"""
		Returns a FastPullObject representing the object by cryptographic hash if it exists.

		``hashes`` is a dictionary which contains "final data", which will be used to verify the integrity
		of the requested file. ``hashes['sha512']`` must exist for the lookup to succeed, or a
		``BLOSMissingIndexError`` will be raised. All other fields will be used to verify integrity only.

		``get_object()`` will always perform some level of verification for object retrieval, though there
		are ways that this can be tuned. But in all cases, *all* hashes supplied in the ``hashes`` argument
		must be in the MongoDB BLOS record for the object, and they must all match. If this is not the case,
		then a ``BLOSHashError`` will be raised detailing the mismatch.

		If integrity checks succeed, a reference to the object will be returned. If integrity checks fail,
		then a ``BLOSHashError`` will be raised with the details related to the expected and
		actual hashes in the exception itself.

		It is possible, if the file exists on disk but is not in the BLOS mongo collection, that this method
		will 'fixup' the mongo collection by adding hash information to the database. It will also at this
		point reverify the SHA512 of the file on disk. If this check fails, a BLOSCorruptionError will be
		raised, and this BLOS entry will be auto-wiped to maintain integrity of the database.

		If the requested file is not found, BLOSNotFoundError will be returned.
		"""
		if 'sha512' not in hashes:
			raise BLOSMissingIndexError()

		sha512 = hashes['sha512']
		fp = BLOSObject(self, sha512)

		if fp.exists:
		# Perform integrity checks
		else:
			return None

	def insert_object(self, temp_file, final_data=None):
		"""
		This will be used to directly add an object to fastpull, by pointing to the file to insert, and its
		final data. If no final data is provided, it will be calculated based on the contents of the temp_file.
		This file will be linked into place inside fastpull.
		"""
		pass

	def get_url(self, url, mirrors=None):
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

