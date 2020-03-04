#!/usr/bin/env python3

import os
import sys
import hashlib
from tornado import httpclient
from tornado.httpclient import HTTPRequest
import tornado.template
import logging
logging.basicConfig(level=logging.DEBUG)

class FetchError(Exception):
	pass

def __init__(hub):
	print("Initialized!")

def get_url_from_redirect(hub, url):
	logging.info("Querying %s to get redirect URL..." % url)
	http_client = httpclient.HTTPClient()
	try:
		req = HTTPRequest(url=url, follow_redirects=False)
		http_client.fetch(req)
	except httpclient.HTTPError as e:
		if e.response.code == 302:
			return e.response.headers["location"]
	except Exception as e:
		raise FetchError("Couldn't get URL %s -- %s" % (url, repr(e)))
	raise FetchError("URL %s doesn't appear to redirect" % url)

# vim: ts=4 sw=4 noet
