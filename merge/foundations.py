#!/usr/bin/env python3

import os
import yaml
from merge.config import Configuration


class Foundation:
	def __init__(self, hub, fixup_repo, config: Configuration = None, release=None):
		self.hub = hub
		self.fixup_repo = fixup_repo
		self.release = release
		self.config = config
		with open(os.path.join(fixup_repo.root, "foundations.yaml"), "r") as f:
			self.fdata = yaml.safe_load(f)

	def get_kit_packages(self, kit_name):
		print("GETTING SOME")
		fn = f"{self.fixup_repo.root}/{kit_name}/packages.yaml"
		with open(fn, "r") as f:
			print(f"Opened {fn}")
			self.pdata = yaml.safe_load(f)
			for package_set in self.pdata["packages"]:
				repo_name = list(package_set.keys())[0]
				packages = package_set[repo_name]
				yield repo_name, packages

	def kit_groups(self):
		defaults = self.fdata["kit-groups"]["defaults"] if "defaults" in self.fdata["kit-groups"] else {}
		for release_dict in self.fdata["kit-groups"]["releases"]:

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
		for sdef in self.fdata["source-defs"]:
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
		for ov_dict in self.fdata["overlays"]:

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

			url = self.hub.MERGE_CONFIG.get_option("sources", ov_name, None)
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
		source_defs = self.source_defs(source_name)
		for repo_dict in source_defs:
			ov_name = repo_dict["repo"]
			ov_data = self.get_overlay(ov_name)
			repo_dict.update(ov_data)

			if "src_sha1" not in repo_dict:
				branch = self.hub.MERGE_CONFIG.get_option("branches", ov_name, None)
				if branch is not None:
					repo_dict["branch"] = branch
				else:
					repo_dict["branch"] = "master"
			yield repo_dict
