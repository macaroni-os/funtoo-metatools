#!/usr/bin/env python3

from urllib.parse import urlparse
import httpx
import sys
import logging

"""
This sub implements lower-level HTTP fetching logic, such as actually grabbing the data, sending the
proper headers and authentication, etc.
"""


http_data_timeout = 60
chunk_size = 262144


def get_fetch_headers(hub):
	"""
	Headers to send for all HTTP requests.
	"""
	return {"User-Agent": "funtoo-metatools (support@funtoo.org)"}


def get_auth_tuple(hub, url):
	"""
	Keyword arguments to aiohttp ClientSession.get() for authentication to certain URLs based on configuration
	in ~/.autogen (YAML format.)
	"""

	if "authentication" in hub.AUTOGEN_CONFIG:
		parsed_url = urlparse(url)
		if parsed_url.hostname in hub.AUTOGEN_CONFIG["authentication"]:
			auth_info = hub.AUTOGEN_CONFIG["authentication"][parsed_url.hostname]
			logging.warning(f"Using authentication (username {auth_info['username']}) for {url}")
			return auth_info["username"], auth_info["password"]
	return None


async def http_fetch_stream(hub, url, on_chunk):
	"""
	This is a streaming HTTP fetcher that will call on_chunk(bytes) for each chunk.
	On_chunk is called with literal bytes from the response body so no decoding is
	performed. A FetchError will be raised if any error occurs. If this function
	returns successfully then the download completed successfully.
	"""
	logging.info(f"Starting fetch stream of {url}")
	try:
		async with httpx.AsyncClient() as client:
			r = await client.get(url, headers=hub._.get_fetch_headers(), auth=hub._.get_auth_tuple(url))
			if r.status_code != 200:
				raise hub.pkgtools.fetch.FetchError(url, f"HTTP fetch Error {r.status_code}: {r.reason_phrase}")
			for data in r.iter_bytes():
				sys.stdout.write(".")
				sys.stdout.flush()
				on_chunk(data)
	except httpx.HTTPError as e:
		raise hub.pkgtools.fetch.FetchError(url, f"HTTP fetch error - httpx exeption: {repr(e)}")


async def http_fetch(hub, url):
	"""
	This is a non-streaming HTTP fetcher that will properly convert the request to a Python
	string and return the entire content as a string.
	"""
	try:
		async with httpx.AsyncClient() as client:
			r = await client.get(url, headers=hub._.get_fetch_headers(), auth=hub._.get_auth_tuple(url))
			if r.status_code != 200:
				raise hub.pkgtools.fetch.FetchError(url, f"HTTP fetch Error {r.status_code}: {r.reason_phrase}")
			return r.text
	except httpx.HTTPError as e:
		raise hub.pkgtools.fetch.FetchError(url, f"HTTP fetch error - httpx exeption: {repr(e)}")


async def get_page(hub, url):
	"""
	This function performs a simple HTTP fetch of a resource. The response is cached in memory,
	and a decoded Python string is returned with the result. FetchError is thrown for an error
	of any kind.
	"""
	logging.info(f"Fetching page {url}...")
	try:
		return await hub._.http_fetch(url)
	except Exception as e:
		if isinstance(e, hub.pkgtools.fetch.FetchError):
			raise e
		else:
			raise hub.pkgtools.fetch.FetchError(url, f"Couldn't get_page due to exception {repr(e)}")


async def get_url_from_redirect(hub, url):
	"""
	This function will take a URL that redirects and grab what it redirects to. This is useful
	for /download URLs that redirect to a tarball 'foo-1.3.2.tar.xz' that you want to download,
	when you want to grab the '1.3.2' without downloading the file (yet).
	"""
	logging.info(f"Getting redirect URL from {url}...")
	try:
		async with httpx.AsyncClient() as client:
			r = await client.get(url, headers=hub._.get_fetch_headers(), auth=hub._.get_auth_tuple(url), allow_redirects=False)
			if r.status_code != 200:
				raise hub.pkgtools.fetch.FetchError(url, f"HTTP fetch Error {r.status_code}: {r.reason_phrase}")
			return r.headers["location"]
	except KeyError:
		raise hub.pkgtools.fetch.FetchError(url, "Couldn't find redirect information.")
	except httpx.HTTPError as e:
		raise hub.pkgtools.fetch.FetchError(url, f"HTTP fetch error - httpx exeption: {repr(e)}")


# vim: ts=4 sw=4 noet
