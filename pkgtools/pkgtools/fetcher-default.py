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


__virtualname__ = "FETCHER"


def __virtual__(hub):
	return True


RESOLVERS = {}
# map Artifact to the Task that is running.
ACTIVE_DOWNLOAD_TASKS = {}

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
	temp_path = artifact.temp_path
	final_path = artifact.final_path
	fd = open(temp_path, "wb")
	sha512 = hashlib.sha512()
	blake2b = hashlib.blake2b()
	filesize = 0

	def on_chunk(chunk):
		# See https://stackoverflow.com/questions/5218895/python-nested-functions-variable-scoping
		nonlocal filesize
		fd.write(chunk)
		sha512.update(chunk)
		blake2b.update(chunk)
		filesize += len(chunk)
		sys.stdout.write(".")
		sys.stdout.flush()

	await http_fetch_stream(hub, artifact.url, on_chunk)
	sys.stdout.write("x")
	sys.stdout.flush()
	fd.close()
	os.link(temp_path, final_path)
	os.unlink(temp_path)
	artifact.hashes = {
		"sha512": sha512.hexdigest(),
		"blake2b": blake2b.hexdigest(),
		"size": filesize
	}


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
		raise hub.pkgtools.fetch.FetchError(url, "Doesn't appear to redirect")


def extract(hub, artifact):
	if not artifact.exists:
		artifact.fetch()
	os.makedirs(artifact.extract_path, exist_ok=True)
	cmd = "tar -C %s -xf %s" % (artifact.extract_path, artifact.final_path)
	s, o = getstatusoutput(cmd)
	if s != 0:
		raise hub.pkgtools.ebuild.BreezyError("Command failure: %s" % cmd)


def cleanup(hub, artifact):
	getstatusoutput("rm -rf " + artifact.extract_path)




# vim: ts=4 sw=4 noet
