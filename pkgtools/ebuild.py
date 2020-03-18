#!/usr/bin/env python3

import os
import sys
import hashlib
import asyncio
from subprocess import getstatusoutput

from async_property import async_cached_property, AwaitLoader
from tornado import httpclient
from tornado.httpclient import HTTPRequest
import jinja2
import logging

logging.basicConfig(level=logging.INFO)

QUE = []
ARTIFACT_TEMP_PATH = "/var/tmp/distfiles"


def set_temp_path(hub, path):
	global ARTIFACT_TEMP_PATH
	ARTIFACT_TEMP_PATH = path

async def go(hub):
	for future in asyncio.as_completed(QUE):
		builder = await future

class BreezyError(Exception):
	pass

class Artifact(AwaitLoader):

	"""
	The AwaitLoader class from the async_property package is an interesting thing and worth talking about.

	It can be really tricky to use @property decorators with async. For example, let's say a class has a property
	called 'size' but it needs to call an async function. This simply CANNOT BE DONE with regular Python.

	AwaitLoader works around this. If you sub-class AwaitLoader, then instead of creating an object this old way::

	  foo = MyObject()

	You make it a subclass of AwaitLoader and create it this new way:

	  foo = await MyObject()

	As part of this new technique, any async load() method of your class is called upon creation which can be used
	to make async calls and initialize things for your async properties.

	*Your* methods will need to access your async properties by doing (await self.size)[-1] but code outside your
	class will not need to await on your async properties.

	This is pretty neat so also complicated so worth talking about.
	"""

	def __init__(self, url=None, final_name=None, metadata=None):
		self._fd = None

		self._hashes = None
		self._size = 0
		if metadata:
			if "final_name" in metadata and metadata["final_name"] is None:
				del metadata["final_name"]
			self.metadata = metadata
			self.state = "reconstituted"
		else:
			self.metadata = {}
			self.state = "live"
		if url is not None:
			self.metadata["url"] = url
		if final_name is not None:
			self.metadata["final_name"] = final_name

	#async def check_digests(self):
	#	orig_hashes = self.metadata["hashes"]
	#	await self.fetch()
	#	if orig_hashes != self.metadata["hashes"]:
	#		raise BreezyError("Digest mismatch: %s vs %s" % ( orig_hashes, self.metadata["hashes"]))

	async def load(self):
		if self._hashes is None:
			self._hashes = await self.update_digests()

	@async_cached_property
	async def hashes(self):
		return self._hashes

	@property
	def url(self):
		if self.metadata:
			return self.metadata["url"]

	def as_metadata(self):
		return {
			"$type": "Artifact",
			"url": self.metadata['url'],
			"final_name": self.final_name,
			"hashes": {
				"sha512": self.hashes["sha512"],
				"blake2b": self.hashes["blake2b"],
			},
			"size": self.hashes['size']
		}

	@property
	def final_name(self):
		if "final_name" not in self.metadata:
			return self.metadata["url"].split("/")[-1]
		else:
			return self.metadata["final_name"]

	@property
	def src_uri(self):
		url = self.metadata["url"]
		fn = self.metadata["final_name"]
		if fn is None:
			return url
		else:
			return url + " -> " + fn

	@property
	def exists(self):
		return os.path.exists(self.final_path)

	@property
	def temp_path(self):
		return os.path.join(ARTIFACT_TEMP_PATH, "%s.__download__" % self.final_name)

	@property
	def final_path(self):
		print(self.metadata)
		return os.path.join(ARTIFACT_TEMP_PATH, self.final_name)

	@property
	def extract_path(self):
		return os.path.join(ARTIFACT_TEMP_PATH, "extract", self.final_name)

	def extract(self):
		if not self.exists:
			self.fetch()
		ep = self.extract_path
		os.makedirs(ep, exist_ok=True)
		cmd = "tar -C %s -xf %s" % (ep, self.final_path)
		s, o = getstatusoutput(cmd)
		if s != 0:
			raise BreezyError("Command failure: %s" % cmd)

	def cleanup(self):
		getstatusoutput("rm -rf " + self.extract_path)

	async def update_digests(self):
		if not self.exists:
			await self.fetch()
		_sha512 = hashlib.sha512()
		_blake2b = hashlib.blake2b()
		_size = 0
		logging.info("Calculating digests for %s..." % self.final_name)
		with open(self.final_path, 'rb') as myf:
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

	async def fetch(self):

		if self.exists:
			self._hashes = await self.update_digests()
			logging.warning("File %s exists (size %s); not fetching again." % (self.final_name, (await self.hashes)["size"]))
			return

		os.makedirs(ARTIFACT_TEMP_PATH, exist_ok=True)
		_fd = open(self.temp_path, "wb")

		_sha512 = hashlib.sha512()
		_blake2b = hashlib.blake2b()
		_size = 0

		def on_chunk(chunk):
			_fd.write(chunk)
			_sha512.update(chunk)
			_blake2b.update(chunk)
			_size += len(chunk)
			sys.stdout.write(".")
			sys.stdout.flush()

		logging.info("Fetching %s..." % self.url)

		http_client = httpclient.AsyncHTTPClient()
		try:
			req = HTTPRequest(url=self.url, streaming_callback=on_chunk, request_timeout=999999)
			foo = await http_client.fetch(req)
		except httpclient.HTTPError as e:
			raise BreezyError("Fetch Error")
		http_client.close()

		self._hashes = {
			"sha512": _sha512.hexdigest(),
			"blake2b": _blake2b.hexdigest(),
			"size": _size
		}

		_fd.close()
		os.link(self.temp_path, self.final_path)
		os.unlink(self.temp_path)


