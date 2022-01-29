#!/usr/bin/env python3

import json
import os
import sys
import threading
import traceback
from collections import defaultdict
from concurrent.futures import as_completed
from concurrent.futures.thread import ThreadPoolExecutor
from multiprocessing import cpu_count

import dyne.org.funtoo.metatools.merge as merge
from subpop.util import AttrDict

from funtoo.merge.metadata import AUXDB_LINES, get_catpkg_relations_from_depstring, get_filedata, extract_ebuild_metadata, strip_rev, get_atom, load_json, CACHE_DATA_VERSION
from metatools.files.release import Kit, SourceCollection, SourceRepository, KitKind
from metatools.hashutils import get_md5
from metatools.tree import run_shell, GitTree, GitTreeError

"""
This file exists to define objects related to the processing of kits and releases. It uses settings defined in 
``merge.model``, and in particular will use ``merge.model.release_yaml`` to access the object hierarchy created
from a release's YAML data.
"""


class EclassHashCollection:
	"""
	This is just a simple class for storing the path where we grabbed all the eclasses from plus
	the mapping from eclass name (ie. 'eutils') to the hexdigest of the generated hash.

	You can add two collections together, with the last collection's eclasses taking precedence
	over the first. The concept is to be able to this::

	  all_eclasses = core_kit_eclasses + llvm_eclasses + this_kits_eclasses
	"""

	def __init__(self, path=None, paths=None, hashes=None):
		if paths:
			self.paths = paths
		else:
			self.paths = []
		if hashes:
			self.hashes = hashes
		else:
			self.hashes = {}
		if path and (hashes or paths):
			raise AttributeError("Don't use path= with hashes= or paths= -- pick one.")
		if path:
			self.add_path(path)

	def add_path(self, path, scan=True):
		"""
		Adds a path to self.paths which will take precedence over any existing paths.
		"""
		self.paths = [path] + self.paths
		if scan:
			self.scan_path(os.path.join(path, "eclass"))

	def __add__(self, other):
		paths = self.paths + other.paths
		hashes = self.hashes.copy()
		hashes.update(other.hashes)
		return self.__class__(paths=paths, hashes=hashes)

	def scan_path(self, eclass_scan_path):
		if os.path.isdir(eclass_scan_path):
			for eclass in os.listdir(eclass_scan_path):
				if not eclass.endswith(".eclass"):
					continue
				eclass_path = os.path.join(eclass_scan_path, eclass)
				eclass_name = eclass[:-7]
				self.hashes[eclass_name] = get_md5(eclass_path)


