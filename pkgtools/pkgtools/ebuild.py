#!/usr/bin/env python3

import os
import asyncio

import jinja2
import logging
from collections import defaultdict

logging.basicConfig(level=logging.DEBUG)

HUB = None

def __init__(hub):
	global HUB
	HUB = hub
	hub.MANIFEST_LINES = defaultdict(set)


class BreezyError(Exception):

	def __init__(self, msg):
		self.msg = msg


class DigestError(Exception):

	def __init__(self, msg):
		self.msg = msg


class Fetchable:

	def __init__(self, url=None, **kwargs):
		global HUB
		self.hub = HUB
		self.url = url


class Artifact(Fetchable):

	def __init__(self, url=None, final_name=None, **kwargs):
		super().__init__(url=url, **kwargs)
		self._final_name = final_name
		self.final_data = None

	@property
	def final_name(self):
		if self._final_name is None:
			return self.url.split("/")[-1]
		else:
			return self._final_name

	@property
	def extract_path(self):
		return self.hub.pkgtools.download.extract_path(self)

	async def fetch(self):
		await self.hub.pkgtools.download.ensure_fetched(self)

	def is_fetched(self):
		return self.hub.pkgtools.download.is_fetched(self)

	async def ensure_fetched(self):
		await self.fetch()

	def record_final_data(self, final_data):
		self.final_data = final_data

	@property
	def hashes(self):
		return self.final_data['hashes']

	@property
	def size(self):
		return self.final_data['size']

	def hash(self, h):
		return self.final_data['hashes'][h]

	@property
	def src_uri(self):
		if self._final_name is None:
			return self.url
		else:
			return self.url + " -> " + self._final_name

	def extract(self):
		return self.hub.pkgtools.download.extract(self)

	def cleanup(self):
		return self.hub.pkgtools.download.cleanup(self)

	def exists(self):
		return self.hub.pkgtools.is_fetched(self)

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
				logging.info(f"Setting {kwarg} to {kwargs[kwarg]}")
				setattr(self, kwarg, kwargs[kwarg])
		self.template = template
		self.template_text = template_text
		if template_path is None:
			if 'path' in self.template_args:
				# If we have a pkginfo['path'], this gives us our current processing path.
				# Use this as a base for our default template path.
				self._template_path = os.path.join(self.template_args['path'] + '/templates')
			else:
				# This is a no-op, but wit this set to None, we will use the template_path()
				# property to get the value, which will be relative to the repo root and based
				# on the setting of name and category.
				self._template_path = None
		else:
			# A manual template path was specified.
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

		# TODO: if not fetched, we need to wait on something that will return when the file is actually
		#       fetched.

		futures = []

		for artifact in self.artifact_dicts:
			if type(artifact) != Artifact:
				artifact = Artifact(**artifact)

			async def lil_coroutine(a):
				await a.ensure_fetched()
				print(f"Artifact {a.url} fetched.")
				return a

			futures.append(lil_coroutine(artifact))

		# At this point, all artifacts are fetched:
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
				self.hub.MANIFEST_LINES[key].add("DIST %s %s BLAKE2B %s SHA512 %s\n" % (artifact.final_name, artifact.size, artifact.hash('blake2b'), artifact.hash('sha512')))

	def create_ebuild(self):
		if not self.template_text:
			template_file = os.path.join(self.template_path, self.template)
			try:
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
