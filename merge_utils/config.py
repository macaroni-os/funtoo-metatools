#!/usr/bin/python3

import os
import sys
from configparser import ConfigParser


class Configuration:
	def __init__(self, prod=False, path=None):
		self.prod = prod
		if path is None:
			home_dir = os.path.expanduser("~")
			self.config_path = os.path.join(home_dir, ".merge")
		else:
			self.config_path = path
		if not prod:
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
		self.config = ConfigParser()
		if os.path.exists(self.config_path):
			self.config.read(self.config_path)

		valids = {
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
						print("Error: ~/.merge [%s] option %s is invalid." % (section, opt))
						sys.exit(1)

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
	def kit_fixups(self):
		return self.get_option("sources", "kit-fixups")

	@property
	def meta_repo(self):
		return self.get_option("destinations", "meta-repo")

	@property
	def mirror(self):
		return self.get_option("urls", "mirror")

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
		if "HOME" in os.environ:
			return os.path.join(os.environ["HOME"], "repo_tmp")
		else:
			return "/var/tmp/repo_tmp"

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
