import os
from datetime import datetime

from metatools.release import ReleaseYAML
from metatools.config.base import MinimalConfig
from metatools.context import GitRepositoryLocator
from metatools.tree import AutoCreatedGitTree
from metatools.tree import GitTree

"""
This file contains classes used to create an object model for the contents of a releases/<release>.yaml file,
to more easily interact with the logical contents of this file without having to know the intricacies of the
actual file format.
"""


class MinimalMergeConfig(MinimalConfig):
	"""
	This configuration is for minimal tools that use merge-related data, like deepdive, for example.
	Deepdive can use this to access the release YAML without worrying about more complex data.
	"""

	# Configuration bits:
	prod = False
	release_yaml = None
	release = None
	context = None
	locator = None
	fixups_url = None
	fixups_branch = None
	# Things used during runtime processing:
	kit_fixups: GitTree = None
	logger_name = "metatools.merge"
	log = None
	debug = False

	async def initialize(self, release=None, fixups_url=None, fixups_branch=None, debug=False):
		await super().initialize(debug=debug)
		self.log.debug("Trying to find kit-fixups")
		# TODO: refuse to use any source repository that has local changes (use git status --porcelain | wc -l)
		self.context = os.path.join(self.source_trees, "kit-fixups")
		self.kit_fixups = GitTree(
			name='kit-fixups',
			root=self.context,
			model=self,
			url=fixups_url,
			branch=fixups_branch,
			keep_branch=True
		)
		self.log.debug("Initializing kit-fixups repository in model init")
		await self.kit_fixups.initialize()
		self.locator = GitRepositoryLocator(start_path=self.kit_fixups.root)
		self.release = release
		self.release_yaml = ReleaseYAML(release=self.release, prod=self.prod, kit_fixups=self.kit_fixups)


class MergeConfig(MinimalMergeConfig):
	"""
	This configuration is used for tree regen, also known as 'merge-kits'.
	"""

	meta_repo = None
	push = False
	create_branches = False
	mirror_repos = False
	nest_kits = True
	git_class = AutoCreatedGitTree
	git_kwargs = {}
	howdy = False

	# TODO: should probably review the error/warning stats variables here:
	metadata_error_stats = []
	processing_warning_stats = []
	processing_error_stats = []
	start_time: datetime = None
	current_source_def = None

	async def initialize(self, prod=False, push=False, release=None, create_branches=False, fixups_url=None,
						 fixups_branch=None, debug=False, howdy=False):

		self.prod = prod
		self.push = push
		self.create_branches = create_branches
		self.howdy = howdy

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
			self.mirror_repos = push
			self.git_class = GitTree
			self.git_kwargs = {"checkout_all_branches": True}

		await super().initialize(release=release, fixups_url=fixups_url, fixups_branch=fixups_branch, debug=debug)
		self.log.debug("Model initialization complete.")

# vim: ts=4 sw=4 noet
