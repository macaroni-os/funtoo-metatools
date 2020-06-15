#!/usr/bin/env python3

import asyncio
import aiohttp
from tornado import httpclient
from tornado.httpclient import HTTPRequest
import sys
import os
import hashlib
import logging
import socket
from subprocess import getstatusoutput
import hashlib

__virtualname__ = "FETCHER"


def __virtual__(hub):
	return True

def __init__(hub):
	hub.ARTIFACT_TEMP_PATH = os.path.join(hub.OPT.pkgtools.temp_path, 'distfiles')
	hub.CHECK_DISK_HASHES = False

HASHES = [ 'sha512', 'blake2b' ]


# TODO: implement different download strategies with different levels of security. Maybe as a
#       declarative pipeline.

def _final_path(hub, artifact):
	return os.path.join(hub.ARTIFACT_TEMP_PATH, artifact.final_name)

def _temp_path(hub, artifact):
	return os.path.join(hub.ARTIFACT_TEMP_PATH, "%s.__download__" % artifact.final_name)

async def artifact_ensure_fetched(hub, artifact):
	if os.path.exists(_final_path(hub, artifact)):
		return
	else:
		try:
			final_data = await download(hub, artifact)
			# TODO: implement:
			hub.pkgtools.FETCH_CACHE.record_download_success(final_data)
		except FetchError as e:
			hub.pkgtools.FETCH_CACHE.record_download_failure(TODO)

async def download(hub, artifact):
	"""

	This function is used to download tarballs and other artifacts. Because files can be large,
	it uses a streaming download so the entire file doesn't need to be cached in memory. Hashes
	of the downloaded file are computed as the file is in transit.

	Upon success, the function will update the Artifact's hashes dict to contain hashes and
	filesize of the downloaded artifact.

	"""

	logging.info(f"Fetching {artifact.url}...")
	os.makedirs(hub.ARTIFACT_TEMP_PATH, exist_ok=True)
	temp_path = _temp_path(hub, artifact)
	final_path = _final_path(hub, artifact)

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

	await http_fetch_stream(hub, artifact.url, on_chunk)
	sys.stdout.write("x")
	sys.stdout.flush()
	fd.close()
	os.link(temp_path, final_path)
	os.unlink(temp_path)
	final_data = {
		"size": filesize,
		"hashes": {},
		"path" : final_path
	}

	for h in HASHES:
		final_data['hashes'][h] = hashes[h].hexdigest()

	# TODO: this is likely a good place for GPG verification. Implement.

	return final_data

def extract(hub, artifact):
	# TODO: maybe refactor thest next 2 lines
	if not artifact.exists:
		artifact.fetch()
	extract_path = os.path.join(hub.ARTIFACT_TEMP_PATH, "extract", artifact.final_name)
	os.makedirs(extract_path, exist_ok=True)
	cmd = "tar -C %s -xf %s" % (extract_path, artifact.final_path)
	s, o = getstatusoutput(cmd)
	if s != 0:
		raise hub.pkgtools.ebuild.BreezyError("Command failure: %s" % cmd)


def cleanup(hub, artifact):
	# TODO: check for path stuff like ../.. in final_name to avoid security issues.
	getstatusoutput("rm -rf " + os.path.join(hub.ARTIFACT_TEMP_PATH, "extract", artifact.final_name))


async def calc_hashes(hub, fn):
	hashes = {}
	for h in HASHES:
		hashes[h] = getattr(hashlib, h)()
	filesize = 0
	with open(fn, 'rb') as myf:
		while True:
			data = myf.read(1280000)
			if not data:
				break
			for h in hashes:
				hashes[h].update(data)
			filesize += len(data)
	final_data = {
		"size": filesize,
		"hashes": {},
		"path" : fn
	}
	for h in HASHES:
		final_data['hashes'][h] = hashes[h].hexdigest()
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
