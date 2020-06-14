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

RESOLVERS = {}
HASHES = [ 'sha512', 'blake2b' ]

def get_resolver(hub):
	"""
	Resolvers need to be local to the current ioloop. Since we use a ThreadPool, it may not be in the caller's
	ioloop if we just instantiate a global resolver.

	This should return a resolver local to the caller.
	"""
	global RESOLVERS
	loop = asyncio.get_event_loop()
	if id(loop) not in RESOLVERS:
		RESOLVERS[id(loop)] = aiohttp.AsyncResolver(nameservers=['1.1.1.1', '1.0.0.1'], timeout=5, tries=3)
	return RESOLVERS[id(loop)]


http_data_timeout = 60
chunk_size = 262144


async def http_fetch_stream(hub, url, on_chunk):
	"""
	This is a streaming HTTP fetcher that will call on_chunk(bytes) for each chunk.
	On_chunk is called with literal bytes from the response body so no decoding is
	performed. A FetchError will be raised if any error occurs. If this function
	returns successfully then the download completed successfully.
	"""
	connector = aiohttp.TCPConnector(family=socket.AF_INET, resolver=get_resolver(hub), ssl=False)
	headers = {'User-Agent': 'funtoo-metatools (support@funtoo.org)'}
	try:
		async with aiohttp.ClientSession(connector=connector) as http_session:
			async with http_session.get(url, headers=headers, timeout=None) as response:
				if response.status != 200:
					raise hub.pkgtools.fetch.FetchError(url, f"HTTP Error {response.status}")
				while True:
					try:
						chunk = await response.content.read(chunk_size)
						if not chunk:
							break
						else:
							sys.stdout.write(".")
							sys.stdout.flush()
							on_chunk(chunk)
					except aiohttp.EofStream:
						pass
	except AssertionError:
		raise hub.pkgtools.fetch.FetchError(url, f"Unable to fetch: internal aiohttp assertion failed")
	return None


async def http_fetch(hub, url):
	"""
	This is a non-streaming HTTP fetcher that will properly convert the request to a Python
	string and return the entire content as a string.
	"""
	global RESOLVER
	connector = aiohttp.TCPConnector(family=socket.AF_INET, resolver=get_resolver(hub), ssl=False)
	headers = {'User-Agent': 'funtoo-metatools (support@funtoo.org)'}
	async with aiohttp.ClientSession(connector=connector) as http_session:
		async with http_session.get(url, headers=headers, timeout=None) as response:
			if response.status != 200:
				raise hub.pkgtools.fetch.FetchError(url, f"HTTP Error {response.status}")
			return await response.text()
	return None

# TODO: implement different download strategies with different levels of security. Maybe as a
#       declarative pipeline.

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
	temp_path = os.path.join(hub.ARTIFACT_TEMP_PATH, "%s.__download__" % artifact.final_name)
	final_path = os.path.join(hub.ARTIFACT_TEMP_PATH, artifact.final_name)
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

	# TODO: implement:
	hub.pkgtools.FETCH_CACHE.record_download_metadata(final_data)
	return final_data

async def get_page(hub, url):
	"""
	This function performs a simple HTTP fetch of a resource. The response is cached in memory,
	and a decoded Python string is returned with the result. FetchError is thrown for an error
	of any kind.
	"""
	logging.info(f"Fetching page {url}...")
	try:
		return await http_fetch(hub, url)
	except Exception as e:
		raise hub.pkgtools.fetch.FetchError(url, f"Couldn't get_page due to exception {repr(e)}")


async def get_url_from_redirect(hub, url):
	"""
	This function will take a URL that redirects and grab what it redirects to. This is useful
	for /download URLs that redirect to a tarball 'foo-1.3.2.tar.xz' that you want to download,
	when you want to grab the '1.3.2' without downloading the file (yet).
	"""
	logging.info(f"Getting redirect URL from {url}...")
	http_client = httpclient.AsyncHTTPClient()
	try:
		req = HTTPRequest(url=url, follow_redirects=False)
		await http_client.fetch(req)
	except httpclient.HTTPError as e:
		if e.response.code == 302:
			return e.response.headers["location"]
	except Exception as e:
		raise hub.pkgtools.fetch.FetchError(url, f"Couldn't get_url_from_redirect due to exception {repr(e)}")


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

async def check_hashes(self, old_hashes, new_hashes):
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

"""
	async def update_hashes(self):
		"""
		This method calculates new hashes for the Artifact that currently exists on disk, and also updates the fetch cache with these new hash values.

		This method assumes that the Artifact exists on disk.
		"""
		logging.info(f"Updating hashes for {self.url}")
		self.hashes = await self.calc_hashes()
		await self.hub.pkgtools.FETCH_CACHE.fetch_cache_write("artifact", self, metadata_only=True)

		async with self.in_setup:
			if self.hashes is not None:
				# someone else completed setup while I was waiting.
				return
			if not self.exists:
				await self.download()
			try:
				db_result = await self.hub.pkgtools.FETCH_CACHE.fetch_cache_read("artifact", self)
				try:
					self.hashes = db_result['metadata']['hashes']
					if self.hub.CHECK_DISK_HASHES:
						logging.debug(f"Checking disk hashes for {self.final_name}")
						await self.check_hashes(self.hashes, await self.calc_hashes())
				except (KeyError, TypeError) as foo:
					await self.update_hashes()
			except self.hub.pkgtools.fetch.CacheMiss:
				await self.update_hashes()

	async def download(self):
		async with self.in_download:
			if self.exists or self.attempted_download:
				# someone else completed the download while I was waiting
				return
			await self.hub.pkgtools.FETCHER.download(self)
			self.attempted_download = True
"""



# vim: ts=4 sw=4 noet
