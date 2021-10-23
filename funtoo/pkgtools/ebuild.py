#!/usr/bin/env python3

import os
import asyncio
import sys
from asyncio import Task
import jinja2
import logging

import dyne.org.funtoo.metatools.pkgtools as pkgtools

from metatools.hashutils import calc_hashes


class DigestFailure(Exception):
	def __init__(self, artifact=None, kind=None, expected=None, actual=None):
		self.artifact = artifact
		self.kind = kind
		self.expected = expected
		self.actual = actual

	@property
	def message(self):
		out = f"Digest Failure for {self.artifact.final_name}:\n"
		out += f"    Kind: {self.kind}\n"
		out += f"Expected: {self.expected}\n"
		out += f"  Actual: {self.actual}"
		return out


class BreezyError(Exception):
	def __init__(self, msg):
		self.msg = msg


class Fetchable:
	def __init__(self, url=None, **kwargs):
		self.url = url


class Artifact(Fetchable):
	"""
	An artifact is a tarball or other archive that is used by a BreezyBuild, and ultimately referenced in an ebuild. It's also
	possible that an artifact could be fetched by an autogen directly, but not included in an ebuild.

	If an artifact is going to be incorporated into an ebuild, it's passed to the ``artifacts=[]`` keyword argument of the
	``BreezyBuild`` constructor. When it is passed in this way, we perform extra processing. We will store the resultant download
	in the "fastpull" database (an archive of fetched artifacts, indexed by their SHA512 hash), and we will also generate an
	entry in the "distfile integrity database" for each catpkg. This "distfile integrity database" is what links the BreezyBuild's
	catpkg, via the filename, to the entries in the fastpull database. So, for example:

	"sys-apps/foo-1.0.ebuild" references "foo-1.0.tar.gz".
	The distfile integrity database entry for "sys-apps/foo" has an entry for "foo-1.0.tar.gz" which points it to <SHA512>.
	The fastpull database stores an entry for <SHA512>.

	When an artifact is used in a stand-alone fashion

	"""
	def __init__(self, key=None, url=None, final_name=None, final_path=None, expect=None, extra_http_headers=None, **kwargs):
		super().__init__(url=url, **kwargs)
		self.key = key
		self._final_name = final_name
		self._final_data = None
		self._final_path = final_path
		self.breezybuilds = []
		self.expect = expect
		self.extra_http_headers = extra_http_headers

	@property
	def catpkgs(self):
		outstr = ""
		for bzb in self.breezybuilds:
			outstr = f"{outstr} {bzb.catpkg}"
		return outstr.strip()

	@property
	def temp_path(self):
		return os.path.join(pkgtools.model.fetch_download_path, f"{self.final_name}.__download__")

	@property
	def extract_path(self):
		return pkgtools.download.extract_path(self)

	@property
	def final_path(self):
		if self._final_path:
			return self._final_path
		else:
			return os.path.join(pkgtools.model.fetch_download_path, self.final_name)

	@property
	def final_name(self):
		if self._final_name is None:
			return self.url.split("/")[-1]
		else:
			return self._final_name

	async def fetch(self):
		await self.ensure_fetched()

	def is_fetched(self):
		return os.path.exists(self.final_path)

	@property
	def hashes(self):
		return self._final_data["hashes"]

	@property
	def size(self):
		return self._final_data["size"]

	def hash(self, h):
		return self._final_data["hashes"][h]

	@property
	def src_uri(self):
		if self._final_name is None:
			return self.url
		else:
			return self.url + " -> " + self._final_name

	def extract(self):
		return pkgtools.download.extract(self)

	def cleanup(self):
		return pkgtools.download.cleanup(self)

	def exists(self):
		return self.is_fetched()

	def record_final_data(self, final_data):
		self._final_data = final_data

	def validate_digests_against_expected_values(self):
		"""
		The self.expect dictionary can be used to specify digests that we should expect to find in any completed
		or fetched Artifact. This method will throw a DigestFailure() exception when these expectations are not
		met.
		"""
		if self.expect is None:
			return
		for key, val in self.expect.items():
			if key == "size":
				if val != self.size:
					raise DigestFailure(artifact=self, kind="size", expected=val, actual=self.size)
			else:
				actual_hash = self.hash(key)
				if val != actual_hash:
					raise DigestFailure(artifact=self, kind=val, expected=val, actual=actual_hash)

	@property
	def fastpull_path(self):
		sh = self._final_data["hashes"]["sha512"]
		return pkgtools.model.fastpull.get_disk_path(sh)

	async def ensure_completed(self) -> bool:
		"""
		This function ensures that we can 'complete' the artifact -- meaning we have its hash data in the integrity database.
		If this hash data is not found, then we need to fetch the artifact.

		This function returns True if we do indeed have the artifact available to us, and False if there was some error
		which prevents this.

		So basically, this tries to use the distfile integrity database first to get the hash information, but will fall
		back to fetching. When this method is used instead of ensure_fetched(), we can get by without the file even
		existing on disk, as long as we have a distfile integrity entry. So it's preferred if that's all you need.
		"""

		if not len(self.breezybuilds):
			# Since we are using this outside of the context of an autogen, and there is no associated BreezyBuild,
			# using the distfile integrity database doesn't make sense. So just ensure the file is fetched:
			return await self.ensure_fetched()
		integrity_item = pkgtools.model.distfile_integrity.get(self.breezybuilds[0].catpkg, distfile=self.final_name)
		if integrity_item is not None:
			self._final_data = integrity_item["final_data"]
			# Will throw an exception if our new final data doesn't match any expected values.
			self.validate_digests_against_expected_values()
			return True
		else:
			return await self.ensure_fetched()

	async def try_fetch(self):
		"""
		This is like ensure_fetched, but will return an exception if the download fails.
		"""
		await self.ensure_fetched(throw=True)

	async def ensure_fetched(self, throw=False) -> bool:
		"""
		This function ensures that the artifact is 'fetched' -- in other words, it exists locally. This means we can
		calculate its hashes or extract it.

		Returns a boolean with True indicating success and False failure.
		"""

		if self.is_fetched():
			if self._final_data is not None:
				if os.path.exists(self.fastpull_path):
					return True
			else:
				# This condition handles a situation where the distfile integrity database has been wiped. We need to
				# re-populate the data. We already have the file.
				if len(self.breezybuilds):
					self._final_data = pkgtools.model.distfile_integrity.get(self.breezybuilds[0].catpkg, distfile=self.final_name)
					if self._final_data is None:
						self._final_data = calc_hashes(self.final_path)
						# Will throw an exception if our new final data doesn't match any expected values.
						self.validate_digests_against_expected_values()
						pkgtools.model.distfile_integrity.store(self.breezybuilds[0].catpkg, self.final_name, self._final_data)
						await self.inject_into_fastpull()
				else:
					# TODO: There is a minor problem with this part of the code in regard to autogens that do a fetch of an artifact, but
					#       do not pass the artifact to a BreezyBuild. The rust and go autogens currently do this.
					#       .
					#       What happens is that while these artifacts gets stored in fastpull, they don't get "pulled" from fastpull if
					#       you wipe ~/repo_tmp/fetch -- instead they get re-downloaded.
					#       .
					#       This is because the lack of the distfile integrity entry means that the artifact can only be looked for 'by name'.
					#       So the actual filename has to exist in ~/repo_tmp/fetch or it will be re-downloaded.
					#       .
					#       Some thought needs to go into this, how it should be resolved, and what optimal design is in this case.
					#       One idea is to require a catpkg to be specified with every fetch operation, so the distfile integrity catpkg
					#       can be used.
					#       .
					#       Now, these artifacts will never need to be fetched by the end-user, since they are not referenced by ebuilds
					#       directly. However, it is annoying on an intellectual level :)
					#       .
					#       The problem can be considered a more fundamental design problem, related to the lack of clear hierarchy due to
					#       Hatchisms in the design.
					self._final_data = calc_hashes(self.final_path)
					# Will throw an exception if our new final data doesn't match any expected values.
					self.validate_digests_against_expected_values()
					await self.inject_into_fastpull()
				return True
		else:
			active_dl = pkgtools.download.get_download(self.final_name)
			if active_dl is not None:
				# Active download -- wait for it to finish:
				logging.info(f"Waiting for {self.final_name} download to finish")
				success = await active_dl.wait_for_completion(self)
				if success:
					self._final_data = active_dl.final_data
			else:
				# No active download for this file -- start one:
				dl_file = pkgtools.download.Download(self)
				success = await dl_file.download(throw=throw)
			if success:
				# Will throw an exception if our new final data doesn't match any expected values.
				self.validate_digests_against_expected_values()
				await self.inject_into_fastpull()
			return success


