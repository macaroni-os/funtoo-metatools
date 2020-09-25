#!/usr/bin/python3
import os
import random

from pymongo import MongoClient

"""
This sub implements an even higher-level download API than `download.py`. Think of fastpull as a combination on-disk
database (where the actual distfiles are stored) along with an index which is stored in MongoDB. When fastpull indexes
a file, it is indexed by its cryptographic hashes and can only be retrieved by using these hashes (not by filename.)

Right now, when the download sub downloads a file by name, a hook is called to store the file into fastpull. But
autogen doesn't use fastpull directly for fetching, because it doesn't have any expected hashes. In this way, we
put data IN fastpull, but only the fastpull web service actually serves data OUT of fastpull.

Scratch space for ideas:

Have a unified database for queued distfiles as well as fetched distfiles. What to record:

fastpull_request
================
final_name
urls (list)
expected_hashes ---
requested_by ( kit, branch, atom, date )

If downloaded, goes over to fastpull:


fastpull
========

disk_index
hashes

final_names (indexed list, since it could have many possible final names)
last_attempted_on
fetch_log (updated for every fetch, even failures.)






requested_by (kit, branch, atom, date?) would be cool.

"""


def get_disk_path(hub, disk_index):
	return os.path.join(hub.TEMP_PATH, "fastpull", disk_index[0], disk_index[1], disk_index)


def __init__(hub):
	db = MongoClient.fastpull
	fpdf = hub.FASTPULL_DISTFILES = db.distfiles


def complete_artifact(hub, artifact, expected_final_data):
	"""
	Provided with an artifact and expected final data (hashes and size), we will attempt to locate the artifact
	binary data in the fastpull database. If we find it, we 'complete' the artifact so it is usable for extraction
	or looking at final hashes, with a correct on-disk path to where the data is located.

	Note that when we look for the completed artifact, we don't care if our data has a different 'name' -- as long
	as the binary data on disk has matching hashes and size.

	If not found, simply return None.
	"""
	result = hub.FASTPULL.find_one(expected_final_data)
	if result:
		artifact.subsystem = "fastpull"
		artifact.final_data = result
		artifact.final_path = hub._.get_disk_path(result["disk_index"])
		return artifact
	else:
		return None


def download_completion_hook(hub, artifact):
	rand_id = "".join(random.choice("abcdef0123456789") for _ in range(128))
	fastpull_path = hub._.get_disk_path(rand_id)
	os.link(artifact.final_path, fastpull_path)
	record = {"disk_index": rand_id}
	# Store hashes:
	record.update(artifact.final_data)


def add_artifact(hub, artifact):
	"""Add an artifact to the persistent download queue."""
	pass


async def fastpull_spider(hub):
	"""Start the fastpull spider, which will attempt to download queued artifacts and add them to fastpull db."""
