#!/usr/bin/env python3

import logging

from tornado import httpclient
from tornado.httpclient import HTTPRequest

logging.basicConfig(level=logging.DEBUG)

class FetchError(Exception):
	pass

def __init__(hub):
	print("Initialized!")

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

# vim: ts=4 sw=4 noet
