#!/usr/bin/python3
import pymongo
from pymongo import MongoClient

"""
The DeepDive database is designed to get wiped and re-loaded to contain only the metadata for all ebuilds processed
in the last merge-kits run.

In constrast, the Distfile Integrity database is intended to be persistent and store cryptographic hashes related
to distfiles used by catpkgs. This allows us to autogen ebuilds without having the actual distfile present, and ensures
that distfile hashes don't magically change if a newly-fetched distfile has been modified upstream.

The Distfile Integrity database also ensures that we work well with fastpull. When we do autogen, all we have for
an individual autogen is the name of the distfile. We need a way to map this to a SHA1 hash so we can retrieve the
file from fastpull if it exists. So while we don't need a DB to serve fastpull downloads to users, we DO need a DB
to find things in fastpull when we're doing autogen.

The Distfile Integrity database is designed so that each release/kit/branch has its own 'namespace' where it stores
mappings from distfile names to final_data (cryptographic hashes.)

The one challenge that appears necessary to resolve with the Distfile Integrity Database is that we can potentially have
multiple 'doit' processes accessing it at the same time and reading and writing to it, due to 'merge-kits'
multi-threaded architecture.

However, this is not needed -- due to the design of 'merge-kits', and the fact that 'doit'
will be running on a particular release, kit and branch, any reads and writes will not clobber one another, and thus
we don't need to arbitrate/lock access to the Distfile Integrity DB. The Architecture makes it safe.
"""


def __init__(hub):
	mc = MongoClient()

	dd = hub.DEEPDIVE = mc.metatools.deepdive
	dd.create_index("atom")
	dd.create_index([("kit", pymongo.ASCENDING), ("category", pymongo.ASCENDING), ("package", pymongo.ASCENDING)])
	dd.create_index("catpkg")
	dd.create_index("relations")
	dd.create_index("md5")

	di = hub.DISTFILE_INTEGRITY = mc.metatools.distfile_integrity
	di.create_index(
		[
			("release", pymongo.ASCENDING),
			("kit", pymongo.ASCENDING),
			("branch", pymongo.ASCENDING),
			("distfile", pymongo.ASCENDING),
		]
	)


def get_distfile_integrity(hub, release=None, kit=None, branch=None, distfile=None):
	return hub.DISTFILE_INTEGRITY.find_one({"release": release, "kit": kit, "branch": branch, "distfile": distfile})


def store_distfile_integrity(hub, release=None, kit=None, branch=None, artifact=None):
	"""
	Store something in the distfile integrity database. This method is not thread-safe so you should call it from the
	main thread of 'doit' and not a sub-thread.
	"""
	out = {
		"release": release,
		"kit": kit,
		"branch": branch,
		"distfile": artifact.final_name,
		"final_data": artifact.final_data,
	}
	hub.DISTFILE_INTEGRITY.insert_one(out)
