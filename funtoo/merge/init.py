import logging

from merge_utils.config import Configuration
import pymongo
from pymongo import MongoClient


def __init__(hub, prod=None, push=False, release=None, **kwargs):
	hub.CURRENT_SOURCE_DEF = None
	hub.SOURCE_REPOS = {}
	hub.PUSH = push
	hub.FDATA = None
	hub.PROD = False
	if prod is True:
		hub.PROD = prod
	logging.warning(f"PROD {getattr(hub, 'PROD', 'NOT DEFINED')}")
	hub.RELEASE = release
	# Passing "fastpull" kwarg to Configuration:
	hub.MERGE_CONFIG = Configuration(**kwargs)

	mc = MongoClient()
	dd = hub.DEEPDIVE = mc.metatools.deepdive
	dd.create_index("atom")
	dd.create_index([("kit", pymongo.ASCENDING), ("category", pymongo.ASCENDING), ("package", pymongo.ASCENDING)])
	dd.create_index("catpkg")
	dd.create_index("relations")
	dd.create_index("md5")
	dd.create_index("files.name", partialFilterExpression={"files": {"$exists": True}})

	di = hub.DISTFILE_INTEGRITY = mc.metatools.distfile_integrity
	di.create_index([("category", pymongo.ASCENDING), ("package", pymongo.ASCENDING), ("distfile", pymongo.ASCENDING)])

	fp = hub.FASTPULL = mc.metatools.fastpull
	fp.create_index([("hashes.sha512", pymongo.ASCENDING), ("filename", pymongo.ASCENDING)], unique=True)
	# rand_ids don't need to be unique -- they can be shared if they are pointing to the same underlying file.
	fp.create_index([("rand_id", pymongo.ASCENDING)])
	#
	# Structure of Fastpull database:
	#
	# filename: actual destination final_name, string.
	# hashes: dictionary containing:
	#   size: file size
	#   sha512: sha512 hash
	#   ... other hashes
	# rand_id: random_id from legacy fastpull. We are going to keep using this for all our new fastpulls too.
	# src_uri: URI file was downloaded from.
	# fetched_on: timestamp file was fetched on.
	# refs: list of references in packages, each item in list a dictionary in the following format:
	#  kit: kit
	#  catpkg: catpkg
	#  Some items may be omitted from the above list.
