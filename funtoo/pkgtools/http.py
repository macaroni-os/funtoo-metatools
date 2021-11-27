#!/usr/bin/env python3

import logging
import aiohttp
from tornado import httpclient
from tornado.httpclient import HTTPRequest

import dyne.org.funtoo.metatools.pkgtools as pkgtools

from metatools.fastpull.spider import FetchRequest, FetchError

"""
This sub implements lower-level HTTP fetching logic, such as actually grabbing the data, sending the
proper headers and authentication, etc.
"""


def set_basic_auth(request: FetchRequest):
	"""
	Keyword arguments to aiohttp ClientSession.get() for authentication to certain URLs based on configuration
	in ~/.autogen (YAML format.)
	"""
	if "authentication" in pkgtools.model.config:
		if request.hostname in pkgtools.model.config["authentication"]:
			auth_info = pkgtools.model.config["authentication"][request.hostname]
			request.set_auth(**auth_info)


async def get_page(url, encoding=None):
	"""
	This function performs a simple HTTP fetch of a resource. The response is cached in memory,
	and a decoded Python string is returned with the result. FetchError is thrown for an error
	of any kind.

	Use ``encoding`` if the HTTP resource does not have proper encoding and you have to set
	a specific encoding. Normally, the encoding will be auto-detected and decoded for you.
	"""
	try:
		request = FetchRequest(url=url)
		set_basic_auth(request)
		# Leverage the spider for this fetch. This bypasses the FPOS, etc:
		result = await pkgtools.model.spider.http_fetch(request, encoding=encoding)
		return result
	except Exception as e:
		if isinstance(e, FetchError):
			raise e
		else:
			msg = f"Couldn't get_page due to exception {e.__class__.__name__}"
			logging.error(url + ": " + msg)
			logging.exception(e)
			raise FetchError(url, msg)


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
		raise FetchError(url, f"Couldn't get_url_from_redirect due to exception {repr(e)}")


async def get_response_headers(url):
	"""
	This function will take a URL and grab its response headers. This is useful for obtaining
	information about a URL without fetching its body.
	"""
	async with aiohttp.ClientSession() as http_session:
		async with http_session.get(url) as response:
			return response.headers


# vim: ts=4 sw=4 noet
