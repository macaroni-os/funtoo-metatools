#!/usr/bin/env python3

from tornado import httpclient
from tornado.httpclient import HTTPRequest


async def get_page(hub, url):
	http_client = httpclient.AsyncHTTPClient()
	try:
		req = HTTPRequest(url=url, follow_redirects=False)
		response = await http_client.fetch(req)
		return response.body.decode()
	except Exception as e:
		raise hub.pkgtools.fetch.FetchError("Couldn't get URL %s -- %s" % (url, repr(e)))


async def get_url_from_redirect(hub, url):
	http_client = httpclient.AsyncHTTPClient()
	try:
		req = HTTPRequest(url=url, follow_redirects=False)
		await http_client.fetch(req)
	except httpclient.HTTPError as e:
		if e.response.code == 302:
			return e.response.headers["location"]
	except Exception as e:
		raise hub.pkgtools.fetch.FetchError("Couldn't get URL %s -- %s" % (url, repr(e)))
	raise hub.pkgtools.fetch.FetchError("URL %s doesn't appear to redirect" % url)

# vim: ts=4 sw=4 noet