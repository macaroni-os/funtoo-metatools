#!/usr/bin/python3
import logging
import os

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


def get_disk_path(hub, final_data):
	sh = final_data["hashes"]["sha512"]
	return os.path.join(hub.MERGE_CONFIG.fastpull_path, sh[:2], sh[2:4], sh[4:], sh)


def complete_artifact(hub, artifact):
	"""
	Provided with an artifact and expected final data (hashes and size), we will attempt to locate the artifact
	binary data in the fastpull database. If we find it, we 'complete' the artifact so it is usable for extraction
	or looking at final hashes, with a correct on-disk path to where the data is located.

	Note that when we look for the completed artifact, we don't care if our data has a different 'name' -- as long
	as the binary data on disk has matching hashes and size.

	If not found, simply return None.

	This method was originally intended to allow us to specify expected final data, aka hashes, that we expect to
	see. But this is not really used by autogen at the moment. The reason is that while emerge and ebuild do
	Manifest/hash validation on the client side, this is because we want to ensure that what was downloaded by the
	client matches what was set by the server. But we don't have such checks on just the server side.
	"""
	fp = hub._.get_disk_path(artifact.final_data)
	if not fp:
		return None
	hashes = hub.pkgtools.download.calc_hashes(fp)
	if hashes["sha512"] != artifact.final_data["sha512"]:
		return None
	if hashes["size"] != artifact.final_data["size"]:
		return None
	artifact.final_data = hashes
	artifact.final_path = fp
	artifact.subsystem = "fastpull"
	return artifact


def download_completion_hook(hub, final_data, final_path):
	fastpull_path = hub._.get_disk_path(final_data)
	if not os.path.exists(fastpull_path):
		try:
			os.makedirs(os.path.dirname(fastpull_path), exist_ok=True)
			os.link(final_path, fastpull_path)
		except Exception as e:
			# Multiple doits running in parallel, trying to link the same file -- could cause exceptions:
			logging.error(f"Exception encountered when trying to link into fastpull (may be harmless) -- {repr(e)}")


def add_artifact(hub, artifact):
	"""Add an artifact to the persistent download queue."""
	pass


async def distfile_service(hub):
	pass


async def fastpull_spider(hub):
	"""Start the fastpull spider, which will attempt to download queued artifacts and add them to fastpull db."""
	pass