class KitGenerator:

	"""
	This class represents the work associated with generating a Kit. A ``Kit`` (defined in metatools/files/release.py)
	is passed to the constructor of this object to define settings, and stored within this object as ``self.kit``.

	The KitGenerator takes care of creating or connecting to an existing Git tree that is used to house the results of
	the kit generation, and this Git tree object is stored at ``self.out_tree``.

	The ``self.generate()`` method (and supporting methods) take care of regenerating the Kit. Upon completion,
	``self.kit_sha1`` is set to the SHA1 of the commit containing these updates.
	"""

	kit_sha1 = None
	out_tree = None
	active_repos = set()

	kit_cache = None
	metadata_errors = None
	processing_warnings = None
	kit_cache_retrieved_atoms = None
	kit_cache_misses = None
	kit_cache_writes = None

	eclasses = None
	merged_eclasses = None
	is_master = None

	def __init__(self, kit: Kit, is_master=False):
		self.kit = kit
		self.is_master = is_master

		git_class = merge.model.git_class

		if merge.model.nest_kits:
			root = os.path.join(merge.model.dest_trees, "meta-repo/kits", kit.name)
		else:
			root = os.path.join(merge.model.dest_trees, kit.name)
		self.out_tree = git_class(kit.name, branch=kit.branch, root=root, model=merge.model)
		self.out_tree.initialize()
		self.eclasses = EclassHashCollection(path=self.out_tree.root)

	def get_kit_cache_path(self):
		os.makedirs(os.path.join(merge.model.temp_path, "kit_cache"), exist_ok=True)
		return os.path.join(merge.model.temp_path, "kit_cache", f"{self.out_tree.name}-{self.out_tree.branch}")

	def update_atom(self, atom, td_out):
		"""
		Update our in-memory record for a specific ebuild atom on disk that has changed. This will
		be written out by flush_kit(). Right now we just record it in memory.

		"""
		self.kit_cache[atom] = td_out
		self.kit_cache_writes.add(atom)

	async def run(self, steps):
		for step in steps:
			if step is not None:
				merge.model.log.info(f"Running step {step.__class__.__name__} for {self.out_tree.root}")
				try:
					await step.run(self)
				except GitTreeError as gte:
					merge.model.log.error(f"Exiting due to {gte}.")
					sys.exit(1)
				except Exception as ex:
					exc_string = (''.join(traceback.format_exception(etype=type(ex), value=ex, tb=ex.__traceback__)))
					merge.model.log.error(f"Exiting due to:\n{exc_string}")
					sys.exit(1)

	def fetch_kit(self):
		"""
		Grab cached metadata for an entire kit from serialized JSON, with a single query.
		"""
		outpath = self.get_kit_cache_path()
		kit_cache_data = None
		if os.path.exists(outpath):
			try:
				kit_cache_data = load_json(outpath)
			except json.decoder.JSONDecodeError:
				merge.model.log.warning(f"Kit cache at {outpath} may be empty and will be overwritten.")
		if kit_cache_data is not None:
			self.kit_cache = kit_cache_data["atoms"]
			self.metadata_errors = {}
		else:
			# Missing kit cache or different CACHE_DATA_VERSION will cause it to be thrown away so we can regenerate it.
			self.kit_cache = {}
			self.metadata_errors = {}
		self.processing_warnings = []
		self.kit_cache_retrieved_atoms = set()
		self.kit_cache_misses = set()
		self.kit_cache_writes = set()

	def flush_kit(self, save=True, prune=True):
		"""
		Write out our in-memory copy of our entire kit metadata, which may contain updates.

		If `save` is False, simply empty without saving.

		If no changes have been made to the kit cache, no changes need to be saved.

		If there were changes, and if `prune` is True, any unaccessed (unread) item will be removed from the cache.
		This is intended to clean out stale entries during tree regeneration.
		"""
		if prune:
			all_keys = set(self.kit_cache.keys())
			remove_keys = all_keys - (self.kit_cache_retrieved_atoms | self.kit_cache_writes)
			extra_atoms = self.kit_cache_retrieved_atoms - all_keys
			for key in remove_keys:
				del self.kit_cache[key]
			if len(extra_atoms):
				merge.model.log.error("THERE ARE EXTRA ATOMS THAT WERE RETRIEVED BUT NOT IN CACHE!")
				merge.model.log.error(f"{extra_atoms}")
		if save:
			outpath = self.get_kit_cache_path()
			outdata = {
				"cache_data_version": CACHE_DATA_VERSION,
				"atoms": self.kit_cache,
				"metadata_errors": self.metadata_errors,
			}
			merge.model.log.warning(f"Flushed {self.kit.name}. {len(self.kit_cache)} atoms. Removed {len(remove_keys)} keys. {len(self.metadata_errors)} errors.")
			with open(outpath, "w") as f:
				f.write(json.dumps(outdata))

			# Add summary to hub of error count for this kit, and also write out the error logs:

			error_outpath = os.path.join(
				merge.model.temp_path, f"metadata-errors-{self.out_tree.name}-{self.out_tree.branch}.log"
			)
			if len(self.metadata_errors):
				merge.model.metadata_error_stats.append(
					{"name": self.out_tree.name, "branch": self.out_tree.branch, "count": len(self.metadata_errors)}
				)
				with open(error_outpath, "w") as f:
					f.write(json.dumps(self.metadata_errors))
			else:
				if os.path.exists(error_outpath):
					os.unlink(error_outpath)

			error_outpath = os.path.join(merge.model.temp_path, f"warnings-{self.out_tree.name}-{self.out_tree.branch}.log")
			if len(self.processing_warnings):
				merge.model.processing_warning_stats.append(
					{"name": self.out_tree.name, "branch": self.out_tree.branch, "count": len(self.processing_warnings)}
				)
				with open(error_outpath, "w") as f:
					f.write(json.dumps(self.processing_warnings))
			else:
				if os.path.exists(error_outpath):
					os.unlink(error_outpath)

	def iter_ebuilds(self):
		"""
		This function is a generator that scans the specified path for ebuilds and yields all
		the ebuilds it finds in this kit. Used for metadata generation.
		"""

		for catdir in os.listdir(self.out_tree.root):
			catpath = os.path.join(self.out_tree.root, catdir)
			if not os.path.isdir(catpath):
				continue
			for pkgdir in os.listdir(catpath):
				pkgpath = os.path.join(catpath, pkgdir)
				if not os.path.isdir(pkgpath):
					continue
				for ebfile in os.listdir(pkgpath):
					if ebfile.endswith(".ebuild"):
						yield os.path.join(pkgpath, ebfile)

	def gen_ebuild_metadata(self, atom, merged_eclasses, ebuild_path):
		# merge.model.log.info(f"get_ebuild_metadata for {ebuild_path} (new)")
		self.kit_cache_misses.add(atom)

		env = {}
		env["PF"] = os.path.basename(ebuild_path)[:-7]
		env["CATEGORY"] = ebuild_path.split("/")[-3]
		pkg_only = ebuild_path.split("/")[-2]  # JUST the pkg name "foobar"
		reduced, rev = strip_rev(env["PF"])
		if rev is None:
			env["PR"] = "r0"
			pkg_and_ver = env["PF"]
		else:
			env["PR"] = f"r{rev}"
			pkg_and_ver = reduced
		env["P"] = pkg_and_ver
		env["PV"] = pkg_and_ver[len(pkg_only) + 1:]
		env["PN"] = pkg_only
		env["PVR"] = env["PF"][len(env["PN"]) + 1:]

		infos = extract_ebuild_metadata(self, atom, ebuild_path, env, reversed(merged_eclasses.paths))

		if not isinstance(infos, dict):
			# metadata extract failure
			return None, None
		return env, infos

	def write_repo_cache_entry(self, atom, metadata_out):
		# if we successfully extracted metadata and we are told to write cache, write the cache entry:
		metadata_outpath = os.path.join(self.out_tree.root, "metadata/md5-cache")
		final_md5_outpath = os.path.join(metadata_outpath, atom)
		os.makedirs(os.path.dirname(final_md5_outpath), exist_ok=True)
		with open(os.path.join(metadata_outpath, atom), "w") as f:
			f.write(metadata_out)

	# TODO: eclass_paths needs to be supported so that we can find eclasses.
	def get_ebuild_metadata(self, merged_eclasses, ebuild_path):
		"""
		This function will grab metadata from a single ebuild pointed to by `ebuild_path` and
		return it as a dictionary.

		This function sets up a clean environment and spawns a bash process which runs `ebuild.sh`,
		which is a file from Portage that processes the ebuild and eclasses and outputs the metadata
		so we can grab it. We do a lot of the environment setup inline in this function for clarity
		(helping the reader understand the process) and also to avoid bunches of function calls.
		"""

		basespl = ebuild_path.split("/")
		atom = basespl[-3] + "/" + basespl[-1][:-7]
		ebuild_md5 = get_md5(ebuild_path)
		cp_dir = ebuild_path[: ebuild_path.rfind("/")]
		manifest_path = cp_dir + "/Manifest"

		if not os.path.exists(manifest_path):
			manifest_md5 = None
		else:
			# TODO: this is a potential area of performance improvement. Multiple ebuilds in a single catpkg
			#       directory will result in get_md5() being called on the same Manifest file multiple times
			#       during a run. Cache might be good here.
			manifest_md5 = get_md5(manifest_path)

		# Try to see if we already have this metadata in our kit metadata cache.
		existing = get_atom(self, atom, ebuild_md5, manifest_md5)

		if existing:
			self.kit_cache_retrieved_atoms.add(atom)
			infos = existing["metadata"]
			self.write_repo_cache_entry(atom, existing["metadata_out"])
			return infos
		# TODO: Note - this may be a 'dud' existing entry where there was a metadata failure previously.
		else:
			env, infos = self.gen_ebuild_metadata(atom, merged_eclasses, ebuild_path)
			if infos is None:
				self.update_atom(atom, {})
				return {}

		eclass_out = ""
		eclass_tuples = []

		if infos["INHERITED"]:
			# Do common pre-processing for eclasses:
			for eclass_name in sorted(infos["INHERITED"].split()):
				if eclass_name not in merged_eclasses.hashes:
					self.processing_warnings.append({"msg": f"Can't find eclass hash for {eclass_name}", "atom": atom})
					continue
				try:
					eclass_out += f"\t{eclass_name}\t{merged_eclasses.hashes[eclass_name]}"
					eclass_tuples.append((eclass_name, merged_eclasses.hashes[eclass_name]))
				except KeyError as ke:
					self.processing_warnings.append({"msg": f"Can't find eclass {eclass_name}", "atom": atom})
					pass

		metadata_out = ""

		for key in AUXDB_LINES:
			if infos[key] != "":
				metadata_out += key + "=" + infos[key] + "\n"
		if len(eclass_out):
			metadata_out += "_eclasses_=" + eclass_out[1:] + "\n"
		metadata_out += "_md5_=" + ebuild_md5 + "\n"

		# Extended metadata calculation:

		td_out = {}
		relations = defaultdict(set)

		for key in ["DEPEND", "RDEPEND", "PDEPEND", "BDEPEND", "HDEPEND"]:
			if infos[key]:
				relations[key] = get_catpkg_relations_from_depstring(infos[key])
		all_relations = set()
		relations_by_kind = dict()

		for key, relset in relations.items():
			all_relations = all_relations | relset
			relations_by_kind[key] = sorted(list(relset))

		td_out["relations"] = sorted(list(all_relations))
		td_out["relations_by_kind"] = relations_by_kind
		td_out["category"] = env["CATEGORY"]
		td_out["revision"] = env["PR"].lstrip("r")
		td_out["package"] = env["PN"]
		td_out["catpkg"] = env["CATEGORY"] + "/" + env["PN"]
		td_out["atom"] = atom
		td_out["eclasses"] = eclass_tuples
		td_out["kit"] = self.out_tree.name
		td_out["branch"] = self.out_tree.branch
		td_out["metadata"] = infos
		td_out["md5"] = ebuild_md5
		td_out["metadata_out"] = metadata_out
		td_out["manifest_md5"] = manifest_md5
		if manifest_md5 is not None and "SRC_URI" in infos:
			td_out["files"] = get_filedata(infos["SRC_URI"], manifest_path)
		self.update_atom(atom, td_out)
		self.write_repo_cache_entry(atom, metadata_out)
		return infos

	def gen_cache(self):
		"""
		Generate md5-cache metadata from a bunch of ebuilds, for this kit. Use a ThreadPoolExecutor to run as many threads
		of this as we have logical cores on the system.
		"""

		total_count_lock = threading.Lock()
		total_count = 0

		with ThreadPoolExecutor(max_workers=cpu_count()) as executor:
			count = 0
			futures = []
			fut_map = {}

			for ebpath in self.iter_ebuilds():
				future = executor.submit(
					self.get_ebuild_metadata,
					self.merged_eclasses,
					ebpath
				)
				fut_map[future] = ebpath
				futures.append(future)

			for future in as_completed(futures):
				count += 1
				data = future.result()
				if data is None:
					sys.stdout.write("!")
				else:
					sys.stdout.write(".")
					sys.stdout.flush()

			with total_count_lock:
				total_count += count

		if total_count:
			merge.model.log.info(f"Metadata for {total_count} ebuilds processed.")
		else:
			merge.model.log.warning(f"No ebuilds were found when processing metadata.")

	async def generate_autogenerated_kit(self):
		#######################################################################################################
		# Destination kit has been wiped (no files) and has had initial overlay metadata created at this point.
		# Before we start copying our forked things and autogens from kit-fixups, we want to first:
		#
		# 1. Copy eclasses we have referenced in our release YAML from source repositories.
		# 2. Copy all packages from source repositories specified in packages.yaml.
		# 3. Remove any excluded files that we didn't want to copy over.
		#######################################################################################################

		await self.run(self.copy_eclasses_steps())
		await self.run(self.packages_yaml_steps())
		await self.run([merge.steps.RemoveFiles(self.kit.get_excludes())])

		#######################################################################################################
		# Now that everything from source repositories (except licenses) has been handled, we will copy over
		# all the forked things from kit-fixups, which will have a chance to overwrite any previously-copied
		# things:
		#######################################################################################################

		await self.run(self.copy_from_fixups_steps())

	async def generate_sourced_kit(self):
		raise NotImplementedError()

	async def generate(self):

		"""
		This function will auto-generate a single 'autogenerated' kit by checking out the current version, wiping the
		contents of the git repo, and copying everything over again, updating metadata cache, etc. and then committing (and
		possibly pushing) the result.
		"""

		# load on-disk JSON metadata cache into memory:

		self.fetch_kit()

		steps = [
			merge.steps.CleanTree(),
			merge.steps.GenerateRepoMetadata(self.kit.name, aliases=self.kit.aliases, masters=self.kit.masters, priority=self.kit.priority)
		]

		await self.run(steps)

		# TODO: add support for sourced kits here.
		if self.kit.kind == KitKind.AUTOGENERATED:
			await self.generate_autogenerated_kit()
		elif self.kit.kind == KitKind.SOURCED:
			await self.generate_sourced_kit()

		##############################################################################
		# Now, we can run any post-steps to get the tree in ready-to-commit condition:
		##############################################################################

		steps = [
			merge.steps.FindAndRemove(["__pycache__"]),
			merge.steps.FindAndRemove(["COPYRIGHT.txt"]), # replaced with COPYRIGHT.rst
			merge.steps.GenerateLicensingFile(text=self.kit.get_copyright_rst()),
			merge.steps.Minify(),
			merge.steps.ELTSymlinkWorkaround(),
			merge.steps.CreateCategories(),
		]
		await self.run(steps)

		############################################################################################################
		# Use lots of CPU (potentially) to generate/update metadata cache:
		############################################################################################################

		self.gen_cache()

		############################################################################################################
		# Python USE settings auto-generation and other finalization steps:
		############################################################################################################

		#TODO: add license processing here.

		# TODO: move this to a post-step and only include active licenses.
		# TODO: we should not hard-reference 'gentoo-staging' anymore.
		#	merge.steps.SyncDir(self.kit.source.repositories["gentoo-staging"].tree.root, "licenses")
		# 			merge.steps.PruneLicenses()


		# TODO: this is not currently working
		post_steps = self.python_auto_use_steps()
		# We can now run all the steps that require access to metadata:
		#await self.run(post_steps)

		update_msg = "Autogenerated tree updates."
		self.out_tree.gitCommit(message=update_msg, push=merge.model.push)

		# save in-memory metadata cache to JSON:
		self.flush_kit()
		self.kit_sha1 = self.out_tree.head()

	def get_kit_pre_post_steps(self):
		# unhandled steps:
		# TODO: do some forking of profiles to fix this:
		# core/"post": [
		# 					merge.steps.ThirdPartyMirrors(),
		# 					merge.steps.RunSed(["profiles/base/make.defaults"], ["/^PYTHON_TARGETS=/d", "/^PYTHON_SINGLE_TARGET=/d"]),
		# 				],
		# core/pre: merge.steps.SyncDir(merge.model.source_repos["gentoo-staging"].root, "eclass"),
		# merge.steps.SyncFiles(
		# 						merge.model.kit_fixups.context,
		# 						{
		# 							"LICENSE.txt": "LICENSE.txt",
		# 						},
		# 					),
		pass

	def python_auto_use_steps(self):
		"""
		Funtoo and metatools has a feature where we will look at the configured Python kits for the release,
		and auto-generate optimal Python USE settings for each kit in the release. This ensures that things
		can be easily merged without weird Python USE errors. These settings are stored in the following
		location in each kit in the release::

			profiles/funtoo/kits/python-kit/<python-kit-branch>

		When 'ego sync' runs, it will ensure that these settings are automatically enabled based upon what
		your currently-active python-kit is. This means that even if you have multiple python-kit branches
		defined in your release, switching between them is seamless and Python USE settings for all packages
		in the repository will auto-adapt to whatever Python kit is currently enabled.
		"""
		steps = []
		for kit in merge.model.release_yaml.iter_kits(name="python-kit"):
			steps += [merge.steps.GenPythonUse("funtoo/kits/python-kit/%s" % kit.branch)]
		return steps

	def copy_eclasses_steps(self):

		kit_copy_info = self.kit.eclass_include_info()
		mask = kit_copy_info["mask"]
		file_mask = map(lambda x: f"{x}.eclass", list(mask))
		steps = []
		for srepo_name, eclass_name_list in kit_copy_info["include"].items():
			copy_eclasses = set()
			for eclass_item in eclass_name_list:
				if eclass_item == "*":
					steps.append(merge.steps.SyncDir(self.kit.source.repositories[srepo_name].tree, "eclass", exclude=file_mask))
				else:
					if eclass_item not in mask:
						copy_eclasses.add(eclass_item)
					else:
						merge.model.log.warn(f"For kit {self.kit.name}, {eclass_item} is both included and excluded in the release YAML.")
			if copy_eclasses:
				copy_tuples = []
				for item in copy_eclasses:
					if item.split("/")[-1] not in mask:
						file_path = f"eclass/{item}.eclass"
						copy_tuples.append((file_path, file_path))
				steps.append(merge.steps.CopyFiles(self.kit.source.repositories[srepo_name].tree, copy_tuples))
		return steps

	def packages_yaml_steps(self):
		"""
		This method returns all steps related to the 'packages' entries in the package.yaml file, and getting these
		packages copied over from the source repositories.
		"""
		steps = []
		# Copy over catpkgs listed in 'packages' section:
		for repo_name, packages in self.kit.get_kit_packages():
			self.active_repos.add(repo_name)
			# TODO: add move maps below
			steps += [merge.steps.InsertEbuilds(self.kit.source.repositories[repo_name].tree, skip=None, replace=True, move_maps=None, select=packages, scope=merge.model.release)]
		return steps

	def copy_from_fixups_steps(self):
		"""
		Copy eclasses, licenses, profile info, and ebuild/eclass fixups from the kit-fixups repository.

		First, we are going to process the kit-fixups repository and look for ebuilds and eclasses to replace. Eclasses can be
		overridden by using the following paths inside kit-fixups:

		* kit-fixups/eclass/1.2-release <--------- global eclasses, get installed to all kits unconditionally for release (overrides those above)
		* kit-fixups/<kit>/global/eclass <-------- global eclasses for a particular kit, goes in all branches (overrides those above)
		* kit-fixups/<kit>/global/profiles <------ global profile info for a particular kit, goes in all branches (overrides those above)
		* kit-fixups/<kit>/<branch>/eclass <------ eclasses to install in just a specific branch of a specific kit (overrides those above)
		* kit-fixups/<kit>/<branch>/profiles <---- profile info to install in just a specific branch of a specific kit (overrides those above)

		Note that profile repo_name and categories files are excluded from any copying.

		Ebuilds can be installed to kits by putting them in the following location(s):

		* kit-fixups/<kit>/global/cat/pkg <------- install cat/pkg into all branches of a particular kit
		* kit-fixups/<kit>/<branch>/cat/pkg <----- install cat/pkg into a particular branch of a kit
		"""
		steps = []
		# Here is the core logic that copies all the fix-ups from kit-fixups (eclasses and ebuilds) into place:
		eclass_release_path = "eclass/%s" % merge.model.release
		if os.path.exists(os.path.join(merge.model.kit_fixups.root, eclass_release_path)):
			steps += [merge.steps.SyncDir(merge.model.kit_fixups.root, eclass_release_path, "eclass")]
		fixup_dirs = ["global", "curated", self.kit.branch]
		for fixup_dir in fixup_dirs:
			fixup_path = self.kit.name + "/" + fixup_dir
			if os.path.exists(merge.model.kit_fixups.root + "/" + fixup_path):
				if os.path.exists(merge.model.kit_fixups.root + "/" + fixup_path + "/eclass"):
					steps += [
						merge.steps.InsertFilesFromSubdir(
							merge.model.kit_fixups, "eclass", ".eclass", select="all", skip=None, src_offset=fixup_path
						)
					]
				if os.path.exists(merge.model.kit_fixups.root + "/" + fixup_path + "/licenses"):
					steps += [
						merge.steps.InsertFilesFromSubdir(
							merge.model.kit_fixups, "licenses", None, select="all", skip=None, src_offset=fixup_path
						)
					]
				if os.path.exists(merge.model.kit_fixups.root + "/" + fixup_path + "/profiles"):
					steps += [
						merge.steps.InsertFilesFromSubdir(
							merge.model.kit_fixups, "profiles", None, select="all", skip=["repo_name", "categories"], src_offset=fixup_path
						)
					]
				# copy appropriate kit readme into place:
				readme_path = fixup_path + "/README.rst"
				if os.path.exists(merge.model.kit_fixups.root + "/" + readme_path):
					steps += [merge.steps.SyncFiles(merge.model.kit_fixups.root, {readme_path: "README.rst"})]

				# We now add a step to insert the fixups, and we want to record them as being copied so successive kits
				# don't get this particular catpkg. Assume we may not have all these catpkgs listed in our package-set
				# file...

				steps += [
					merge.steps.InsertEbuilds(merge.model.kit_fixups, ebuildloc=fixup_path, select="all", skip=None, replace=True, scope=merge.model.release)
				]
		return steps


