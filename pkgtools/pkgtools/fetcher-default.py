#!/usr/bin/env python3
import socket
from subprocess import getstatusoutput

from tornado import httpclient
from tornado.httpclient import HTTPRequest
import sys
import os
import hashlib
import logging
from tornado.simple_httpclient import SimpleAsyncHTTPClient

__virtualname__ = "FETCHER"

def __virtual__(hub):
	return True

async def get_page(hub, url):
	http_client = httpclient.AsyncHTTPClient()
	try:
		req = HTTPRequest(url=url, follow_redirects=False, headers={'User-Agent': 'funtoo-metatools (support@funtoo.org)'})
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


async def update_digests(hub, artifact):
	_sha512 = hashlib.sha512()
	_blake2b = hashlib.blake2b()
	_size = 0
	logging.info("Calculating digests for %s..." % artifact.final_name)
	with open(_get_final_path(hub, artifact), 'rb') as myf:
		while True:
			data = myf.read(1280000)
			if not data:
				break
			_sha512.update(data)
			_blake2b.update(data)
			_size += len(data)
	return {
		"sha512": _sha512.hexdigest(),
		"blake2b": _blake2b.hexdigest(),
		"size": _size
	}


def extract(hub, artifact):
	if not artifact.exists:
		artifact.fetch()
	ep = get_extract_path(hub, artifact)
	os.makedirs(ep, exist_ok=True)
	cmd = "tar -C %s -xf %s" % (ep, _get_final_path(hub, artifact))
	s, o = getstatusoutput(cmd)
	if s != 0:
		raise hub.pkgtools.ebuild.BreezyError("Command failure: %s" % cmd)


def cleanup(hub, artifact):
	getstatusoutput("rm -rf " + artifact.extract_path)


def _get_temp_path(hub, artifact):
	return os.path.join(hub.ARTIFACT_TEMP_PATH, "%s.__download__" % artifact.final_name)


def _get_final_path(hub, artifact):
	return os.path.join(hub.ARTIFACT_TEMP_PATH, artifact.final_name)


def get_extract_path(hub, artifact):
	return os.path.join(hub.ARTIFACT_TEMP_PATH, "extract", artifact.final_name)


def exists(hub, artifact):
	final_path = _get_final_path(hub, artifact)
	return os.path.exists(final_path)


async def download(hub, artifact):

	os.makedirs(hub.ARTIFACT_TEMP_PATH, exist_ok=True)
	temp_path = _get_temp_path(hub, artifact)
	final_path = _get_final_path(hub, artifact)
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

	logging.info("Fetching %s..." % artifact.url)
	http_client = SimpleAsyncHTTPClient(max_body_size=1024 * 1024 * 1024 * 1024 * 50)
	try:
		req = HTTPRequest(url=artifact.url, streaming_callback=on_chunk, request_timeout=999999)
		foo = await http_client.fetch(req)
	except httpclient.HTTPError as e:
		raise hub.pkgtools.fetch.FetchError("Fetch Error")
	except socket.gaierror as ge:
		raise hub.pkgtools.fetch.FetchError("Name resolution error")
	http_client.close()
	fd.close()
	os.link(temp_path, final_path)
	os.unlink(temp_path)

	return {
		"sha512": sha512.hexdigest(),
		"blake2b": blake2b.hexdigest(),
		"size": filesize
	}



# vim: ts=4 sw=4 noet
