import logging
import os
import threading
from datetime import datetime

from metatools.config.base import MinimalConfig
from metatools.context import GitRepositoryLocator
from metatools.files.release import ReleaseYAML
from metatools.hashutils import get_md5
from metatools.pretty_logging import TornadoPrettyLogFormatter
from metatools.tree import AutoCreatedGitTree, GitTree


class MergeConfig(MinimalConfig):
	"""
	This configuration is used for tree regen, also known as 'merge-kits'.
	"""

	# Configuration bits:

	release_yaml = None
	context = None
	locator = None
	meta_repo = None
	prod = False
	release = None
	push = False
	create_branches = False
	mirror_repos = False
	nest_kits = True
	git_class = AutoCreatedGitTree

	# Not sure if this is used:
	_third_party_mirrors = None

	# Things used during runtime processing:
	kit_fixups: GitTree = None
	metadata_error_stats = []
	processing_error_stats = []
	start_time: datetime = None
	current_source_def = None
	log = None

	async def initialize(self, prod=False, push=False, release=None, create_branches=False):

		self.log = logging.getLogger('metatools.merge')
		self.log.propagate = False
		self.log.setLevel(logging.INFO)
		channel = logging.StreamHandler()
		channel.setFormatter(TornadoPrettyLogFormatter())
		self.log.addHandler(channel)

		self.prod = prod
		self.push = push
		self.release = release
		self.create_branches = create_branches

		# Locate the root of the git repository we're currently in. We assume this is kit-fixups:
		self.locator = GitRepositoryLocator()
		self.context = self.locator.root

		# Next, find release.yaml in the proper directory in kit-fixups.

		self.release_yaml = ReleaseYAML(self.locator, mode="prod" if prod else "dev", release=release)
		self.kit_fixups = GitTree(name='kit-fixups', root=self.release_yaml.locator.root, model=self)

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

	@property
	def metadata_cache(self):
		return os.path.join(self.work_path, "metadata-cache")

	@property
	def source_trees(self):
		return os.path.join(self.work_path, "source-trees")

	@property
	def dest_trees(self):
		return os.path.join(self.work_path, "dest-trees")


