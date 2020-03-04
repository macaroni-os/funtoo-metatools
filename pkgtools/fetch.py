#!/usr/bin/env python3

import os
import sys
import hashlib
from tornado import httpclient
from tornado.httpclient import HTTPRequest
import tornado.template
import logging
logging.basicConfig(level=logging.DEBUG)

class BreezyError(Exception):
	pass

def __init__(hub):
	print("Initialized!")

def get_url_from_redirect(url):
	logging.info("Querying %s to get redirect URL..." % url)
	http_client = httpclient.HTTPClient()
	try:
		req = HTTPRequest(url=url, follow_redirects=False)
		http_client.fetch(req)
	except httpclient.HTTPError as e:
		if e.response.code == 302:
			return e.response.headers["location"]
	except Exception as e:
		raise BreezyError("Couldn't get URL %s -- %s" % (url, repr(e)))
	raise BreezyError("URL %s doesn't appear to redirect" % url)

class ArtifactFetcher:

	def __init__(self, artifact):
		self.artifact = artifact
		self.filename = artifact.split("/")[-1]
		self._fd = None
		self._sha512 = hashlib.sha512()
		self._blake2b = hashlib.blake2b()
		self._size = 0
		if os.path.exists(self.final_name):
			self.exists = True
		else:
			self.exists = False

	@property
	def temp_name(self):
		return "distfiles/%s.__download__" % self.filename

	@property
	def final_name(self):
		return "distfiles/%s" % self.filename

	@property
	def sha512(self):
		return self._sha512.hexdigest()

	@property
	def blake2b(self):
		return self._blake2b.hexdigest()

	@property
	def size(self):
		return self._size

	def update_digests(self):
		logging.info("Calculating digests for %s..." % self.final_name)
		with open(self.final_name, 'rb') as myf:
			while True:
				data = myf.read(1280000)
				if not data:
					break
				self._sha512.update(data)
				self._blake2b.update(data)
				self._size += len(data)

	def on_chunk(self, chunk):
		if self._fd is None:
			self._fd = open(self.temp_name, "wb")
		self._fd.write(chunk)
		self._sha512.update(chunk)
		self._blake2b.update(chunk)
		self._size += len(chunk)
		sys.stdout.write(".")
		sys.stdout.flush()

	def fetch(self):
		if self.exists:
			self.update_digests()
			logging.warning("File %s exists (size %s); not fetching again." % ( self.filename, self.size ))
			return
		logging.info("Fetching %s..." % self.artifact)
		http_client = httpclient.HTTPClient()
		try:
			req = HTTPRequest(url=self.artifact, streaming_callback=self.on_chunk)
			http_client.fetch(req)
		except httpclient.HTTPError as e:
			raise BreezyError("Fetch Error")
		http_client.close()
		if self._fd is not None:
			self._fd.close()
			os.link(self.temp_name, self.final_name)
			os.unlink(self.temp_name)

def fetch_all(artifact_list):
	os.makedirs("distfiles", exist_ok=True)
	fetchers = []
	for artifact in artifact_list:
		af = ArtifactFetcher(artifact)
		try:
			af.fetch()
		except BreezyError as e:
			print("Fetch error for %s" % artifact)
			sys.exit(1)
		fetchers.append(af)
	return fetchers

def generate_metadata_for(fetchers):
	with open("Manifest", "w") as mf:
		for fetcher in fetchers:
			mf.write("DIST %s %s BLAKE2B %s SHA512 %s\n" % ( fetcher.filename, fetcher.size, fetcher.blake2b, fetcher.sha512 ))
	logging.info("Manifest generated.")

def get_artifacts(artifact_list):
	fetchers = fetch_all(artifact_list)
	generate_metadata_for(fetchers)

def hello():
	print("hello world!")

# vim: ts=4 sw=4 noet