class BreezyBuild:

	cat = None
	name = None
	template = None
	version = None
	revision = 0
	source_tree = None
	output_tree = None
	template_args = None

	def __init__(self,
		hub,
		artifacts: list = None,
		template: str = None,
		template_text: str = None,
		**kwargs
	):
		self.hub = hub
		self.source_tree = hub.CONTEXT
		self.output_tree = hub.OUTPUT_CONTEXT
		self._pkgdir = None
		self.template_args = kwargs
		for kwarg in ['cat', 'name', 'version', 'revision']:
			if kwarg in kwargs:
				setattr(self, kwarg, kwargs[kwarg])
		self.template = template
		self.template_text = template_text
		if self.template_text is None and self.template is None:
			self.template = self.name + ".tmpl"

		if artifacts is None:
			self.artifacts = []
		else:
			self.artifacts = artifacts
		self.template_args["artifacts"] = self.artifacts

	def push(self):
		task = asyncio.create_task(self.generate())
		QUE.append(task)

	async def fetch_all(self):
		for artifact in self.artifacts:
			await artifact.fetch()

	@property
	def pkgdir(self):
		if self._pkgdir is None:
			self._pkgdir = os.path.join(self.source_tree.root, self.cat, self.name)
			os.makedirs(self._pkgdir, exist_ok=True)
		return self._pkgdir

	@property
	def output_pkgdir(self):
		if self._pkgdir is None:
			self._pkgdir = os.path.join(self.output_tree.root, self.cat, self.name)
			os.makedirs(self._pkgdir, exist_ok=True)
		return self._pkgdir

	@property
	def ebuild_name(self):
		if self.revision == 0:
			return "%s-%s.ebuild" % (self.name, self.version)
		else:
			return "%s-%s-r%s.ebuild" % (self.name, self.version, self.revision)

	@property
	def ebuild_path(self):
		return os.path.join(self.pkgdir, self.ebuild_name)

	@property
	def output_ebuild_path(self):
		return os.path.join(self.output_pkgdir, self.ebuild_name)

	@property
	def catpkg(self):
		return self.cat + "/" + self.name

	def __getitem__(self, key):
		return self.template_args[key]

	@property
	def catpkg_version_rev(self):
		if self.revision == 0:
			return self.cat + "/" + self.name + '-' + self.version
		else:
			return self.cat + "/" + self.name + '-' + self.version + '-r%s' % self.revision

	@property
	def template_path(self):
		tpath = os.path.join(self.source_tree.root, self.cat, self.name, "templates")
		return tpath

	def generate_metadata(self):
		if not len(self.artifacts):
			return
		with open(self.output_pkgdir + "/Manifest", "w") as mf:
			for artifact in self.artifacts:
				mf.write("DIST %s %s BLAKE2B %s SHA512 %s\n" % ( artifact.final_name, artifact.hashes["size"], artifact.hashes["blake2b"], artifact.hashes["sha512"] ))
		logging.info("Manifest generated.")

	async def get_artifacts(self):
		await self.fetch_all()
		self.generate_metadata()

	def create_ebuild(self):
		if not self.template_text:
			with open(os.path.join(self.template_path, self.template), "r") as tempf:
				template = jinja2.Template(tempf.read())
		else:
			template = jinja2.Template(self.template_text)
		with open(self.output_ebuild_path, "wb") as myf:
			myf.write(template.render(**self.template_args).encode("utf-8"))
		logging.info("Created: " + os.path.relpath(self.output_ebuild_path))

	async def generate(self):
		try:
			if self.cat is None:
				raise BreezyError("Please set 'cat' to the category name of this ebuild.")
			if self.name is None:
				raise BreezyError("Please set 'name' to the package name of this ebuild.")
			await self.get_artifacts()
			self.create_ebuild()
		except BreezyError as e:
			print(e)
			sys.exit(1)
		return self

# vim: ts=4 sw=4 noet
