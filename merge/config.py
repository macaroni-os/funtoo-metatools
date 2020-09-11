#!/usr/bin/python3

import os
import sys
from configparser import ConfigParser


class Configuration:
	def __init__(self, path=None):
		if path is None:
			home_dir = os.path.expanduser("~")
			self.config_path = os.path.join(home_dir, ".merge")
		else:
			self.config_path = path
		if not os.path.exists(self.config_path):
			print(
				"""
Merge scripts now use a configuration file. Create a ~/.merge file with the following format. Note that
while the config file must exist, it may be empty, in which case, the following settings will be used.
These are the recommended 'starter' settings for use as an individual developer:

[sources]

flora = https://code.funtoo.org/bitbucket/scm/co/flora.git
kit-fixups = https://code.funtoo.org/bitbucket/scm/core/kit-fixups.git
gentoo-staging = https://code.funtoo.org/bitbucket/scm/auto/gentoo-staging.git

[branches]

flora = master
kit-fixups = master
meta-repo = master


"""
			)
			sys.exit(1)
		self.defaults = {"sources": {"flora": "ssh://git@code.funtoo.org:7999/co/flora.git"}}
		self.config = ConfigParser()
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
			my_path = None
		return my_path

	def db_connection(self, dbname):
		return self.get_option("database", dbname)

	@property
	def flora(self):
		return self.get_option("sources", "flora", "ssh://git@code.funtoo.org:7999/co/flora.git")

	@property
	def kit_fixups(self):
		return self.get_option("sources", "kit-fixups", "ssh://git@code.funtoo.org:7999/core/kit-fixups.git")

	@property
	def mirror(self):
		if self.args.nomirror is True:
			return None
		else:
			return self.get_option("destinations", "mirror", None)

	@property
	def gentoo_staging(self):
		return self.get_option("sources", "gentoo-staging", "ssh://git@code.funtoo.org:7999/auto/gentoo-staging.git")

	def base_url(self, repo):
		base = self.get_option("destinations", "base_url", "ssh://git@code.funtoo.org:7999/auto/")
		if not base.endswith("/"):
			base += "/"
		if not repo.endswith(".git"):
			repo += ".git"
		return base + repo

	def indy_url(self, repo):
		base = self.get_option("destinations", "indy_url", "ssh://git@code.funtoo.org:7999/indy/")
		if not base.endswith("/"):
			base += "/"
		if not repo.endswith(".git"):
			repo += ".git"
		return base + repo

	def branch(self, key):
		return self.get_option("branches", key, "master")

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
		if self.args and self.args.prod:
			return self.dest_trees
		else:
			return os.path.join(self.dest_trees, "meta-repo/kits")
