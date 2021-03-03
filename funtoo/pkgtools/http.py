#!/usr/bin/env python3

from asyncio import Semaphore
from collections import defaultdict
from urllib.parse import urlparse
import aiohttp
from tornado import httpclient
from tornado.httpclient import HTTPRequest
import sys
import logging
import socket

"""
This sub implements lower-level HTTP fetching logic, such as actually grabbing the data, sending the
proper headers and authentication, etc.
"""

import dyne.org.funtoo.metatools.pkgtools as pkgtools


async def get_resolver():
	"""
	This returns a DNS resolver local to the ioloop of the caller.
	"""
	resolver = getattr(hub.THREAD_CTX, "http_resolver", None)
	if resolver is None:
		resolver = hub.THREAD_CTX.http_resolver = aiohttp.AsyncResolver(
			nameservers=["1.1.1.1", "1.0.0.1"], timeout=5, tries=3
		)
	return resolver


async def acquire_host_semaphore(hostname):
	semaphores = getattr(hub.THREAD_CTX, "http_semaphores", None)
	if semaphores is None:
		semaphores = hub.THREAD_CTX.http_semaphores = defaultdict(lambda: Semaphore(value=8))
	return semaphores[hostname]


http_data_timeout = 60
chunk_size = 262144


def get_fetch_headers():
	"""
	Headers to send for all HTTP requests.
	"""
	return {"User-Agent": "funtoo-metatools (support@funtoo.org)"}


def get_hostname(url):
	parsed_url = urlparse(url)
	return parsed_url.hostname


def get_auth_kwargs(hostname, url):
	"""
	Keyword arguments to aiohttp ClientSession.get() for authentication to certain URLs based on configuration
	in ~/.autogen (YAML format.)
	"""
	kwargs = {}
	if "authentication" in pkgtools.model.AUTOGEN_CONFIG:
		if hostname in pkgtools.model.AUTOGEN_CONFIG["authentication"]:
			auth_info = pkgtools.model.AUTOGEN_CONFIG["authentication"][hostname]
			logging.warning(f"Using authentication (username {auth_info['username']}) for {url}")
			kwargs = {"auth": aiohttp.BasicAuth(auth_info["username"], auth_info["password"])}
	return kwargs


async def http_fetch_stream(url, on_chunk, retry=True):
	"""
	This is a streaming HTTP fetcher that will call on_chunk(bytes) for each chunk.
	On_chunk is called with literal bytes from the response body so no decoding is
	performed. A FetchError will be raised if any error occurs. If this function
	returns successfully then the download completed successfully.
	"""
	hostname = get_hostname(url)
	semi = await acquire_host_semaphore(hostname)
	rec_bytes = 0
	attempts = 0
	if retry:
		max_attempts = 20
	else:
		max_attempts = 1
	completed = False
	async with semi:
		while not completed and attempts < max_attempts:
			connector = aiohttp.TCPConnector(family=socket.AF_INET, resolver=await get_resolver(), ssl=False)
			try:
				async with aiohttp.ClientSession(connector=connector) as http_session:
					headers = get_fetch_headers()
					if rec_bytes:
						headers["Range"] = f"bytes={rec_bytes}-"
						logging.warning(f"Resuming at {rec_bytes}")
					async with http_session.get(url, headers=headers, timeout=None, **get_auth_kwargs(hostname, url)) as response:
						if response.status not in [200, 206]:
							reason = (await response.text()).strip()
							raise pkgtools.fetch.FetchError(url, f"HTTP fetch_stream Error {response.status}: {reason}")
						while not completed:
							chunk = await response.content.read(chunk_size)
							rec_bytes += len(chunk)
							if not chunk:
								completed = True
								break
							else:
								sys.stdout.write(".")
								sys.stdout.flush()
								on_chunk(chunk)
			except Exception as e:
				logging.error(f"Encountered {e} during fetch")
				if attempts + 1 < max_attempts:
					attempts += 1
					continue
				else:
					raise pkgtools.fetch.FetchError(url, f"{e.__class__.__name__}: {str(e)}")
		return None


async def http_fetch(url):
	"""
	This is a non-streaming HTTP fetcher that will properly convert the request to a Python
	string and return the entire content as a string.
	"""
	hostname = get_hostname(url)
	semi = await acquire_host_semaphore(hostname)
	async with semi:
		connector = aiohttp.TCPConnector(family=socket.AF_INET, resolver=await get_resolver(), ssl=False)
		async with aiohttp.ClientSession(connector=connector) as http_session:
			async with http_session.get(
				url, headers=get_fetch_headers(), timeout=None, **get_auth_kwargs(hostname, url)
			) as response:
				if response.status != 200:
					reason = (await response.text()).strip()
					raise pkgtools.fetch.FetchError(url, f"HTTP fetch Error {response.status}: {reason}")
				return await response.text()
		return None


async def get_page(url):
	"""
	This function performs a simple HTTP fetch of a resource. The response is cached in memory,
	and a decoded Python string is returned with the result. FetchError is thrown for an error
	of any kind.
	"""
	logging.info(f"Fetching page {url}...")
	try:
		return await http_fetch(url)
	except Exception as e:
		if isinstance(e, pkgtools.fetch.FetchError):
			raise e
		else:
			msg = f"Couldn't get_page due to exception {repr(e)}"
			logging.error(url + ": " + msg)
			raise pkgtools.fetch.FetchError(url, msg)


async def get_url_from_redirect(url):
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
		raise pkgtools.fetch.FetchError(url, f"Couldn't get_url_from_redirect due to exception {repr(e)}")


# vim: ts=4 sw=4 noet
