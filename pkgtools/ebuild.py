#!/usr/bin/env python3

import os
import sys
import hashlib
import asyncio
from tornado import httpclient
from tornado.httpclient import HTTPRequest
import tornado.template
import logging
logging.basicConfig(level=logging.INFO)

QUE = []
ARTIFACT_TEMP_PATH="/var/tmp/distfiles"

def push(hub, **kwargs):
	"""
		Add an ebuild to the queue for generation.
	"""
	setup = None
	if 'setup' in kwargs:
		setup = kwargs['setup']
		del kwargs['setup']
	builder = BreezyBuild(**kwargs)
	if setup:
		setup(hub, builder)
	QUE.append([lambda: builder.generate(tree)])

async def go(hub):
	for future in asyncio.as_completed(QUE):
		builder = await(future)
		hub.CPM_LOGGER.record(tree.name, builder.catpkg, is_fixup=True)

def __init__(hub):
	pass

class BreezyError(Exception):
	pass

class Artifact:

	def __init__(self, url=None, final_name=None):
		self.url = url
		self.filename = url.split("/")[-1]
		self._fd = None
		self._sha512 = hashlib.sha512()
		self._blake2b = hashlib.blake2b()
		self._size = 0
		self._final_name = final_name

	@property
	def exists(self):
		return os.path.exists(self.final_name)

	@property
	def temp_name(self):
		return os.path.join(ARTIFACT_TEMP_PATH, "%s.__download__" % self.filename)

	@property
	def final_name(self):
		if self._final_name:
			return os.path.join(ARTIFACT_TEMP_PATH, self._final_name)
		else:
			return os.path.join(ARTIFACT_TEMP_PATH, "%s" % self.filename)

	@property
	def sha512(self):
		return self._sha512.hexdigest()

	@property
	def blake2b(self):
		return self._blake2b.hexdigest()

	@property
	def size(self):
		return self._size

	def extract(self):
		pass

	def cleanup(self):
		pass

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
		self._fd.write(chunk)
		self._sha512.update(chunk)
		self._blake2b.update(chunk)
		self._size += len(chunk)
		sys.stdout.write(".")
		sys.stdout.flush()

	async def fetch(self):
		if self.exists:
			self.update_digests()
			logging.warning("File %s exists (size %s); not fetching again." % ( self.filename, self.size ))
			return
		logging.info("Fetching %s..." % self.url)
		if self._fd is None:
			self._fd = open(self.temp_name, "wb")
		http_client = httpclient.AsyncHTTPClient()
		try:
			req = HTTPRequest(url=self.url, streaming_callback=self.on_chunk)
			await http_client.fetch(req)
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
	tree = None
	template_vars = None

	def __init__(self,
		artifacts: list = None,
		template: str = None,
		**kwargs
	):
		self.artifacts = []
		self._pkgdir = None
		self.template_args = kwargs
		for kwarg in [ 'cat', 'name', 'version', 'revision' ]
			if kwarg in kwargs:
				setattr(self, kwarg, kwargs[kwarg])
		if self.template is None:
			self.template = self.name + ".tmpl"
		else:
			self.template = template

		self.artifacts = []

		# This following code allows us to use the template variables in the
		# artifact URLs and have them expand. We instantiate the Artifact objects
		# ourselves so we can do this:

		if artifacts is not None:
			for artifact in artifacts:
				for key, val in artifact.items():
					artifact[key] = val.format(self.template_args)
				self.artifacts.append(Artifact(**kwargs))

	async def fetch_all(self):
		for artifact in self.artifacts:
			await af.fetch()

	@property
	def pkgdir(self):
		if self._pkgdir is None:
			self._pkgdir = os.path.join(self.tree.root, self.cat, self.name)
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
	def catpkg(self):
		return self.cat + "/" + self.name

	def __getitem__(self, key):
		return self.template_args[key]

	@property
	def catpkg_version_rev(self):
		if self.revision == 0:
			return self.cat + "/" + self.name + '-' + self.version
		else:
			return self.cat + "/" + self.name + '-' + self.version + '_r%s' % self.revision

	@property
	def template_path(self):
		tpath = os.path.join(self.tree.root, self.cat, self.name, "templates")
		os.makedirs(tpath, exist_ok=True)
		return tpath

	def generate_metadata_for(self):
		with open(self.pkgdir + "/Manifest", "w") as mf:
			for artifact in self.artifacts:
				mf.write("DIST %s %s BLAKE2B %s SHA512 %s\n" % ( artifact.filename, artifact.size, artifact.blake2b, artifact.sha512 ))
		logging.info("Manifest generated.")

	async def get_artifacts(self):
		await self.fetch_all()
		self.generate_metadata()

	def create_ebuild(self):
		# TODO: fix path on next line to point somewhere logical.
		loader = tornado.template.Loader(self.template_path)
		template = loader.load(self.template)
		# generate template variables
		with open(self.ebuild_path, "wb") as myf:
			myf.write(template.generate(**self.template_vars))
		logging.info("Ebuild %s generated." % self.ebuild_path)

	async def generate(self, tree):
		try:
			if self.cat is None:
				raise BreezyError("Please set 'cat' to the category name of this ebuild.")
			if self.name is None:
				raise BreezyError("Please set 'name' to the package name of this ebuild.")
			self.create_ebuild()
			await self.get_artifacts()
		except BreezyError as e:
			print(e)
			sys.exit(1)
		return self

# vim: ts=4 sw=4 noet
