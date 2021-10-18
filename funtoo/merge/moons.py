#!/usr/bin/python3

# Context -> (can we even tweak this? ideally we don't have it reading from args or env directly, so we can!)
#   Configuration ->
#     Entry Point (can tweak configuration) ->
#       Model (gets config) ->
#         Initialization of subsystem (in process of entry point)
#                                |
#                                \ subpop should make entry points accessible by other pieces of code, not just
#                                  from the command-line.
#                                  It can do this by having an explicit configuration pipeline rather than leaving
#                                  things to the setuptools entrypoint to do everything. So we want to model this in
#                                  code.
#                                  We should be able to mark subsystems as needing initialization or not.
#
#
# import dyne.org.funtoo.org.metatools.merge as merge
#
# config = {
#	"env" : None,
#	"user": None,
#	"config":
#       "main" : "~/.foo/bar"
#}

# one-stage launch:
# await hub.launch(merge, payload={"regen"}, config=None)
#
# Even without payloads, you need to launch, because that's how you provide config. The only way you wouldn't need to
# launch is if you don't have any config.
#
# two-stage launch:
#
# model = await hub.pre_launch(merge, payload={"regen"}, config)
# (tweak/interact with model)
# await merge.launch(model=model)
#
# orbit.model <-- the subsystem-specific hub? mapped into namespace?
# orbit.foo

import os
from collections import defaultdict, OrderedDict
from configparser import ConfigParser
from datetime import datetime

import yaml

from metatools.tree import GitTree, AutoCreatedGitTree
from subpop.config import SubPopModel, ConfigurationError

# Components: fastpull: spider
#             regen. full tree regen?
#             autogen: a doit run
#             deepdive: deepdive querying

