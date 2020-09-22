#!/usr/bin/env python3
import json
import os
from collections import defaultdict

try:
	import pymongo
	import pymongo.errors
	from pymongo import MongoClient
except ImportError:
	pass


def init_kit_cache(hub):
	hub.KIT_CACHE = defaultdict(dict)
	hub.KIT_CACHE_TOUCHED = defaultdict(lambda: defaultdict(bool))


def __init__(hub):
	hub._.init_kit_cache()

	# mc.create_index("atom")
	# mc.create_index([("kit", pymongo.ASCENDING), ("category", pymongo.ASCENDING), ("package", pymongo.ASCENDING)])
	# mc.create_index("catpkg")
	# mc.create_index("relations")
	# mc.create_index("md5")


def get_outpath(hub, kit_dict):
	os.makedirs(os.path.join(hub.MERGE_CONFIG.temp_path, "kit_cache"), exist_ok=True)
	return os.path.join(hub.MERGE_CONFIG.temp_path, "kit_cache", f"{kit_dict['name']}-{kit_dict['branch']}")


def fetch_kit(hub, kit_dict):
	"""
	Grab cached metadata for an entire kit from MongoDB, with a single query.
	"""
	outpath = hub._.get_outpath(kit_dict)
	if os.path.exists(outpath):
		with open(outpath, "r") as f:
			atoms = json.loads(f.read())
	else:
		atoms = {}
	hub.KIT_CACHE[kit_dict["name"]][kit_dict["branch"]] = atoms


def flush_kit(hub, kit_dict, save=True):
	"""
	Write out our in-memory copy of our entire kit metadata, which may contain updates.

	If `save` is False, simply empty without saving.
	"""
	if not save:
		hub._.init_kit_cache()
		return
	if not hub.KIT_CACHE_TOUCHED[kit_dict["name"]][kit_dict["branch"]]:
		return
	if kit_dict["name"] in hub.KIT_CACHE and kit_dict["branch"] in hub.KIT_CACHE[kit_dict["name"]]:
		outpath = hub._.get_outpath(kit_dict)
		outdata = hub.KIT_CACHE[kit_dict["name"]][kit_dict["branch"]]
		with open(outpath, "w") as f:
			f.write(json.dumps(outdata))
		hub.KIT_CACHE_TOUCHED[kit_dict["name"]][kit_dict["branch"]] = False


def get_atom(hub, kit_repo, atom, md5, eclass_hashes):
	"""
	Read from our in-memory kit metadata cache. Return something if available, else None.

	This will validate that our in-memory record has a matching md5 and that md5s of all
	eclasses match. Otherwise we treat this as a cache miss.
	"""
	existing = None
	cache = hub.KIT_CACHE[kit_repo.name][kit_repo.branch]
	if atom in cache and cache[atom]["md5"] == md5:
		existing = cache[atom]
		if existing["eclasses"]:
			bad = False
			for eclass, md5 in existing["eclasses"]:
				if eclass not in eclass_hashes:
					bad = True
					break
				if eclass_hashes[eclass] != md5:
					bad = True
					break
			if bad:
				# stale cache entry, don't use.
				existing = None
	return existing


def update_atom(hub, td_out):
	"""
	Update our in-memory record for a specific ebuild atom on disk that has changed. This will
	be written out by flush_kit(). Right now we just record it in memory.

	"""
	hub.KIT_CACHE_TOUCHED[td_out["kit"]][td_out["branch"]] = True
	hub.KIT_CACHE[td_out["kit"]][td_out["branch"]][td_out["atom"]] = td_out
