#!/usr/bin/env python3

import asyncio
import hashlib
import logging
import os
import sys
from subprocess import getstatusoutput

"""
This sub deals with the higher-level logic related to downloading of distfiles. Where the 'fetch.py'
sub deals with grabbing HTTP data from APIs, this is much more geared towards grabbing tarballs that
are bigger, and organizing them into a distfiles directory. This includes calculating cryptographic
hashes on the resultant downloads and ensuring they match what we expect.

The implementation is based around a class called `Download`.

Because autogen is multi-threaded, it's possible for two autogens to try downloading the same file
at the same time. If they create a `Download` object, this special class will do the magic of looking
at `hub.DL_ACTIVE` for any active downloads of the same file, and if one exists, it will not fire
off a new download but instead wait for the existing download to complete. So the 'downloader'
(code trying to download the file) can remain ignorant of the fact that the download was already
started previously.

This allows multi-threaded downloads of potentially identical files to work without complication in
the autogen.py files or generators so that this complexity does not have to be dealt with by those
who are simply writing autogens.
"""


def __init__(hub):

	hub.CHECK_DISK_HASHES = False
	hub.DL_ACTIVE = {}
	# This DL_ACTIVE_COUNT is used to limit the number of simultaneous downloads (to 24):
	hub.DL_ACTIVE_COUNT = asyncio.Semaphore(value=24, loop=asyncio.get_event_loop())


HASHES = ["sha256", "sha512", "blake2b"]

# TODO: implement different download strategies with different levels of security. Maybe as a
#       declarative pipeline.


async def ensure_fetched(hub, artifact):
	if artifact.is_fetched(hub, artifact):
		if artifact.final_data is not None:
			return
		else:
			# TODO: put this in a threadpool to avoid multiple simultaneous hash calcs on same file:
			artifact.record_final_data(await calc_hashes(hub, artifact.final_path))
	else:
		if artifact.final_name in hub.DL_ACTIVE:
			# Active download -- wait for it to finish:
			print(f"Waiting for {artifact.final_name} to finish")
			await hub.DL_ACTIVE[artifact.final_name].wait_for_completion(artifact)
		else:
			# No active download for this file -- start one:
			print(f"Starting download of {artifact.final_name}")
			dl_file = Download(hub, artifact)
			await dl_file.download()


class Download:

	"""
	When we need to download an artifact, we create a download. Multiple, co-existing Artifact
	objects can reference the same file. Rather than have them try to download the same file
	at the same time, they leverage a "Download" which eliminates conflicts and manages the
	retrieval of the file.

	The Download object will record all Artifacts that need this file, and arbitrate the download
	of this file and update the Artifacts with the completion data when the download is complete.

	"""

	def __init__(self, hub, artifact):
		self.hub = hub
		self.final_name = artifact.final_name
		self.url = artifact.url
		self.artifacts = [artifact]
		self.futures = []

	def add_artifact(self, artifact):
		self.artifacts.append(artifact)

	def wait_for_completion(self, artifact):
		self.artifacts.append(artifact)
		fut = asyncio.get_event_loop().create_future()
		self.futures.append(fut)
		return fut

	async def download(self):
		await self.hub.DL_ACTIVE_COUNT.acquire()
		self.hub.DL_ACTIVE[self.final_name] = self
		final_data = await _download(self.hub, self.artifacts[0])
		for artifact in self.artifacts:
			artifact.record_final_data(final_data)
		del self.hub.DL_ACTIVE[self.final_name]
		self.hub.DL_ACTIVE_COUNT.release()
		for future in self.futures:
			future.set_result(None)


async def _download(hub, artifact):
	"""

	This function is used to download tarballs and other artifacts. Because files can be large,
	it uses a streaming download so the entire file doesn't need to be cached in memory. Hashes
	of the downloaded file are computed as the file is in transit.

	Upon success, the function will update the Artifact's hashes dict to contain hashes and
	filesize of the downloaded artifact.

	"""

	logging.info(f"Fetching {artifact.url}...")

	temp_path = artifact.temp_path
	os.makedirs(os.path.dirname(temp_path), exist_ok=True)
	final_path = artifact.final_path

	fd = open(temp_path, "wb")
	hashes = {}

	for h in HASHES:
		hashes[h] = getattr(hashlib, h)()
	filesize = 0

	def on_chunk(chunk):
		# See https://stackoverflow.com/questions/5218895/python-nested-functions-variable-scoping
		nonlocal filesize
		fd.write(chunk)
		for hash in HASHES:
			hashes[hash].update(chunk)
		filesize += len(chunk)
		sys.stdout.write(".")
		sys.stdout.flush()

	await hub.pkgtools.http.http_fetch_stream(artifact.url, on_chunk)
	sys.stdout.write("x")
	sys.stdout.flush()
	fd.close()
	os.link(temp_path, final_path)
	os.unlink(temp_path)
	final_data = {"size": filesize, "hashes": {}, "path": final_path}

	for h in HASHES:
		final_data["hashes"][h] = hashes[h].hexdigest()

	# TODO: this is likely a good place for GPG verification. Implement.

	return final_data


def extract_path(hub, artifact):
	return os.path.join(hub.TEMP_PATH, artifact.subsystem + "_extract", artifact.final_name)


def extract(hub, artifact):
	# TODO: maybe refactor these next 2 lines
	if not artifact.exists:
		artifact.fetch()
	ep = extract_path(hub, artifact)
	os.makedirs(ep, exist_ok=True)
	cmd = "tar -C %s -xf %s" % (ep, artifact.final_path)
	s, o = getstatusoutput(cmd)
	if s != 0:
		raise hub.pkgtools.ebuild.BreezyError("Command failure: %s" % cmd)


def cleanup(hub, artifact):
	# TODO: check for path stuff like ../.. in final_name to avoid security issues.
	getstatusoutput("rm -rf " + os.path.join(hub.TEMP_PATH, artifact.subsystem + "_extract", artifact.final_name))


async def calc_hashes(hub, fn):
	hashes = {}
	for h in HASHES:
		hashes[h] = getattr(hashlib, h)()
	filesize = 0
	with open(fn, "rb") as myf:
		while True:
			data = myf.read(1280000)
			if not data:
				break
			for h in hashes:
				hashes[h].update(data)
			filesize += len(data)
	final_data = {"size": filesize, "hashes": {}, "path": fn}
	for h in HASHES:
		final_data["hashes"][h] = hashes[h].hexdigest()
	return final_data


async def check_hashes(hub, old_hashes, new_hashes):
	"""
	This method compares two sets of hashes passed to it and throws an exception if they don't match.
	"""
	failures = []
	for h in HASHES:
		old = old_hashes[h]
		new = new_hashes[h]
		if old != new:
			failures.append((h, old, new))
	return failures


# vim: ts=4 sw=4 noet
