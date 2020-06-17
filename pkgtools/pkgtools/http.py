#!/usr/bin/env python3

import aiohttp
from tornado import httpclient
from tornado.httpclient import HTTPRequest
import sys
import logging
import socket


http_data_timeout = 60
chunk_size = 262144


async def http_fetch_stream(hub, url, on_chunk):
	"""
	This is a streaming HTTP fetcher that will call on_chunk(bytes) for each chunk.
	On_chunk is called with literal bytes from the response body so no decoding is
	performed. A FetchError will be raised if any error occurs. If this function
	returns successfully then the download completed successfully.
	"""
	connector = aiohttp.TCPConnector(family=socket.AF_INET, resolver=hub.pkgtools.dns.get_resolver(), ssl=False)
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
	connector = aiohttp.TCPConnector(family=socket.AF_INET, resolver=hub.pkgtools.dns.get_resolver(), ssl=False)
	headers = {'User-Agent': 'funtoo-metatools (support@funtoo.org)'}
	async with aiohttp.ClientSession(connector=connector) as http_session:
		async with http_session.get(url, headers=headers, timeout=None) as response:
			if response.status != 200:
				raise hub.pkgtools.fetch.FetchError(url, f"HTTP Error {response.status}")
			return await response.text()
	return None

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

# vim: ts=4 sw=4 noet
