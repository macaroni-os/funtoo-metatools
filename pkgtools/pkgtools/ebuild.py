#!/usr/bin/env python3

import os
import asyncio

import jinja2
import logging
from collections import defaultdict
import hashlib

logging.basicConfig(level=logging.DEBUG)


HUB = None


def __init__(hub):
	global HUB
	HUB = hub
	hub.ARTIFACT_TEMP_PATH = os.path.join(hub.OPT.pkgtools.temp_path, 'distfiles')
	hub.MANIFEST_LINES = defaultdict(set)
	hub.CHECK_DISK_HASHES = False


class BreezyError(Exception):

	def __init__(self, msg):
		self.msg = msg


class DigestError(Exception):

	def __init__(self, msg):
		self.msg = msg


class Fetchable:

	def __init__(self, **kwargs):
		global HUB
		self.hub = HUB
		self.metadata = kwargs

	@property
	def url(self):
		return self.metadata["url"]

	def as_metadata(self):
		return {
			"url": self.metadata['url']
		}


class Artifact(Fetchable):

	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		self.hashes = None
		self._size = 0
		self.in_setup = asyncio.Semaphore()
		self.in_download = asyncio.Semaphore()
		self.attempted_download = False

	async def setup(self):
		async with self.in_setup:
			if self.hashes is not None:
				# someone else completed setup while I was waiting.
				return
			if not self.exists:
				await self.download()
			try:
				db_result = await self.hub.pkgtools.FETCH_CACHE.fetch_cache_read("artifact", self)
				try:
					self.hashes = db_result['metadata']['hashes']
					if self.hub.CHECK_DISK_HASHES:
						logging.debug(f"Checking disk hashes for {self.final_name}")
						await self.check_hashes(self.hashes, await self.calc_hashes())
				except (KeyError, TypeError) as foo:
					await self.update_hashes()
			except self.hub.pkgtools.fetch.CacheMiss:
				await self.update_hashes()

	async def download(self):
		async with self.in_download:
			if self.exists or self.attempted_download:
				# someone else completed the download while I was waiting
				return
			await self.hub.pkgtools.FETCHER.download(self)
			self.attempted_download = True

	async def update_hashes(self):
		"""
		This method calculates new hashes for the Artifact that currently exists on disk, and also updates the fetch cache with these new hash values.

		This method assumes that the Artifact exists on disk.
		"""
		logging.info(f"Updating hashes for {self.url}")
		self.hashes = await self.calc_hashes()
		await self.hub.pkgtools.FETCH_CACHE.fetch_cache_write("artifact", self, metadata_only=True)

	async def check_hashes(self, old_hashes, new_hashes):
		"""
		This method compares two sets of hashes passed to it and throws an exception if they don't match.
		"""
		logging.debug("Checking hashes to make sure they match")
		if new_hashes['sha512'] != old_hashes['sha512']:
			raise DigestError(f"Digests of {self.final_name} do not match digest when it was originally downloaded. Current digest: {old_hashes['sha512']} Original digest: {new_hashes['sha512']}")
		if new_hashes['blake2b'] != old_hashes['blake2b']:
			raise DigestError(f"Digests of {self.final_name} do not match digest when it was originally downloaded. Current digest: {old_hashes['blake2b']} Original digest: {new_hashes['blake2b']}")
		if new_hashes['size'] != old_hashes['size']:
			raise DigestError(f"Filesize of {self.final_name} do not match filesize when it was originally downloaded. Current size: {old_hashes['size']} Original size: {new_hashes['size']}")

	async def calc_hashes(self):
		logging.debug("Performing hash calculations on Artifact on disk")
		if not self.exists:
			raise BreezyError(f"Asked to calculate digests for {self.final_name} but file does not exist on disk.")
		_sha512 = hashlib.sha512()
		_blake2b = hashlib.blake2b()
		_size = 0
		logging.info("Calculating digests for %s..." % self.final_path)
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
		if not self.exists:
			await self.setup()

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
		fn = self.final_name
		if fn is None:
			return url
		else:
			return url + " -> " + fn

	def extract(self):
		return self.hub.pkgtools.FETCHER.extract(self)

	def cleanup(self):
		self.hub.pkgtools.FETCHER.cleanup(self)

	@property
	def temp_path(self):
		return os.path.join(self.hub.ARTIFACT_TEMP_PATH, "%s.__download__" % self.final_name)

	@property
	def final_path(self):
		return os.path.join(self.hub.ARTIFACT_TEMP_PATH, self.final_name)

	@property
	def extract_path(self):
		return os.path.join(self.hub.ARTIFACT_TEMP_PATH, "extract", self.final_name)

	@property
	def exists(self):
		return os.path.exists(self.final_path)