class KitPipeline:

	def __init__(self, key, jobs):
		self.key = key
		self.jobs = jobs

	def initialize_source_repository(self, repo: SourceRepository):
		#if repo_key in merge.model.source_repos:
		#	repo_obj = merge.model.source_repos[repo_key]
		#	if repo_sha1:
		#		repo_obj.gitCheckout(sha1=repo_sha1)
		#	elif repo_branch:
		#		repo_obj.gitCheckout(branch=repo_branch)
		#else:
		merge.model.log.info(f"Initializing Source Repository {repo.name}")
		repo.tree = GitTree(
			repo.name,
			url=repo.url,
			root="%s/%s" % (merge.model.source_trees, repo.name),
			branch=repo.branch,
			commit_sha1=repo.src_sha1,
			origin_check=False,
			reclone=False,
			model=merge.model
		)
		repo.tree.initialize()

	def initialize_sources(self, source_def: SourceCollection):

		"""
		This method initializes the source repositories referenced by the kit to ensure that they are all initialized to the
		proper branch and/or SHA1. Some internal checking is done to avoid re-initializing repositories unnecessarily, so if
		they are already set up properly then no action will be taken.
		"""

		# If we are already using this SourceCollection, no action is needed:
		merge.model.log.info(f"Initializing source collection {source_def.name} with {len(source_def.repositories)} repositories")
		if merge.model.current_source_def == source_def:
			return

		# If we need to switch SourceCollection, we can still avoid unnecessary work:
		# We will go through each of our repositories, and only (re-)initialize it if:
		#
		# 1. Our repo is missing.
		# 2. Our repo exists with same name but is referencing a different branch/sha1.

		repo_futures = []
		with ThreadPoolExecutor(max_workers=4) as executor:
			for repo_name, repo in source_def.repositories.items():
				fut = executor.submit(self.initialize_source_repository, repo)
				repo_futures.append(fut)
			for repo_fut in as_completed(repo_futures):
				# Getting .result() will also cause any exception to be thrown:
				repo_dict = repo_fut.result()
				continue

		merge.model.current_source_def = source_def

	async def run(self):
		pass


