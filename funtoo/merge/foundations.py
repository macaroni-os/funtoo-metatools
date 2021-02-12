#!/usr/bin/env python3

from collections import defaultdict
import yaml
import os

import dyne.org.funtoo.metatools.merge as merge


def get_kit_pre_post_steps(ctx):
	kit_steps = {
		"core-kit": {
			"pre": [
				merge.steps.GenerateRepoMetadata("core-kit", aliases=["gentoo"], priority=1000),
				# core-kit has special logic for eclasses -- we want all of them, so that third-party overlays can reference the full set.
				# All other kits use alternate logic (not in kit_steps) to only grab the eclasses they actually use.
				merge.steps.SyncDir(merge.model.SOURCE_REPOS["gentoo-staging"].root, "eclass"),
			],
			"post": [
				merge.steps.ThirdPartyMirrors(),
				merge.steps.RunSed(["profiles/base/make.defaults"], ["/^PYTHON_TARGETS=/d", "/^PYTHON_SINGLE_TARGET=/d"]),
			],
		},
		# masters of core-kit for regular kits and nokit ensure that masking settings set in core-kit for catpkgs in other kits are applied
		# to the other kits. Without this, mask settings in core-kit apply to core-kit only.
		"regular-kits": {
			"pre": [
				merge.steps.GenerateRepoMetadata(ctx.kit.name, masters=["core-kit"], priority=500),
			]
		},
		"all-kits": {
			"pre": [
				merge.steps.SyncFiles(
					merge.model.FIXUP_REPO.root,
					{
						"COPYRIGHT.txt": "COPYRIGHT.txt",
						"LICENSE.txt": "LICENSE.txt",
					},
				),
			]
		},
		"nokit": {
			"pre": [
				merge.steps.GenerateRepoMetadata("nokit", masters=["core-kit"], priority=-2000),
			]
		},
	}

	out_pre_steps = []
	out_post_steps = []

	kd = ctx.kit.name
	if kd in kit_steps:
		if "pre" in kit_steps[kd]:
			out_pre_steps += kit_steps[kd]["pre"]
		if "post" in kit_steps[kd]:
			out_post_steps += kit_steps[kd]["post"]

	# a 'regular kit' is not core-kit or nokit -- if we have pre or post steps for them, append these steps:
	if kd not in ["core-kit", "nokit"] and "regular-kits" in kit_steps:
		if "pre" in kit_steps["regular-kits"]:
			out_pre_steps += kit_steps["regular-kits"]["pre"]
		if "post" in kit_steps["regular-kits"]:
			out_post_steps += kit_steps["regular-kits"]["post"]

	if "all-kits" in kit_steps:
		if "pre" in kit_steps["all-kits"]:
			out_pre_steps += kit_steps["all-kits"]["pre"]
		if "post" in kit_steps["all-kits"]:
			out_post_steps += kit_steps["all-kits"]["post"]

	return out_pre_steps, out_post_steps


def grab_fdata():
	if merge.model.FDATA is None:
		with open(os.path.join(merge.model.FIXUP_REPO.root, "foundations.yaml"), "r") as f:
			merge.model.FDATA = yaml.safe_load(f)


def grab_pdata(ctx):
	pdata = ctx.get("PDATA", None)
	if pdata is not None:
		# already loaded
		return
	# Try to use branch-specific packages.yaml if it exists. Fall back to global kit-specific YAML:
	fn = f"{merge.model.FIXUP_REPO.root}/{ctx.kit.name}/{ctx.kit.branch}/packages.yaml"
	if not os.path.exists(fn):
		fn = f"{merge.model.FIXUP_REPO.root}/{ctx.kit.name}/packages.yaml"
	with open(fn, "r") as f:
		ctx["PDATA"] = yaml.safe_load(f)


def get_kit_items(ctx, section="packages"):
	grab_pdata(ctx)
	if section in ctx.PDATA:
		for package_set in ctx.PDATA[section]:
			repo_name = list(package_set.keys())[0]
			packages = package_set[repo_name]
			yield repo_name, packages


