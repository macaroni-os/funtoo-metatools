#!/usr/bin/env python3

import os
import sys
import hashlib
import asyncio
from subprocess import getstatusoutput

from tornado import httpclient
from tornado import simple_httpclient
from tornado.httpclient import HTTPRequest
import jinja2
import logging

logging.basicConfig(level=logging.INFO)

QUE = []

def __init__(hub):
	hub.CACHE_PATH = '/var/tmp/funtoo-metatools'
	hub.ARTIFACT_TEMP_PATH = '/var/tmp/distfiles'

def set_cache_path(hub, path):
	hub.CACHE_PATH = path

def set_temp_path(hub, path):
	hub.ARTIFACT_TEMP_PATH = path

async def go(hub):
	for future in asyncio.as_completed(QUE):
		builder = await future

class BreezyError(Exception):
	pass

class Artifact:

	def __init__(self, hub, **kwargs):
		self.hub = hub
		self._fd = None
		self.hashes = {}
		self._size = 0
		self.metadata = kwargs

	async def setup(self):
		self.hashes = await self.update_digests()

	@property
	def url(self):
		return self.metadata["url"]

	def as_metadata(self):
		return {
			"url": self.metadata['url'],
			"final_name": self.final_name,
			"hashes": self.hashes
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
		return os.path.join(self.hub.ARTIFACT_TEMP_PATH, "%s.__download__" % self.final_name)

	@property
	def final_path(self):
		return os.path.join(self.hub.ARTIFACT_TEMP_PATH, self.final_name)

	@property
	def extract_path(self):
		return os.path.join(self.hub.ARTIFACT_TEMP_PATH, "extract", self.final_name)

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

	def on_chunk(self, chunk):
		self._fd.write(chunk)
		self._sha512.update(chunk)
		self._blake2b.update(chunk)
		self._size += len(chunk)
		sys.stdout.write(".")
		sys.stdout.flush()

	async def fetch(self):

		if self.exists:
			self.hashes = await self.update_digests()
			logging.warning("File %s exists (size %s); not fetching again." % (self.final_name, self.hashes["size"]))
			return

		os.makedirs(self.hub.ARTIFACT_TEMP_PATH, exist_ok=True)
		self._fd = open(self.temp_path, "wb")
		self._sha512 = hashlib.sha512()
		self._blake2b = hashlib.blake2b()
		self._size = 0

		logging.info("Fetching %s..." % self.url)

		http_client = simple_httpclient.SimpleAsyncHTTPClient(max_body_size=1024 * 1024 * 1024 * 1024 * 50)

		try:
			req = HTTPRequest(url=self.url, streaming_callback=self.on_chunk, request_timeout=999999)
			foo = await http_client.fetch(req)
		except httpclient.HTTPError as e:
			raise BreezyError("Fetch Error")
		http_client.close()

		self.hashes = {
			"sha512": self._sha512.hexdigest(),
			"blake2b": self._blake2b.hexdigest(),
			"size": self._size
		}

		self._fd.close()
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

		self.artifact_dicts = artifacts
		self.artifacts = []

	async def setup(self):
		"""
		This method ensures that Artifacts are instantiated (if dictionaries were passed in instead of live
		Artifact objects) -- and that their setup() method is called, which may actually do fetching, if the
		local archive is not available for generating digests.
		"""
		for artifact in self.artifact_dicts:
			if type(artifact) != Artifact:
				artifact = Artifact(self.hub, **artifact)
			await artifact.setup()
			self.artifacts.append(artifact)
		self.template_args["artifacts"] = self.artifact_dicts

	def push(self):
		"""
		Push means "do it soon". Anything pushed will be on a task queue which will get fired off at the end
		of the autogen run. Tasks will run in parallel so this is a great way to improve performance if generating
		a lot of catpkgs. Push all the catpkgs you want to generate and they will all get fired off at once.
		"""
		task = asyncio.create_task(self.generate())
		QUE.append(task)

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

	def generate_manifest(self):
		if not len(self.artifacts):
			return
		with open(self.output_pkgdir + "/Manifest", "w") as mf:
			for artifact in self.artifacts:
				mf.write("DIST %s %s BLAKE2B %s SHA512 %s\n" % ( artifact.final_name, artifact.hashes["size"], artifact.hashes["blake2b"], artifact.hashes["sha512"] ))
		logging.info("Manifest generated.")

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
		"""
		This is an async method that does the actual creation of the ebuilds from templates. It also handles
		initialization of Artifacts (indirectly) and could result in some HTTP fetching. If you call
		``myebuild.push()``, this is the task that gets pushed onto the task queue to run in parallel.
		If you don't call push() on your BreezyBuild, then you could choose to call the generate() method
		directly instead. In that case it will run right away.
		"""
		try:
			if self.cat is None:
				raise BreezyError("Please set 'cat' to the category name of this ebuild.")
			if self.name is None:
				raise BreezyError("Please set 'name' to the package name of this ebuild.")
			await self.setup()
			self.create_ebuild()
			self.generate_manifest()
		except BreezyError as e:
			print(e)
			sys.exit(1)
		return self

# vim: ts=4 sw=4 noet
