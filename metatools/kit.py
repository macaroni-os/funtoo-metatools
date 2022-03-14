#!/usr/bin/env python3
import glob
import json
import sys
import threading
from collections import defaultdict
from concurrent.futures import as_completed
from concurrent.futures.thread import ThreadPoolExecutor
from multiprocessing import cpu_count
from typing import Union

from subpop.util import AttrDict

from metatools.config.merge import Kit, KitKind, AutoGeneratedKit, SourcedKit
from metatools.hashutils import get_md5
from metatools.metadata import AUXDB_LINES, get_catpkg_relations_from_depstring, get_filedata, extract_ebuild_metadata, strip_rev, get_atom, load_json, CACHE_DATA_VERSION
from metatools.tree import GitTreeError, run_shell
import metatools.steps
import os

from metatools.model import get_model
model = get_model("metatools.merge")


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

	def __repr__(self):
		return f"KitGenerator(kit.name={self.kit.name}, kit.branch={self.kit.branch})"

	def __init__(self, kit: Union[SourcedKit, AutoGeneratedKit], is_master=False):
		self.kit = kit
		self.is_master = is_master

		git_class = model.git_class

		if model.nest_kits:
			root = os.path.join(model.dest_trees, "meta-repo/kits", kit.name)
		else:
			root = os.path.join(model.dest_trees, kit.name)
		self.out_tree = git_class(kit.name, branch=kit.branch, root=root, model=model)
		self.out_tree.initialize()
		self.eclasses = EclassHashCollection(path=self.out_tree.root)

	def get_kit_cache_path(self):
		os.makedirs(os.path.join(model.temp_path, "kit_cache"), exist_ok=True)
		return os.path.join(model.temp_path, "kit_cache", f"{self.out_tree.name}-{self.out_tree.branch}")

	def update_atom(self, atom, td_out):
		"""
		Update our in-memory record for a specific ebuild atom on disk that has changed. This will
		be written out by flush_kit(). Right now we just record it in memory.

		"""
		self.kit_cache[atom] = td_out
		self.kit_cache_writes.add(atom)

	async def run(self, steps):
		"""
		This command runs ga series of steps. What I need to add is proper propagation of errors to caller.
		"""
		for step in steps:
			if step is not None:
				model.log.info(f"Running step {step.__class__.__name__} for {self.out_tree.root}")
				await step.run(self)

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
				model.log.warning(f"Kit cache at {outpath} may be empty and will be overwritten.")
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
		remove_keys = set()
		if prune:
			all_keys = set(self.kit_cache.keys())
			remove_keys = all_keys - (self.kit_cache_retrieved_atoms | self.kit_cache_writes)
			extra_atoms = self.kit_cache_retrieved_atoms - all_keys
			for key in remove_keys:
				del self.kit_cache[key]
			if len(extra_atoms):
				model.log.error("THERE ARE EXTRA ATOMS THAT WERE RETRIEVED BUT NOT IN CACHE!")
				model.log.error(f"{extra_atoms}")
		if save:
			outpath = self.get_kit_cache_path()
			outdata = {
				"cache_data_version": CACHE_DATA_VERSION,
				"atoms": self.kit_cache,
				"metadata_errors": self.metadata_errors,
			}
			model.log.warning(f"Flushed {self.kit.name}. {len(self.kit_cache)} atoms. Removed {len(remove_keys)} keys. {len(self.metadata_errors)} errors.")
			with open(outpath, "w") as f:
				f.write(json.dumps(outdata))

			# Add summary to hub of error count for this kit, and also write out the error logs:

			error_outpath = os.path.join(
				model.temp_path, f"metadata-errors-{self.out_tree.name}-{self.out_tree.branch}.log"
			)
			if len(self.metadata_errors):
				model.metadata_error_stats.append(
					{"name": self.out_tree.name, "branch": self.out_tree.branch, "count": len(self.metadata_errors)}
				)
				with open(error_outpath, "w") as f:
					f.write(json.dumps(self.metadata_errors))
			else:
				if os.path.exists(error_outpath):
					os.unlink(error_outpath)

			error_outpath = os.path.join(model.temp_path, f"warnings-{self.out_tree.name}-{self.out_tree.branch}.log")
			if len(self.processing_warnings):
				model.processing_warning_stats.append(
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
			model.log.info(f"Metadata for {total_count} ebuilds processed.")
		else:
			model.log.warning(f"No ebuilds were found when processing metadata.")

	async def fail(self):
		raise GitTreeError()

	def initialize_sources(self):
		self.kit.initialize_sources()

	async def generate_sourced(self):
		"""
		This function contains the full steps used for generating a "sourced" kit. These steps are:

		1. Run autogen in the sourced tree.
		2. Copy everything over from the sourced tree.

		Note that kit-fixups is not used in this case -- all autogens, ebuilds, eclasses, etc. come from the sourced tree.

		Once these steps are all done, the kit is ready for finalization (gencache, etc) and a git commit which will contain
		the new changes.
		"""

		src_tree = self.kit.source.tree
		await self.run([
			metatools.steps.Autogen(src_tree),
			metatools.steps.SyncFromTree(src_tree)
		])

	async def generate_autogenerated(self):
		"""
		This function produces steps to recreate the contents of an autogenerated kit. This is typically run with a
		destination kit that has been "emptied" and is ready to be regenerated from scratch:

		1. First, look at ``packages.yaml`` and copy over any specified eclasses and files from source repositories.
		2. Next, look at ``packages.yaml``, and copy over any specified ebuilds from any source repositories. Note
		   that we do not run autogen for source repositories used in this way.
	    3. Next, *remove* any files we specifically want to exclude from the destination kit.

	    In the second phase, we then perform the following actions:

	    4. Run autogen on the proper part of kit-fixups.
	    5. Copy over all resultant ebuilds, eclasses, licenses, etc from kit-fixups that should be copied.

	    This ensures that kit-fixups overrides whatever was in the source repositories. Once these steps are all done,
	    the kit is ready for finalization (gencache, etc.) and a git commit which will contain the new changes.
		"""

		await self.run(self.copy_eclasses_steps())
		await self.run(self.packages_yaml_copy_ebuilds_steps())
		await self.run([metatools.steps.RemoveFiles(self.kit.get_excludes())])
		await self.run(self.autogen_and_copy_from_kit_fixups())

	async def generate(self):
		"""
		This function contains the full step-flow for updating a kit. This function handles both autogenerated kits
		and sourced kits.

		Here is a basic overview of the process:

		1. The to-be-updated kit is completely emptied of all files. (``CleanTree()``)
		2. The basic metadata is created inside the kit to make it a valid, but empty overlay. (``GenerateRepoMetadata()``)
		3. Depending on what type of kit it is -- autogenerated or sourced -- the steps will be executed to populate the kit
		   with its updated contents.
		4. Various miscellaneous tasks will be executed -- creating a global licensing information file, cleaning up of Manifests, etc.
	    5. The Portage metadata cache will be updated and stored inside the kit.
	    6. Auto-generation of Python USE settings will be performed. This optimizes the Python USE experience for Funtoo users.
	    7. Licenses used by the ebuilds will be copied over to the ``licenses/`` directory.
		7. A new git commit within the kit will be created based on the result of these steps.
		8. The HEAD SHA1 will be recorded so that we can record it later within the meta-repo metadata.
		"""

		# load on-disk JSON metadata cache into memory:

		self.fetch_kit()

		await self.run([
			metatools.steps.CleanTree(),
			metatools.steps.GenerateRepoMetadata(self.kit.name, aliases=self.kit.aliases, masters=self.kit.masters, priority=self.kit.priority)
		])

		if isinstance(self.kit, AutoGeneratedKit):
			await self.generate_autogenerated()
		elif isinstance(self.kit, SourcedKit):
			await self.generate_sourced()


		##############################################################################
		# Now, we can run any post-steps to get the tree in ready-to-commit condition:
		##############################################################################

		await self.run([
			metatools.steps.FindAndRemove(["__pycache__"]),
			metatools.steps.FindAndRemove(["COPYRIGHT.txt"]), # replaced with COPYRIGHT.rst
			metatools.steps.GenerateLicensingFile(text=self.kit.get_copyright_rst()),
			metatools.steps.Minify(),
			metatools.steps.ELTSymlinkWorkaround(),
			metatools.steps.CreateCategories(),
		])

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
		self.out_tree.gitCommit(message=update_msg, push=model.push)

		# save in-memory metadata cache to JSON:
		self.flush_kit()
		self.kit_sha1 = self.out_tree.head()
		# This will get passed as the "result" if run in a ThreadPoolGenerator() (when we call get_result())
		return self

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
		my_steps = []
		for kit in model.release_yaml.iter_kits(name="python-kit"):
			my_steps += [metatools.steps.GenPythonUse("funtoo/kits/python-kit/%s" % kit.branch)]
		return my_steps

	def copy_eclasses_steps(self):

		kit_copy_info = self.kit.eclass_include_info()
		mask = kit_copy_info["mask"]
		file_mask = map(lambda x: f"{x}.eclass", list(mask))
		my_steps = []
		for srepo_name, eclass_name_list in kit_copy_info["include"].items():
			copy_eclasses = set()
			for eclass_item in eclass_name_list:
				if eclass_item == "*":
					my_steps.append(metatools.steps.SyncDir(self.kit.source.repositories[srepo_name].tree, "eclass", exclude=file_mask))
				else:
					if eclass_item not in mask:
						copy_eclasses.add(eclass_item)
					else:
						model.log.warn(f"For kit {self.kit.name}, {eclass_item} is both included and excluded in the release YAML.")
			if copy_eclasses:
				copy_tuples = []
				for item in copy_eclasses:
					if item.split("/")[-1] not in mask:
						file_path = f"eclass/{item}.eclass"
						copy_tuples.append((file_path, file_path))
				my_steps.append(metatools.steps.CopyFiles(self.kit.source.repositories[srepo_name].tree, copy_tuples))
		return my_steps

	def get_source_repo(self):
		raise NotImplementedError()

	def packages_yaml_copy_ebuilds_steps(self):
		"""
		This method returns all steps related to the 'packages' entries in the package.yaml file, and getting these
		packages copied over from the source repositories. Note that we do not run autogen for any trees for which
		we are using in this way.
		"""
		my_steps = []
		# Copy over catpkgs listed in 'packages' section:
		for repo_name, packages in self.kit.get_kit_packages():
			self.active_repos.add(repo_name)
			my_steps += [metatools.steps.InsertEbuilds(self.kit.source.repositories[repo_name].tree, skip=None, replace=True, move_maps=None, select=packages)]
		return my_steps

	def autogen_and_copy_from_kit_fixups(self):
		"""
		Return steps that will, as a whole, copy over everything from kit-fixups to a destination kit. These steps will include:

		1. Running autogen in the appropriate subdirectories inside kit-fixups.
		2. Copying over ebuilds from these subdirectories.

		The steps are ordered correctly so that "curated", "next", "1.4-release" directories have the proper precedence over one
		another (with a more specific release's ebuild overriding what might be in "curated".)

		The end result will be that opy over eclasses, licenses, profile info, and ebuild/eclass fixups from the kit-fixups repository.

		How the Algorithm Works
		=======================

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
		eclass_release_path = "eclass/%s" % model.release
		if os.path.exists(os.path.join(model.kit_fixups.root, eclass_release_path)):
			steps += [metatools.steps.SyncDir(model.kit_fixups.root, eclass_release_path, "eclass")]
		fixup_dirs = ["global", "curated", self.kit.branch]
		for fixup_dir in fixup_dirs:
			fixup_path = self.kit.name + "/" + fixup_dir
			if os.path.exists(model.kit_fixups.root + "/" + fixup_path):
				if os.path.exists(model.kit_fixups.root + "/" + fixup_path + "/eclass"):
					steps += [
						metatools.steps.InsertFilesFromSubdir(
							model.kit_fixups, "eclass", ".eclass", select="all", skip=None, src_offset=fixup_path
						)
					]
				if os.path.exists(model.kit_fixups.root + "/" + fixup_path + "/licenses"):
					steps += [
						metatools.steps.InsertFilesFromSubdir(
							model.kit_fixups, "licenses", None, select="all", skip=None, src_offset=fixup_path
						)
					]
				if os.path.exists(model.kit_fixups.root + "/" + fixup_path + "/profiles"):
					steps += [
						metatools.steps.InsertFilesFromSubdir(
							model.kit_fixups, "profiles", None, select="all", skip=["repo_name", "categories"], src_offset=fixup_path
						)
					]
				# copy appropriate kit readme into place:
				readme_path = fixup_path + "/README.rst"
				if os.path.exists(model.kit_fixups.root + "/" + readme_path):
					steps += [metatools.steps.SyncFiles(model.kit_fixups.root, {readme_path: "README.rst"})]

				# We now add a step to insert the fixups, and we want to record them as being copied so successive kits
				# don't get this particular catpkg. Assume we may not have all these catpkgs listed in our package-set
				# file...

				# TODO: since we are running autogen in a for-loop, below, there is always the possibility of parallelizing this code further.
				#       The only challenge is that we may be autogenning similar ebuilds, and thus we may be writing to the same Store() behind-the-scenes.

				steps += [
					metatools.steps.Autogen(model.kit_fixups, ebuildloc=fixup_path),
					metatools.steps.InsertEbuilds(model.kit_fixups, ebuildloc=fixup_path, select="all", skip=None, replace=True)
				]
		return steps


class KitExecutionPool:

	def __init__(self, jobs):
		self.jobs = jobs

	async def run(self):
		for kit_job in self.jobs:

			model.log.debug(f"KitExecutionPool: running job {kit_job}")
			kit_job.initialize_sources()
			await kit_job.generate()
			model.log.debug(f"KitExecutionPool: job {kit_job} complete")


class MetaRepoJobController:

	"""
	This class is designed to run the full meta-repo and kit regeneration process -- in other words, the entire
	technical flow of 'merge-kits' when it creates or updates kits and meta-repo.
	"""

	kit_jobs = []
	model = None

	def __init__(self, model):
		model = model

	def cleanup_error_logs(self):
		# This should be explicitly called at the beginning of every command that generates metadata for kits:

		for file in glob.glob(os.path.join(model.temp_path, "metadata-errors*.log")):
			os.unlink(file)

	def display_error_summary(self):
		for stat_list, name, shortname in [
			(model.metadata_error_stats, "metadata extraction errors", "errors"),
			(model.processing_warning_stats, "warnings", "warnings"),
		]:
			if len(stat_list):
				for stat_info in stat_list:
					stat_info = AttrDict(stat_info)
					model.log.warning(f"The following kits had {name}:")
					branch_info = f"{stat_info.name} branch {stat_info.branch}".ljust(30)
					model.log.warning(f"* {branch_info} -- {stat_info.count} {shortname}.")
				model.log.warning(f"{name} errors logged to {model.temp_path}.")

	def generate_metarepo_metadata(self):

		output_sha1s = model.kit_sha1s
		if not os.path.exists(model.meta_repo.root + "/metadata"):
			os.makedirs(model.meta_repo.root + "/metadata")

		with open(model.meta_repo.root + "/metadata/kit-sha1.json", "w") as a:
			a.write(json.dumps(output_sha1s, sort_keys=True, indent=4, ensure_ascii=False))

		outf = model.meta_repo.root + "/metadata/kit-info.json"
		all_kit_names = sorted(output_sha1s.keys())

		with open(outf, "w") as a:
			k_info = {}
			out_settings = defaultdict(lambda: defaultdict(dict))
			for kit_dict in model.kit_groups:
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
						lambda x: x["name"] == kit_name and x["stability"] not in ["deprecated"], model.kit_groups
				):
					rdefs[kit_name].append(def_kit["branch"])

		rel_info = model.release_info()

		k_info["release_defs"] = rdefs
		k_info["release_info"] = rel_info
		a.write(json.dumps(k_info, sort_keys=True, indent=4, ensure_ascii=False))

		with open(model.meta_repo.root + "/metadata/version.json", "w") as a:
			a.write(json.dumps(rel_info, sort_keys=True, indent=4, ensure_ascii=False))

	async def generate(self):
		model.log.debug("In generate() start")
		self.cleanup_error_logs()

		all_masters = set()
		for kit_name, kit_list in model.release_yaml.kits.items():
			for kit in kit_list:
				all_masters |= set(kit.masters)

		for master in all_masters:
			if not len(model.release_yaml.kits[master]):
				raise ValueError(f"Master {master} defined in release does not seem to exist in kits YAML.")
			elif len(model.release_yaml.kits[master]) > 1:
				raise ValueError(f"This release defines {master} multiple times, but it is a master. Only define one master since it is foundational to the release.")

		master_jobs_list = []
		other_jobs_list = []
		master_jobs = {}
		for kit_name, kit_list in model.release_yaml.kits.items():
			for kit in kit_list:
				kit_job = KitGenerator(kit, is_master=kit_name in all_masters)
				self.kit_jobs.append(kit_job)
				if kit_name in all_masters:
					master_jobs[kit_name] = kit_job
				if kit_job.is_master:
					master_jobs_list.append(kit_job)
				else:
					other_jobs_list.append(kit_job)

		# Generate 'merged eclasses', which is essentially all the eclasses from kits (overlays) 'smooshed' into the final
		# set of eclasses. This is used for metadata generation:

		for kit_job in self.kit_jobs:
			merged_eclasses = EclassHashCollection()
			for master in kit_job.kit.masters:
				merged_eclasses += master_jobs[master].eclasses
			merged_eclasses += kit_job.eclasses
			kit_job.merged_eclasses = merged_eclasses

		master_pool = KitExecutionPool(jobs=master_jobs_list)
		await master_pool.run()

		other_pool = KitExecutionPool(jobs=other_jobs_list)
		await other_pool.run()

		# Create meta-repo commit referencing our updated kits:
		self.generate_metarepo_metadata()
		model.meta_repo.gitCommit(message="kit updates", skip=["kits"], push=model.push)

		if not model.prod:
			# check out preferred kit branches, because there's a good chance we'll be using it locally.
			for name, ctx in self.get_kit_preferred_branches().items():
				model.log.info(f"Checking out {name} {ctx.kit.branch}...")
				await self.checkout_kit(ctx, pull=False)

		if not model.mirror_repos:
			self.display_error_summary()
			return

		# Mirroring to GitHub happens here:

		self.mirror_all_repositories()
		self.display_error_summary()

	def get_kit_preferred_branches(self):
		"""
		When we generate a meta-repo, and we're not in "prod" mode, then it's likely that we will be using
		our meta-repo locally. In this case, it's handy to have the proper kits checked out after this is
		done. So for example, we would want gnome-kit 3.36-prime checked out not 3.34-prime, since 3.36-prime
		is the preferred branch in the metadata. This function will return a dict of kit names with the
		values being a AttrDict with the info specific to the kit.
		"""
		out = {}

		for kit_dict in model.kit_groups:
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
		base_path = os.path.join(model.temp_path, "mirror_repos")
		run_shell(f"rm -rf {base_path}")
		kit_mirror_futures = []
		with ThreadPoolExecutor(max_workers=8) as executor:
			# Push all kits, then push meta-repo.
			for kit_name, kit_tuple in model.kit_results.items():
				ctx, tree_obj, tree_sha1 = kit_tuple
				future = executor.submit(self.mirror_repository, tree_obj, base_path)
				kit_mirror_futures.append(future)
			for future in as_completed(kit_mirror_futures):
				kit_name = future.result()
				print(f"Mirroring of {kit_name} complete.")
		self.mirror_repository(model.meta_repo, base_path)
		print("Mirroring of meta-repo complete.")


"""
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

"""