def get_excludes_from_yaml(ctx):
	"""
	Grabs the excludes: section from packages.yaml, which is used to remove stuff from the resultant
	kit that accidentally got copied by merge scripts (due to a directory looking like an ebuild
	directory, for example.)
	"""
	grab_pdata(ctx)
	if "exclude" in ctx.PDATA:
		return ctx.PDATA["exclude"]
	else:
		return []


def get_copyfiles_from_yaml(ctx):
	"""
	Parses the 'eclasses' and 'copyfiles' sections in a kit's YAML and returns a list of files to
	copy from each source repository in a tuple format.
	"""
	eclass_items = list(get_kit_items(ctx, section="eclasses"))
	copyfile_items = list(get_kit_items(ctx, section="copyfiles"))
	copy_tuple_dict = defaultdict(list)

	for src_repo, eclasses in eclass_items:
		for eclass in eclasses:
			copy_tuple_dict[src_repo].append((f"eclass/{eclass}.eclass", f"eclass/{eclass}.eclass"))

	for src_repo, copyfiles in copyfile_items:
		for copy_dict in copyfiles:
			copy_tuple_dict[src_repo].append((copy_dict["src"], copy_dict["dest"] if "dest" in copy_dict else copy_dict["src"]))
	return copy_tuple_dict


def get_kit_packages(ctx):
	return get_kit_items(ctx)


def python_kit_settings():
	grab_fdata()
	for section in merge.model.FDATA["python-settings"]:
		release = list(section.keys())[0]
		if release != merge.model.RELEASE:
			continue
		return section[release][0]
	return None


def release_exists(release):
	grab_fdata()
	for release_dict in merge.model.FDATA["kit-groups"]["releases"]:
		cur_release = list(release_dict.keys())[0]
		if cur_release == release:
			return True
	return False


def kit_groups():
	grab_fdata()
	defaults = merge.model.FDATA["kit-groups"]["defaults"] if "defaults" in merge.model.FDATA["kit-groups"] else {}
	for release_dict in merge.model.FDATA["kit-groups"]["releases"]:

		# unbundle from singleton dict:
		release = list(release_dict.keys())[0]
		release_data = release_dict[release]

		if release != merge.model.RELEASE:
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


def source_defs(name):
	grab_fdata()
	for sdef in merge.model.FDATA["source-defs"]:
		sdef_name = list(sdef.keys())[0]
		if sdef_name != name:
			continue
		sdef_data = list(sdef.values())[0]
		for sdef_entry in sdef_data:
			yield sdef_entry


def get_overlay(name):
	"""
	Gets data on a specific overlay
	"""
	grab_fdata()
	for ov_dict in merge.model.FDATA["overlays"]:

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

		url = merge.model.MERGE_CONFIG.get_option("sources", ov_name)
		if url is not None:
			ov_data["url"] = url

		if "url" not in ov_data:
			raise IndexError(f"No url found for overlay {name}")

		return ov_data
	raise IndexError(f"overlay not found: {name}")


def get_repos(source_name):
	"""
	Given a source definition, return a list of repositories with all data included (like urls
	from the source definitions, etc.)
	"""

	sdefs = source_defs(source_name)

	for repo_dict in sdefs:
		if isinstance(repo_dict, str):
			repo_dict = {"repo": repo_dict}
		ov_name = repo_dict["repo"]
		ov_data = get_overlay(ov_name)
		repo_dict.update(ov_data)

		if "src_sha1" not in repo_dict:
			branch = merge.model.MERGE_CONFIG.get_option("branches", ov_name)
			if branch is not None:
				repo_dict["branch"] = branch
			else:
				repo_dict["branch"] = "master"
		yield repo_dict


def release_info():
	grab_fdata()
	release_out = {}
	for release_dict in merge.model.FDATA["metadata"]:
		release = list(release_dict.keys())[0]
		if release != merge.model.RELEASE:
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
