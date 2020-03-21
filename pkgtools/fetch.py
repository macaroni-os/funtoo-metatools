#!/usr/bin/env python3

import logging

from tornado import httpclient
from tornado.httpclient import HTTPRequest

class FetchError(Exception):
	pass

async def get_url_from_redirect(hub, url):
	logging.info("Querying %s to get redirect URL..." % url)
	http_client = httpclient.AsyncHTTPClient()
	try:
		req = HTTPRequest(url=url, follow_redirects=False)
		await http_client.fetch(req)
	except httpclient.HTTPError as e:
		if e.response.code == 302:
			return e.response.headers["location"]
	except Exception as e:
		raise FetchError("Couldn't get URL %s -- %s" % (url, repr(e)))
	raise FetchError("URL %s doesn't appear to redirect" % url)

async def get_page(hub, url):
	http_client = httpclient.AsyncHTTPClient(max_buffer_size=1024*1024*50)
	try:
		req = HTTPRequest(url=url, follow_redirects=False, headers={'User-Agent' : 'funtoo-metatools (support@funtoo.org)'})
		response = await http_client.fetch(req)
		return response.body.decode()
	except Exception as e:
		raise FetchError("Couldn't get URL %s -- %s" % (url, repr(e)))


# vim: ts=4 sw=4 noet
