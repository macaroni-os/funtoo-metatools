#!/usr/bin/env python3

import os
import asyncio
import jinja2
import logging

logging.basicConfig(level=logging.INFO)

QUE = []

def __init__(hub):
	hub.ARTIFACT_TEMP_PATH = os.path.join(hub.OPT.pkgtools.temp_path, 'distfiles')

async def parallelize_pending_tasks(hub):
	for future in asyncio.as_completed(QUE):
		builder = await future


class BreezyError(Exception):

	def __init__(self, msg):
		self.msg = msg


class Fetchable:

	def __init__(self, hub, **kwargs):
		self.hub = hub
		self.metadata = kwargs

	@property
	def url(self):
		return self.metadata["url"]

	def as_metadata(self):
		return {
			"url": self.metadata['url']
		}


class Artifact(Fetchable):

	def __init__(self, hub, **kwargs):
		super().__init__(hub, **kwargs)
		self.hashes = {}
		self._size = 0

	async def setup(self):
		if self.exists:
			self.hashes = await self.hub.pkgtools.FETCHER.update_digests(self)
		else:
			self.hashes = await self.hub.pkgtools.FETCHER.download(self)

	async def fetch(self):
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

	@property
	def exists(self):
		return self.hub.pkgtools.FETCHER.exists(self)

	def extract(self):
		return self.hub.pkgtools.FETCHER.extract(self)

	@property
	def extract_path(self):
		return self.hub.pkgtools.FETCHER.get_extract_path(self)

	def cleanup(self):
		self.hub.pkgtools.FETCHER.cleanup(self)


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
				artifact = Artifact(self.hub, **artifact)
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

	# TODO: we should really generate one Manifest per catpkg -- this does one per ebuild:

	def generate_manifest(self):
		if not len(self.artifacts):
			return
		with open(self.output_pkgdir + "/Manifest", "w") as mf:
			for artifact in self.artifacts:
				mf.write("DIST %s %s BLAKE2B %s SHA512 %s\n" % (artifact.final_name, artifact.hashes["size"], artifact.hashes["blake2b"], artifact.hashes["sha512"] ))
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

		if self.cat is None:
			raise BreezyError("Please set 'cat' to the category name of this ebuild.")
		if self.name is None:
			raise BreezyError("Please set 'name' to the package name of this ebuild.")
		await self.setup()
		self.create_ebuild()
		self.generate_manifest()
		return self

# vim: ts=4 sw=4 noet