def aggregate(meta_list):
	out_list = []
	for item in meta_list:
		if isinstance(item, list):
			out_list += item
		else:
			out_list.append(item)
	return out_list


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

	def __init__(
		self,
		artifacts=None,
		template: str = None,
		template_text: str = None,
		template_path: str = None,
		**kwargs,
	):
		self.source_tree = pkgtools.model.context
		self.output_tree = pkgtools.model.output_context
		self._pkgdir = None
		self.template_args = kwargs
		for kwarg in ["cat", "name", "version", "path"]:
			if kwarg in kwargs:
				setattr(self, kwarg, kwargs[kwarg])

		# Accept a revision= keyword argument, which can be an integer or a dictionary indexed by version.
		# If a dict by version, we only apply the revision if we find self.version in the dict.

		if "revision" in kwargs:
			rev_val = kwargs["revision"]
			if isinstance(rev_val, int):
				self.revision = rev_val
			elif isinstance(rev_val, dict):
				if self.version in rev_val:
					self.revision = rev_val[self.version]
			else:
				raise TypeError(f"Unrecognized type for revision= argument for {kwargs}: {repr(type(rev_val))} {isinstance(rev_val, int)} {isinstance(rev_val, dict)} {rev_val is dict}")

		self.template = template
		self.template_text = template_text
		if template_path is None:
			if "path" in self.template_args:
				# If we have a pkginfo['path'], this gives us our current processing path.
				# Use this as a base for our default template path.
				self._template_path = os.path.join(self.template_args["path"] + "/templates")
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
			self.artifacts = []
		else:
			self.artifacts = artifacts
		self.template_args["artifacts"] = artifacts

	def iter_artifacts(self):
		if type(self.artifacts) == list:
			for artifact in self.artifacts:
				yield artifact
		elif type(self.artifacts) == dict:
			for key, artifact in self.artifacts.items():
				yield artifact
		else:
			raise TypeError("Invalid type for artifacts passed to BreezyBuild -- should be list or dict.")

	async def setup(self):
		"""
		This method performs some special setup steps. We tend to treat Artifacts as stand-alone objects -- and they
		can be -- such as if you instantiate an Artifact in `generate()` and fetch it because you need to extract it
		and look inside it.

		But when associated with a BreezyBuild, as is commonly the case, this means that there is a relationship between
		the Artifact and the BreezyBuild.

		In this scenario, we know that the Artifact is associated with a catpkg, and will be written out to a Manifest.
		So this means we want to create some associations. We want to record that the Artifact is associated with the
		catpkg of this BreezyBuild. We use this for writing new entries to the Distfile Integrity database for
		to-be-fetched artifacts.

		The `ensure_completed()` call will ensure the Artifact has hashes from the Distfile Integrity Database or is
		fetched and hashes calculated.

		TODO: if the file exists on disk, but there is no Distfile Integrity entry, we need to make sure that hashes
		      are not just calculated -- the distfile integrity entry should be created as well.

		"""

		fetch_tasks_dict = {}

		for artifact in self.iter_artifacts():
			if type(artifact) != Artifact:
				artifact = Artifact(**artifact)

			# This records that the artifact is used by this catpkg, because an Artifact can be shared among multiple
			# catpkgs. This is used for the integrity database writes:

			if self not in artifact.breezybuilds:
				artifact.breezybuilds.append(self)

			async def lil_coroutine(a):
				status = await a.ensure_completed()
				return a, status

			fetch_task = asyncio.Task(lil_coroutine(artifact))
			fetch_task.add_done_callback(pkgtools.autogen._handle_task_result)
			fetch_tasks_dict[artifact] = fetch_task

		# Wait for any artifacts that are still fetching:
		results, exceptions = await pkgtools.autogen.gather_pending_tasks(fetch_tasks_dict.values())
		completion_list = aggregate(results)
		for artifact, status in completion_list:
			if status is False:
				logging.error(f"Artifact for url {artifact.url} referenced in {artifact.catpkgs} could not be fetched.")
				sys.exit(1)

	def push(self):
		#
		# https://stackoverflow.com/questions/1408171/thread-local-storage-in-python

		async def wrapper(self):
			await self.generate()
			return self

		# This will cause the BreezyBuild to start autogeneration immediately, appending the task to the thread-
		# local context so we can grab the result later. The return value will be the BreezyBuild object itself,
		# thanks to the wrapper.
		bzb_task = Task(wrapper(self))
		bzb_task.bzb = self
		bzb_task.add_done_callback(pkgtools.autogen._handle_task_result)
		hub.THREAD_CTX.running_breezybuilds.append(bzb_task)

	@property
	def pkgdir(self):
		if self._pkgdir is None:
			self._pkgdir = os.path.join(self.source_tree.root, self.cat, self.name)
			os.makedirs(self._pkgdir, exist_ok=True)
		return self._pkgdir

	@property
	def output_pkgdir(self):
		if self._pkgdir is None:
			logging.info(f"OUTPUT PKGDIR: {self.output_tree.root} {self.cat} {self.name}")
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
			return self.cat + "/" + self.name + "-" + self.version
		else:
			return self.cat + "/" + self.name + "-" + self.version + "-r%s" % self.revision

	@property
	def template_path(self):
		if self._template_path:
			return self._template_path
		tpath = os.path.join(self.source_tree.root, self.cat, self.name, "templates")
		return tpath

	async def record_manifest_lines(self):
		"""
		This method records literal Manifest output lines which will get written out later, because we may
		not have *all* the Manifest lines we need to write out until autogen is fully complete.
		"""
		if not len(self.artifacts):
			return

		key = self.output_pkgdir + "/Manifest"

		for artifact in self.iter_artifacts():
			success = await artifact.ensure_completed()
			if not success:
				raise BreezyError(f"Something prevented us from storing Manifest data for {key}.")
			pkgtools.model.manifest_lines[key].add(
				"DIST %s %s BLAKE2B %s SHA512 %s\n"
				% (artifact.final_name, artifact.size, artifact.hash("blake2b"), artifact.hash("sha512"))
			)

	def create_ebuild(self):
		if not self.template_text:
			template_file = os.path.join(self.template_path, self.template)
			try:
				with open(template_file, "r") as tempf:
					try:
						template = jinja2.Template(tempf.read())
					except jinja2.exceptions.TemplateError as te:
						raise BreezyError(f"Template error in {template_file}: {repr(te)}")
					except Exception as te:
						raise BreezyError(f"Unknown error processing {template_file}: {repr(te)}")
			except FileNotFoundError as e:
				logging.error(f"Could not find template: {template_file}")
				raise BreezyError(f"Template file not found: {template_file}")
		else:
			template = jinja2.Template(self.template_text)

		with open(self.output_ebuild_path, "wb") as myf:
			try:
				myf.write(template.render(**self.template_args).encode("utf-8"))
			except Exception as te:
				raise BreezyError(f"Error rendering template: {repr(te)}")
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
		try:
			self.create_ebuild()
		except Exception as e:
			raise BreezyError(f"Error creating ebuild {self.catpkg}: {str(e)}")
		await self.record_manifest_lines()
		return self


# vim: ts=4 sw=4 noet