class Model(SubPopModel):

	config_files = {
		"merge": "~/.merge"
	}

	prod = False
	release = None
	push = False
	create_branches = False
	fastpull = None
	db = None

	_foundation_data = None
	_kit_groups = None
	_package_data_dict = {}
	_third_party_mirrors = None

	mirror_repos = False
	nest_kits = True
	git_class = AutoCreatedGitTree
	source_repos = {}

	# This is used to grab a reference to the eclasses in core kit during regen:
	eclass_root = None
	eclass_hashes = None

	kit_results = OrderedDict()
	current_source_def = None

	config: ConfigParser = None
	start_time: datetime = None

	async def initialize(self, prod=False, push=False, release=None, create_branches=False, fastpull=False):

		self.prod = prod
		self.push = push
		self.release = release
		self.create_branches = create_branches
		self.fastpull = True if self.prod else fastpull

		self.config = ConfigParser()
		self.config.read_string(self.get_file("merge"))

		if not self.prod:
			self.defaults = {
				"urls": {
					"auto": "https://code.funtoo.org/bitbucket/scm/auto",
					"indy": "https://code.funtoo.org/bitbucket/scm/indy",
					"mirror": "",
				},
				"sources": {
					"flora": "https://code.funtoo.org/bitbucket/scm/co/flora.git",
					"kit-fixups": "https://code.funtoo.org/bitbucket/scm/core/kit-fixups.git",
					"gentoo-staging": "https://code.funtoo.org/bitbucket/scm/auto/gentoo-staging.git",
				},
			}
		else:
			# In this mode, we're actually wanting to update real kits, and likely are going to push our updates to remotes (unless
			# --nopush is specified as an arg.) This might be used by people generating their own custom kits for use on other systems,
			# or by Funtoo itself for updating official kits and meta-repo.

			self.nest_kits = False
			self.push = push
			self.mirror_repos = push
			self.git_class = GitTree
			self.defaults = {
				"urls": {
					"auto": "ssh://git@code.funtoo.org:7999/auto",
					"indy": "ssh://git@code.funtoo.org:7999/indy",
					"mirror": "git@github.com:funtoo",
				},
				"sources": {
					"flora": "ssh://git@code.funtoo.org:7999/co/flora.git",
					"kit-fixups": "ssh://git@code.funtoo.org:7999/core/kit-fixups.git",
					"gentoo-staging": "ssh://git@code.funtoo.org:7999/auto/gentoo-staging.git",
				},
			}

		valids = {
			"main": ["features"],
			"paths": ["fastpull"],
			"sources": ["flora", "kit-fixups", "gentoo-staging"],
			"destinations": ["base_url", "mirror", "indy_url"],
			"branches": ["flora", "kit-fixups", "meta-repo"],
			"work": ["source", "destination", "metadata-cache"],
		}

		for section, my_valids in valids.items():
			if self.config.has_section(section):
				if section == "database":
					continue
				for opt in self.config[section]:
					if opt not in my_valids:
						raise ConfigurationError(f"Error: ~/.merge [{section}] option {opt} is invalid.")

		await self.initial_repo_setup()

	async def initial_repo_setup(self):
		self.meta_repo =self.git_class(
			name="meta-repo",
			branch=self.release,
			url=self.meta_repo_url if self.prod else None,
			root=self.dest_trees + "/meta-repo",
			origin_check=True if self.prod else None,
			mirror=self.mirror_url.rstrip("/") + "/meta-repo" if self.mirror_repos else False,
			create_branches=self.create_branches
		)

		self.start_time = datetime.utcnow()

		self.kit_fixups = GitTree(
			name="kit-fixups",
			branch=self.branch("kit-fixups"),
			url=self.kit_fixups_url,
			root=self.source_trees + "/kit-fixups",
			checkout_all_branches=False,
		)

		self.meta_repo.initialize()
		self.kit_fixups.initialize()

		if not self.release_exists(self.release):
			raise ConfigurationError(f"Release not found: {self.release}")

	# TODO: this should be added to start of regen run:
	#merge.metadata.cleanup_error_logs()

	@property
	def third_party_mirrors(self):
		if not self._third_party_mirrors:
			mirr_dict = {}
			with open(os.path.join(self.meta_repo.root, "profiles/core-kit/curated/thirdpartymirrors"), "r") as f:
				lines = f.readlines()
				for line in lines:
					ls = line.split()
					mirr_dict[ls[0]] = ls[1:]
			self._third_party_mirrors = mirr_dict
		return self._third_party_mirrors

	@property
	def foundation_data(self):
		if self._foundation_data is None:
			with open(os.path.join(self.kit_fixups.root, "foundations.yaml"), "r") as f:
				self._foundation_data = yaml.safe_load(f)
		return self._foundation_data

	def release_exists(self, release):
		for release_dict in self.foundation_data["kit-groups"]["releases"]:
			cur_release = list(release_dict.keys())[0]
			if cur_release == release:
				return True
		return False

	@property
	def release_info(self):
		release_out = {}
		fdata = self.foundation_data
		for release_dict in fdata["metadata"]:
			release = list(release_dict.keys())[0]
			if release != self.release:
				continue
			release_info = release_dict[release]
			# We now need to de-listify any lists
			for key, val in release_info.items():
				if not isinstance(val, list):
					release_out[key] = val
				else:
					release_out[key] = val[0]
			break
		return release_out

	@property
	def kit_groups(self):
		if self._kit_groups is None:
			self._kit_groups = list(self._gen_kit_groups())
		return self._kit_groups

	def _gen_kit_groups(self):
		fdata = self.foundation_data
		defaults = fdata["kit-groups"]["defaults"] if "defaults" in fdata["kit-groups"] else {}
		for release_dict in fdata["kit-groups"]["releases"]:

			# unbundle from singleton dict:
			release = list(release_dict.keys())[0]
			release_data = release_dict[release]

			if release != self.release:
				continue

			for kg in release_data:
				out = defaults.copy()
				if isinstance(kg, str):
					out["name"] = kg
				elif isinstance(kg, dict):
					out["name"] = list(kg.keys())[0]
					out.update(list(kg.values())[0])
				yield out
			break

	def source_defs(self, name):
		for sdef in self.foundation_data["source-defs"]:
			sdef_name = list(sdef.keys())[0]
			if sdef_name != name:
				continue
			sdef_data = list(sdef.values())[0]
			for sdef_entry in sdef_data:
				yield sdef_entry

	def get_overlay(self, name):
		"""
		Gets data on a specific overlay
		"""
		for ov_dict in self.foundation_data["overlays"]:

			if isinstance(ov_dict, str):
				ov_name = ov_dict
				ov_data = {"name": ov_name}
			else:
				ov_name = list(ov_dict.keys())[0]
				if ov_name != name:
					continue
				ov_data = list(ov_dict.values())[0]
				ov_data["name"] = ov_name

			if ov_name != name:
				continue

			url = self.get_option("sources", ov_name)
			if url is not None:
				ov_data["url"] = url

			if "url" not in ov_data:
				raise IndexError(f"No url found for overlay {name}")

			return ov_data
		raise IndexError(f"overlay not found: {name}")

	def get_repos(self, source_name):
		"""
		Given a source definition, return a list of repositories with all data included (like urls
		from the source definitions, etc.)
		"""

		sdefs = self.source_defs(source_name)

		for repo_dict in sdefs:
			if isinstance(repo_dict, str):
				repo_dict = {"repo": repo_dict}
			ov_name = repo_dict["repo"]
			ov_data = self.get_overlay(ov_name)
			repo_dict.update(ov_data)

			if "src_sha1" not in repo_dict:
				branch = self.get_option("branches", ov_name)
				if branch is not None:
					repo_dict["branch"] = branch
				else:
					repo_dict["branch"] = "master"
			yield repo_dict

	def get_package_data(self, ctx):
		key = f"{ctx.kit_name}/{ctx.kit_branch}"
		if key not in self._package_data_dict:
			# Try to use branch-specific packages.yaml if it exists. Fall back to global kit-specific YAML:
			fn = f"{self.kit_fixups.root}/{key}/packages.yaml"
			if not os.path.exists(fn):
				fn = f"{self.kit_fixups.root}/{ctx.kit.name}/packages.yaml"
			with open(fn, "r") as f:
				self._package_data_dict[key] = yaml.safe_load(f)
		return self._package_data_dict[key]

	def get_kit_items(self, ctx, section="packages"):
		pdata = self.get_package_data(ctx)
		if section in pdata:
			for package_set in pdata[section]:
				repo_name = list(package_set.keys())[0]
				packages = package_set[repo_name]
				yield repo_name, packages

	def get_kit_packages(self, ctx):
		return self.get_kit_items(ctx)

	def python_kit_settings(self):
		for section in self.foundation_data["python-settings"]:
			release = list(section.keys())[0]
			if release != self.release:
				continue
			return section[release][0]
		return None

	def get_excludes_from_yaml(self, ctx):
		"""
		Grabs the excludes: section from packages.yaml, which is used to remove stuff from the resultant
		kit that accidentally got copied by merge scripts (due to a directory looking like an ebuild
		directory, for example.)
		"""
		pdata = self.get_package_data(ctx)
		if "exclude" in pdata:
			return pdata["exclude"]
		else:
			return []

	def get_copyfiles(self, ctx):
		"""
		Parses the 'eclasses' and 'copyfiles' sections in a kit's YAML and returns a list of files to
		copy from each source repository in a tuple format.
		"""
		eclass_items = list(self.get_kit_items(ctx, section="eclasses"))
		copyfile_items = list(self.get_kit_items(ctx, section="copyfiles"))
		copy_tuple_dict = defaultdict(list)

		for src_repo, eclasses in eclass_items:
			for eclass in eclasses:
				copy_tuple_dict[src_repo].append((f"eclass/{eclass}.eclass", f"eclass/{eclass}.eclass"))

		for src_repo, copyfiles in copyfile_items:
			for copy_dict in copyfiles:
				copy_tuple_dict[src_repo].append((copy_dict["src"], copy_dict["dest"] if "dest" in copy_dict else copy_dict["src"]))
		return copy_tuple_dict

	def get_option(self, section, key, default=None):
		if self.config.has_section(section) and key in self.config[section]:
			my_path = self.config[section][key]
		elif section in self.defaults and key in self.defaults[section]:
			my_path = self.defaults[section][key]
		else:
			my_path = default
		return my_path

	@property
	def flora(self):
		return self.get_option("sources", "flora")

	@property
	def kit_fixups_url(self):
		return self.get_option("sources", "kit-fixups")

	@property
	def meta_repo_url(self):
		return self.url("meta-repo")

	@property
	def mirror_url(self):
		return self.get_option("urls", "mirror", default=False)

	@property
	def gentoo_staging(self):
		return self.get_option("sources", "gentoo-staging")

	def url(self, repo, kind="auto"):
		base = self.get_option("urls", kind)
		if not base.endswith("/"):
			base += "/"
		if not repo.endswith(".git"):
			repo += ".git"
		return base + repo

	def branch(self, key):
		return self.get_option("branches", key, default="master")

	@property
	def work_path(self):
		home = self.home()
		if home:
			return os.path.join(home, "repo_tmp")
		else:
			return "/var/tmp/repo_tmp"

	@property
	def temp_path(self):
		"""
		merge-kits may run multiple 'doit's in parallel. In this case, we probably want to segregate their temp
		paths. We can do this by having a special option passed to doit which can in turn tweak the Configuration
		object to create unique sub-paths here.
		This is TODO item!
		"""
		home = self.home()
		if home:
			return os.path.join(home, "repo_tmp/tmp")
		else:
			return "/var/tmp/repo_tmp/tmp"

	@property
	def fastpull_path(self):
		"""
		In theory, multiple fastpull hooks could try to link the same file into the same fastpull location at
		the same time resulting in a code failure.

		Possibly, we could have a 'staging' fastpull for each 'doit' call, and the master merge-kits process
		could look in this area and move files into its main fastpull db from its main process rather than
		relying on each 'doit' process to take care of it.

		Maybe this only happens when 'doit' is run as part of merge-kits. When run separately, 'doit' would
		populate the main fastpull db itself.

		In any case, some resiliency in the code for multiple creation of the same symlink (and thus symlink
		creation failure) would be a good idea.

		"""
		fp_path = self.get_option("paths", "fastpull")
		if fp_path is None:
			return os.path.join(self.work_path, "fastpull")
		return fp_path

	@property
	def metadata_cache(self):
		return os.path.join(self.work_path, "metadata-cache")

	@property
	def source_trees(self):
		return os.path.join(self.work_path, "source-trees")

	@property
	def dest_trees(self):
		return os.path.join(self.work_path, "dest-trees")

	@property
	def kit_dest(self):
		if self.prod:
			return self.dest_trees
		else:
			return os.path.join(self.dest_trees, "meta-repo/kits")

	@property
	def fastpull_enabled(self):
		# If set via constructor, we use that. Otherwise, read from config.
		if self.fastpull is not None:
			return self.fastpull
		features = self.get_option("main", "features", "")
		f_split = features.split()
		if "fastpull" in f_split:
			return True
		else:
			return False

	@property
	def fetch_download_path(self):
		return os.path.join(self.work_path, "fetch")


async def moon(model):
	return Moon(model)

class Moon:
	def __init__(self, model):
		pass