class BreezyBuild:

	cat = None
	name = None
	path = None
	template = None
	version = None
	revision = 0
	source_tree = None
	output_tree = None
	template_args = None

	def __init__(self,
		artifacts: list = None,
		template: str = None,
		template_text: str = None,
		template_path: str = None,
		**kwargs
	):
		global HUB
		self.hub = HUB
		self.source_tree = self.hub.CONTEXT
		self.output_tree = self.hub.OUTPUT_CONTEXT
		self._pkgdir = None
		self.template_args = kwargs
		for kwarg in ['cat', 'name', 'version', 'revision', 'path']:
			if kwarg in kwargs:
				setattr(self, kwarg, kwargs[kwarg])
		self.template = template
		self.template_text = template_text
		self._template_path = template_path
		if self.template_text is None and self.template is None:
			self.template = self.name + ".tmpl"

		if artifacts is None:
			self.artifact_dicts = []
		else:
			self.artifact_dicts = artifacts
		self.artifacts = []

	async def setup(self):
		"""
		This method ensures that Artifacts are instantiated (if dictionaries were passed in instead of live
		Artifact objects) -- and that their setup() method is called, which may actually do fetching, if the
		local archive is not available for generating digests.

		Note that this now parallelizes all downloads.
		"""

		futures = []

		async def lil_coroutine(a):
			await a.setup()
			return a

		for artifact in self.artifact_dicts:
			if type(artifact) != Artifact:
				artifact = Artifact(**artifact)
			futures.append(lil_coroutine(artifact))

		self.artifacts = await asyncio.gather(*futures)
		self.template_args["artifacts"] = self.artifacts

	def push(self):
		"""
		Push means "do it soon". Anything pushed will be on a task queue which will get fired off at the end
		of the autogen run. Tasks will run in parallel so this is a great way to improve performance if generating
		a lot of catpkgs. Push all the catpkgs you want to generate and they will all get fired off at once.
		"""
		task = asyncio.create_task(self.generate())
		self.hub.pkgtools.autogen.QUE.append(task)

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
		if self._template_path:
			return self._template_path
		tpath = os.path.join(self.source_tree.root, self.cat, self.name, "templates")
		return tpath

	# TODO: we should really generate one Manifest per catpkg -- this does one per ebuild:

	def record_manifest_lines(self):
		"""
		This method records literal Manifest output lines which will get written out later, because we may
		not have *all* the Manifest lines we need to write out until autogen is fully complete.
		"""
		if not len(self.artifacts):
			return
		key = self.output_pkgdir + "/Manifest"
		for artifact in self.artifacts:
				self.hub.MANIFEST_LINES[key].add("DIST %s %s BLAKE2B %s SHA512 %s\n" % (artifact.final_name, artifact.hashes["size"], artifact.hashes["blake2b"], artifact.hashes["sha512"]))

	def create_ebuild(self):
		if not self.template_text:
			try:
				template_file = os.path.join(self.template_path, self.template)
				with open(template_file, "r") as tempf:
					template = jinja2.Template(tempf.read())
			except FileNotFoundError as e:
				logging.error(f"Could not find template: {template_file}")
				raise BreezyError(f"Template file not found: {template_file}")
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

		if self.cat is None:
			raise BreezyError("Please set 'cat' to the category name of this ebuild.")
		if self.name is None:
			raise BreezyError("Please set 'name' to the package name of this ebuild.")
		await self.setup()
		self.create_ebuild()
		self.record_manifest_lines()
		return self

# vim: ts=4 sw=4 noet