class ParallelKitPipeline(KitPipeline):

	async def run(self):
		if not len(self.jobs):
			return
		# All kits here are sharing the same sources collection, so we just have to initialize them once:
		self.initialize_sources(self.jobs[0].kit.source)
		regen_futures = []
		with ThreadPoolExecutor(max_workers=8) as executor:
			for kit_job in self.jobs:
				future = executor.submit(hub.run_async_adapter, kit_job.generate)
				regen_futures.append(future)
			for future in as_completed(regen_futures):
				result = future.result()


class MasterKitPipeline(KitPipeline):

	current_source_def = None

	def __init__(self, jobs):
		super().__init__("masters", jobs)

	async def run(self):
		for kit_job in self.jobs:
			# Each master may have different sources, so perform initialize call prior to each run:
			self.initialize_sources(kit_job.kit.source)
			await kit_job.generate()


class MetaRepoJobController:

	"""
	This class is designed to run the full meta-repo and kit regeneration process -- in other words, the entire
	technical flow of 'merge-kits' when it creates or updates kits and meta-repo.
	"""

	pipeline_count = 0
	kit_pipeline_keys = ["masters"]
	kit_pipeline_slots = defaultdict(list)
	kit_jobs = []

	def __init__(self):
		self.generate_jobs_and_pipelines()

	def iter_pipelines(self):
		for pipeline_key in self.kit_pipeline_keys[1:]:
			yield ParallelKitPipeline(pipeline_key, self.kit_pipeline_slots[pipeline_key])

	async def generate(self):
		merge.metadata.cleanup_error_logs()

		master_pipeline = MasterKitPipeline(jobs=self.kit_pipeline_slots["masters"])
		await master_pipeline.run()

		for pipeline in self.iter_pipelines():
			await pipeline.run()

		# Create meta-repo commit referencing our updated kits:
		merge.kit.generate_metarepo_metadata(merge.model.kit_sha1s)
		merge.model.meta_repo.gitCommit(message="kit updates", skip=["kits"], push=merge.model.push)

		if not merge.model.prod:
			# check out preferred kit branches, because there's a good chance we'll be using it locally.
			for name, ctx in merge.sources.get_kit_preferred_branches().items():
				merge.model.log.info(f"Checking out {name} {ctx.kit.branch}...")
				await merge.kit.checkout_kit(ctx, pull=False)

		if not merge.model.mirror_repos:
			merge.metadata.display_error_summary()
			return

		# Mirroring to GitHub happens here:

		merge.kit.mirror_all_repositories()
		merge.metadata.display_error_summary()

	def get_kit_preferred_branches(self):
		"""
		When we generate a meta-repo, and we're not in "prod" mode, then it's likely that we will be using
		our meta-repo locally. In this case, it's handy to have the proper kits checked out after this is
		done. So for example, we would want gnome-kit 3.36-prime checked out not 3.34-prime, since 3.36-prime
		is the preferred branch in the metadata. This function will return a dict of kit names with the
		values being a AttrDict with the info specific to the kit.
		"""
		out = {}

		for kit_dict in merge.model.kit_groups:
			name = kit_dict["name"]
			stability = kit_dict["stability"]
			if stability != "prime":
				continue
			if name in out:
				# record first instance of kit from the YAML, ignore others (primary kit is the first one listed)
				continue
			out[name] = AttrDict()
			out[name].kit = AttrDict(kit_dict)
		return out

	def create_new_pipeline(self) -> str:
		"""
		This method creates a new kit pipeline and returns its index as a string.
		"""
		pipeline_key = f"pipeline{self.pipeline_count}"
		self.pipeline_count += 1
		self.kit_pipeline_keys.append(pipeline_key)
		return pipeline_key

	def find_existing_pipeline(self, kit_job: KitGenerator):
		"""
		For threading, we want to group kits into collections (pipelines) when they can legally run at the same
		time. This function will help us find a pipeline which we can "legally" join. If we can't find an existing
		pipeline that works for us, this function will return None so we can know to create a new thread pipeline.

		TODO: we can potentially parallelize this further by detecting when there are no source repositories in
		      common, even if ``other.source != kit.source`` -- these can still be auto-generated in parallel.
		"""

		for pipeline_key in self.kit_pipeline_keys[1:]:
			skip_pipeline = False
			for other in self.kit_pipeline_slots[pipeline_key]:
				if other.kit.source != kit_job.kit.source:
					# Autogenerated kit different git sources, can't use this pipeline:
					skip_pipeline = True
					break
				elif other.kit.name == kit_job.kit.name:
					# already processing another branch of same kit in this pipeline, so can't run simultaneously:
					skip_pipeline = True
					break
			if skip_pipeline:
				continue
			return pipeline_key
		return None

	def generate_jobs_and_pipelines(self):

		"""
		This method organizes to-be-generated kits into pipelines containing kit jobs (KitGenerators) to regenerate the kits.

		The first pipeline is called "masters" and is special -- each kit in this pipeline is generated in-order, and there must be only
		one of each of these kits defined in the entire release. These are the 'foundational' kits of the release that contain eclasses and
		that other kits reference (core-kit, llvm-kit).

		Successive pipelines contain one or more kits that can be (re)generated at the same time, because they use the same source repositories.
		To improve performance, this class will parallelize these pipelines.

		For 'regular' kits, we cannot generate two kits in parallel if any of these conditions are true:

		1. The kits are for different branches of the same kit (they will clobber writes to the dest. tree)
		2. The kits reference a different set of source repositories (they need different sha1's checked out at the same time.)
		"""

		all_masters = set()
		for kit_name, kit_list in merge.model.release_yaml.kits.items():
			for kit in kit_list:
				all_masters |= set(kit.masters)

		for master in all_masters:
			if not len(merge.model.release_yaml.kits[master]):
				raise ValueError(f"Master {master} defined in release does not seem to exist in kits YAML.")
			elif len(merge.model.release_yaml.kits[master]) > 1:
				raise ValueError(f"This release defines {master} multiple times, but it is a master. Only define one master since it is foundational to the release.")

		master_jobs = {}
		for kit_name, kit_list in merge.model.release_yaml.kits.items():
			for kit in kit_list:
				kit_job = KitGenerator(kit, is_master=kit_name in all_masters)
				self.kit_jobs.append(kit_job)
				if kit_name in all_masters:
					master_jobs[kit_name] = kit_job
				if kit_job.is_master:
					self.kit_pipeline_slots["masters"].append(kit_job)
				else:
					my_pipeline = self.find_existing_pipeline(kit_job)
					if my_pipeline is None:
						my_pipeline = self.create_new_pipeline()
					self.kit_pipeline_slots[my_pipeline].append(kit_job)

		# Generate 'merged eclasses', which is essentially all the eclasses from kits (overlays) 'smooshed' into the final
		# set of eclasses. This is used for metadata generation:

		for kit_job in self.kit_jobs:
			merged_eclasses = EclassHashCollection()
			for master in kit_job.kit.masters:
				merged_eclasses += master_jobs[master].eclasses
			merged_eclasses += kit_job.eclasses
			kit_job.merged_eclasses = merged_eclasses


	# TODO: does this need to be upgraded to handle multiple remotes?
	def mirror_repository(self, repo_obj, base_path):
		"""
		Mirror a repository to its mirror location, ie. GitHub.
		"""

		os.makedirs(base_path, exist_ok=True)
		run_shell(f"git clone --bare {repo_obj.root} {base_path}/{repo_obj.name}.pushme")
		run_shell(
			f"cd {base_path}/{repo_obj.name}.pushme && git remote add upstream {repo_obj.mirror} && git push --mirror upstream"
		)
		run_shell(f"rm -rf {base_path}/{repo_obj.name}.pushme")
		return repo_obj.name

	def mirror_all_repositories(self):
		base_path = os.path.join(merge.temp_path, "mirror_repos")
		run_shell(f"rm -rf {base_path}")
		kit_mirror_futures = []
		with ThreadPoolExecutor(max_workers=8) as executor:
			# Push all kits, then push meta-repo.
			for kit_name, kit_tuple in merge.model.kit_results.items():
				ctx, tree_obj, tree_sha1 = kit_tuple
				future = executor.submit(self.mirror_repository, tree_obj, base_path)
				kit_mirror_futures.append(future)
			for future in as_completed(kit_mirror_futures):
				kit_name = future.result()
				print(f"Mirroring of {kit_name} complete.")
		merge.kit.mirror_repository(merge.model.meta_repo, base_path)
		print("Mirroring of meta-repo complete.")


