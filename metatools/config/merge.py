import os
import threading
from collections import defaultdict
from datetime import datetime

import yaml

from metatools.config.base import MinimalConfig
from metatools.context import GitRepositoryLocator
from metatools.files.release import ReleaseYAML
from metatools.hashutils import get_md5
from metatools.tree import AutoCreatedGitTree, GitTree
from subpop.config import ConfigurationError


class EClassHashCollector:

	LOCK = threading.Lock()
	# mapping eclass to source location:
	eclass_loc_dict = {}
	# mapping eclass to hash:
	eclass_hash_dict = {}

	"""
	When we are doing a merge run, we need to collect the hashes for all the eclasses in each kit. We also
	need to ensure that eclasses only appear once and are not duplicated (best practice, and not doing so
	creates problems with inconsistent behavior.) This class implements a cross-thread storage that can be
	used to record this information and identify when we have a duplicate eclass situation so we can print
	an informative error message.
	"""

	def add_eclasses(self, eclass_sourcedir: str):
		"""

		For generating metadata, we need md5 hashes of all eclasses for writing out into the metadata.

		This function grabs all the md5sums for all eclasses.
		"""

		ecrap = os.path.join(eclass_sourcedir, "eclass")
		if os.path.isdir(ecrap):
			for eclass in os.listdir(ecrap):
				if not eclass.endswith(".eclass"):
					continue
				eclass_path = os.path.join(ecrap, eclass)
				eclass_name = eclass[:-7]
				with self.LOCK:
					if eclass_name in self.eclass_loc_dict:
						raise KeyError(f"Eclass {eclass_name} in {eclass_path} is duplicated by {self.eclass_loc_dict[eclass_name]}. This should be fixed.")
					self.eclass_loc_dict[eclass_name] = eclass_path
					self.eclass_hash_dict[eclass_name] = get_md5(eclass_path)


class MergeConfig(MinimalConfig):
	"""
	This configuration is used for tree regen, also known as 'merge-kits'.
	"""

	release_yaml = None
	context = None
	locator = None
	meta_repo = None
	prod = False
	release = None
	push = False
	create_branches = False

	fastpull = None
	_third_party_mirrors = None

	mirror_repos = False
	nest_kits = True
	git_class = AutoCreatedGitTree

	metadata_error_stats = []
	processing_error_stats = []
	eclass_hashes = EClassHashCollector()
	start_time: datetime = None

	async def initialize(self, prod=False, push=False, release=None, create_branches=False):

		self.prod = prod
		self.push = push
		self.release = release
		self.create_branches = create_branches

		# Locate the root of the git repository we're currently in. We assume this is kit-fixups:
		self.locator = GitRepositoryLocator()
		self.context = self.locator.context

		# Next, find release.yaml in the proper directory in kit-fixups.

		self.release_yaml = ReleaseYAML(self.locator, mode="prod" if prod else "dev")

		# TODO: add a means to override the remotes in the release.yaml using a local config file.

		if not self.prod:
			# The ``push`` keyword argument only makes sense in prod mode. If not in prod mode, we don't push.
			self.push = False
		else:

			# In this mode, we're actually wanting to update real kits, and likely are going to push our updates to remotes (unless
			# --nopush is specified as an arg.) This might be used by people generating their own custom kits for use on other systems,
			# or by Funtoo itself for updating official kits and meta-repo.
			self.push = push
			self.nest_kits = False
			self.push = push
			self.mirror_repos = push
			self.git_class = GitTree

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

	@property
	def metadata_cache(self):
		return os.path.join(self.work_path, "metadata-cache")

	@property
	def source_trees(self):
		return os.path.join(self.work_path, "source-trees")

	@property
	def dest_trees(self):
		return os.path.join(self.work_path, "dest-trees")


