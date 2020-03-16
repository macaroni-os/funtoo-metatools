#!/usr/bin/env python3

import os
import sys
import hashlib
import asyncio
from subprocess import getstatusoutput

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


class Artifact:

	def __init__(self, url=None, final_name=None):

		self.url = url
		self._filename = url.split("/")[-1]
		self._fd = None
		self._sha512 = hashlib.sha512()
		self._blake2b = hashlib.blake2b()
		self._size = 0
		self._final_name = final_name

	@property
	def filename(self):
		if self._final_name is None:
			return self._filename
		else:
			return self._final_name

	@property
	def src_uri(self):
		if self._final_name is None:
			return self.url
		else:
			return self.url + " -> " + self._final_name

	@property
	def exists(self):
		return os.path.exists(self.final_name)

	@property
	def temp_name(self):
		return os.path.join(ARTIFACT_TEMP_PATH, "%s.__download__" % self._filename)

	@property
	def final_name(self):
		if self._final_name:
			return os.path.join(ARTIFACT_TEMP_PATH, self._final_name)
		else:
			return os.path.join(ARTIFACT_TEMP_PATH, "%s" % self._filename)

	@property
	def sha512(self):
		return self._sha512.hexdigest()

	@property
	def blake2b(self):
		return self._blake2b.hexdigest()

	@property
	def size(self):
		return self._size

	@property
	def extract_path(self):
		return os.path.join(ARTIFACT_TEMP_PATH, "extract", self._final_name)

	def extract(self):
		ep = self.extract_path
		os.makedirs(ep, exist_ok=True)
		cmd = "tar -C %s -xf %s" % (ep, self.final_name)
		s, o = getstatusoutput(cmd)
		if s != 0:
			raise BreezyError("Command failure: %s" % cmd)

	def cleanup(self):
		getstatusoutput("rm -rf " + self.extract_path)

	def update_digests(self):
		self._sha512 = hashlib.sha512()
		self._blake2b = hashlib.blake2b()
		self._size = 0
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
		self._fd.write(chunk)
		self._sha512.update(chunk)
		self._blake2b.update(chunk)
		self._size += len(chunk)
		sys.stdout.write(".")
		sys.stdout.flush()

	async def fetch(self):
		if self.exists:
			self.update_digests()
			logging.warning("File %s exists (size %s); not fetching again." % (self._filename, self.size))
			return
		logging.info("Fetching %s..." % self.url)
		if self._fd is None:
			os.makedirs(ARTIFACT_TEMP_PATH, exist_ok=True)
			self._fd = open(self.temp_name, "wb")
		http_client = httpclient.AsyncHTTPClient()
		try:
			req = HTTPRequest(url=self.url, streaming_callback=self.on_chunk, request_timeout=999999)
			foo = await http_client.fetch(req)
		except httpclient.HTTPError as e:
			raise BreezyError("Fetch Error")
		http_client.close()
		if self._fd is not None:
			self._fd.close()
			os.link(self.temp_name, self.final_name)
			os.unlink(self.temp_name)


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
				mf.write("DIST %s %s BLAKE2B %s SHA512 %s\n" % ( artifact.filename, artifact.size, artifact.blake2b, artifact.sha512 ))
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