class MetaRepoGenerator:

	def __init__(self):
		meta_repo_config = self.release_yaml.get_meta_repo_config()
		self.meta_repo = self.git_class(
			name="meta-repo",
			branch=release,
			url=meta_repo_config['url'],
			root=self.dest_trees + "/meta-repo",
			origin_check=True if self.prod else None,
			mirrors=meta_repo_config['mirrors'],
			create_branches=self.create_branches,
			model=self
		)
		self.start_time = datetime.utcnow()
		self.meta_repo.initialize()


# TODO: integrate this into the workflow
def generate_metarepo_metadata(self):
	"""
	Generates the metadata in /var/git/meta-repo/metadata/...
	:param release: the release string, like "1.3-release".
	:param merge.model.meta_repo: the meta-repo GitTree.
	:return: None.
	"""

	if not os.path.exists(merge.model.meta_repo.root + "/metadata"):
		os.makedirs(merge.model.meta_repo.root + "/metadata")

	with open(merge.model.meta_repo.root + "/metadata/kit-sha1.json", "w") as a:
		a.write(json.dumps(output_sha1s, sort_keys=True, indent=4, ensure_ascii=False))

	outf = merge.model.meta_repo.root + "/metadata/kit-info.json"
	all_kit_names = sorted(output_sha1s.keys())

	with open(outf, "w") as a:
		k_info = {}
		out_settings = defaultdict(lambda: defaultdict(dict))
		for kit_dict in merge.model.kit_groups:
			kit_name = kit_dict["name"]
			# specific keywords that can be set for each branch to identify its current quality level
			out_settings[kit_name]["stability"][kit_dict["branch"]] = kit_dict["stability"]
			kind_json = "auto"
			out_settings[kit_name]["type"] = kind_json
		k_info["kit_order"] = all_kit_names
		k_info["kit_settings"] = out_settings

		# auto-generate release-defs. We used to define them manually in foundation:
		rdefs = {}
		for kit_name in all_kit_names:
			rdefs[kit_name] = []
			for def_kit in filter(
				lambda x: x["name"] == kit_name and x["stability"] not in ["deprecated"], merge.model.kit_groups
			):
				rdefs[kit_name].append(def_kit["branch"])

	rel_info = merge.model.release_info()

	k_info["release_defs"] = rdefs
	k_info["release_info"] = rel_info
	a.write(json.dumps(k_info, sort_keys=True, indent=4, ensure_ascii=False))

	with open(merge.model.meta_repo.root + "/metadata/version.json", "w") as a:
		a.write(json.dumps(rel_info, sort_keys=True, indent=4, ensure_ascii=False))


