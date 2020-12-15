#!/usr/bin/env python3
import json
import os
import sys
from collections import defaultdict

from merge_utils.steps import (
	InsertFilesFromSubdir,
	SyncDir,
	SyncFiles,
	InsertEbuilds,
	CleanTree,
	CopyFiles,
	PruneLicenses,
	ELTSymlinkWorkaround,
	CreateCategories,
	GenPythonUse,
	Minify,
	GenCache,
	RemoveFiles,
	FindAndRemove,
)
from merge_utils.tree import GitTree, runShell, headSHA1


def copy_from_fixups_steps(hub, ctx):

	# Phase 3: copy eclasses, licenses, profile info, and ebuild/eclass fixups from the kit-fixups repository.

	# First, we are going to process the kit-fixups repository and look for ebuilds and eclasses to replace. Eclasses can be
	# overridden by using the following paths inside kit-fixups:

	# kit-fixups/eclass/1.2-release <--------- global eclasses, get installed to all kits unconditionally for release (overrides those above)
	# kit-fixups/<kit>/global/eclass <-------- global eclasses for a particular kit, goes in all branches (overrides those above)
	# kit-fixups/<kit>/global/profiles <------ global profile info for a particular kit, goes in all branches (overrides those above)
	# kit-fixups/<kit>/<branch>/eclass <------ eclasses to install in just a specific branch of a specific kit (overrides those above)
	# kit-fixups/<kit>/<branch>/profiles <---- profile info to install in just a specific branch of a specific kit (overrides those above)

	# Note that profile repo_name and categories files are excluded from any copying.

	# Ebuilds can be installed to kits by putting them in the following location(s):

	# kit-fixups/<kit>/global/cat/pkg <------- install cat/pkg into all branches of a particular kit
	# kit-fixups/<kit>/<branch>/cat/pkg <----- install cat/pkg into a particular branch of a kit

	# Remember that at this point, we may be missing a lot of eclasses and licenses from Gentoo. We will then perform a final sweep
	# of all catpkgs in the dest_kit and auto-detect missing eclasses from Gentoo and copy them to our dest_kit. Remember that if you
	# need a custom eclass from a third-party overlay, you will need to specify it in the overlay's overlays["ov_name"]["eclasses"]
	# list. Or alternatively you can copy the eclasses you need to kit-fixups and maintain them there :)

	steps = []
	# Here is the core logic that copies all the fix-ups from kit-fixups (eclasses and ebuilds) into place:
	eclass_release_path = "eclass/%s" % hub.RELEASE
	if os.path.exists(os.path.join(hub.FIXUP_REPO.root, eclass_release_path)):
		steps += [SyncDir(hub.FIXUP_REPO.root, eclass_release_path, "eclass")]
	fixup_dirs = ["global", "curated", ctx.kit.branch]
	for fixup_dir in fixup_dirs:
		fixup_path = ctx.kit.name + "/" + fixup_dir
		if os.path.exists(hub.FIXUP_REPO.root + "/" + fixup_path):
			if os.path.exists(hub.FIXUP_REPO.root + "/" + fixup_path + "/eclass"):
				steps += [
					InsertFilesFromSubdir(hub.FIXUP_REPO, "eclass", ".eclass", select="all", skip=None, src_offset=fixup_path)
				]
			if os.path.exists(hub.FIXUP_REPO.root + "/" + fixup_path + "/licenses"):
				steps += [InsertFilesFromSubdir(hub.FIXUP_REPO, "licenses", None, select="all", skip=None, src_offset=fixup_path)]
			if os.path.exists(hub.FIXUP_REPO.root + "/" + fixup_path + "/profiles"):
				steps += [
					InsertFilesFromSubdir(
						hub.FIXUP_REPO, "profiles", None, select="all", skip=["repo_name", "categories"], src_offset=fixup_path
					)
				]
			# copy appropriate kit readme into place:
			readme_path = fixup_path + "/README.rst"
			if os.path.exists(hub.FIXUP_REPO.root + "/" + readme_path):
				steps += [SyncFiles(hub.FIXUP_REPO.root, {readme_path: "README.rst"})]

			# We now add a step to insert the fixups, and we want to record them as being copied so successive kits
			# don't get this particular catpkg. Assume we may not have all these catpkgs listed in our package-set
			# file...

			steps += [InsertEbuilds(hub, hub.FIXUP_REPO, ebuildloc=fixup_path, select="all", skip=None, replace=True)]
	return steps


async def get_deepdive_kit_items(hub, ctx):

	"""
	This function will read on-disk metadata for a particular kit, and process it, splitting it into individual
	records for performing a bulk insert into MongoDB, for example. It will return a big collection of dicts
	in a list, ready for insertion. As part of this scan, Manifest data will be read from disk and hashes will
	be added to each record.

	We use this after a kit has been generated. We then grab the JSON of the metadata cache and prep it for
	writing into MongoDB.
	"""

	repo_obj = await checkout_kit(hub, ctx, pull=False)

	# load on-disk JSON metadata cache into memory:
	hub.cache.metadata.fetch_kit(repo_obj)

	bulk_insert = []
	head_sha1 = headSHA1(repo_obj.root)
	# Grab our fancy JSON record containing lots of kit information and prep it for insertion into MongoDB:
	try:
		for atom, json_data in repo_obj.KIT_CACHE.items():
			json_data["commit"] = head_sha1
			sys.stdout.write(".")
			sys.stdout.flush()
			bulk_insert.append(json_data)
	except KeyError as ke:
		print(f"Encountered error when processing {ctx.kit.name} {ctx.kit.branch}")
		raise ke
	hub.cache.metadata.flush_kit(repo_obj, save=False)
	print(f"Got {len(bulk_insert)} items to bulk insert for {ctx.kit.name} branch {ctx.kit.branch}.")
	return ctx, bulk_insert


async def checkout_kit(hub, ctx, pull=None):

	kind = ctx.kit.kind
	branch = ctx.kit.branch
	kwargs = {}

	if kind == "independent":
		# For independent kits, we must clone the source tree
		git_class = GitTree
		kwargs["url"] = hub.MERGE_CONFIG.url(ctx.kit.name, kind="indy")
		if not getattr(hub, "PROD", False):
			# If generating indy kits locally, the indy kit was sourced from the Internet, so it's not an
			# AutoCreatedGitTree (we had to pull it.) But it will diverge from upstream. So we can't really
			# keep pulling in upstream changes:
			kwargs["pull"] = False
		else:
			kwargs["pull"] = True
	else:
		# For auto-generated kits, if we are in 'dev mode' then simply create a Tree from scratch.
		git_class = getattr(hub, "GIT_CLASS", GitTree)
		kwargs["url"] = hub.MERGE_CONFIG.url(ctx.kit.name, kind="auto")

	# Allow overriding of pull behavior.
	if pull is not None:
		kwargs["pull"] = pull

	try:
		if hub.MIRROR:
			kwargs["mirror"] = hub.MERGE_CONFIG.mirror.rstrip("/") + "/" + ctx.kit.name
	except AttributeError:
		pass

	if getattr(hub, "NEST_KITS", True):
		root = os.path.join(hub.MERGE_CONFIG.dest_trees, "meta-repo/kits", ctx.kit.name)
	else:
		root = os.path.join(hub.MERGE_CONFIG.dest_trees, ctx.kit.name)

	out_tree = git_class(hub, ctx.kit.name, branch=branch, root=root, **kwargs)
	out_tree.initialize()
	return out_tree


async def generate_kit(hub, ctx):

	"""

	This function will auto-generate a single 'autogenerated' kit by checking out the current version, wiping the
	contents of the git repo, and copying everything over again, updating metadata cache, etc. and then committing (and
	possibly pushing) the result.

	It will also work for 'independent' kits but will simply re-generate the metadata cache and ensure proper
	housekeeping is done.

	'ctx' is a NamespaceDict which contains the kit dictionary at `ctx.kit`.

	"""

	out_tree = await checkout_kit(hub, ctx)

	# load on-disk JSON metadata cache into memory:
	hub.cache.metadata.fetch_kit(out_tree)

	steps = []

	if ctx.kit.kind == "independent":
		steps += [RemoveFiles(["metadata/md5-cache"])]
	elif ctx.kit.kind == "autogenerated":
		steps += [CleanTree()]

		pre_steps, post_steps = hub.merge.foundations.get_kit_pre_post_steps(ctx)

		if pre_steps is not None:
			steps += pre_steps

		# Copy files specified in 'eclasses' and 'copyfiles' sections in the kit's YAML:
		for repo_name, copyfile_tuples in hub.merge.foundations.get_copyfiles_from_yaml(ctx).items():
			steps += [CopyFiles(hub.SOURCE_REPOS[repo_name], copyfile_tuples)]

		# Copy over catpkgs listed in 'packages' section:

		for repo_name, packages in hub.merge.foundations.get_kit_packages(ctx):
			from_tree = hub.SOURCE_REPOS[repo_name]
			# TODO: add move maps below
			steps += [InsertEbuilds(hub, from_tree, skip=None, replace=True, move_maps=None, select=packages)]

		# If an autogenerated kit, we also want to copy various things (catpkgs, eclasses, profiles) from kit-fixups:
		steps += copy_from_fixups_steps(hub, ctx)
		steps += [
			RemoveFiles(hub.merge.foundations.get_excludes_from_yaml(ctx)),
			FindAndRemove(["__pycache__"]),
		] + post_steps

	steps += [
		Minify(),
		ELTSymlinkWorkaround(),
		CreateCategories(),
		SyncDir(hub.SOURCE_REPOS["gentoo-staging"].root, "licenses"),
	]

	await out_tree.run(steps)

	# Now, if we are core-kit, get hashes of all the eclasses so that we can generate metadata cache and use
	# it as needed:

	if ctx.kit.name == "core-kit":
		hub.ECLASS_ROOT = out_tree.root
		hub.ECLASS_HASHES = hub.merge.metadata.get_eclass_hashes(hub.ECLASS_ROOT)

	# We will execute all the steps that we have queued up to this point, which will result in out_tree.KIT_CACHE
	# being populated with all the metadata from the kit. Which will allow the next steps to run successfully.

	await out_tree.run([GenCache()])

	meta_steps = [PruneLicenses()]

	python_settings = hub.merge.foundations.python_kit_settings()

	for py_branch, py_settings in python_settings.items():
		meta_steps += [GenPythonUse(hub, py_settings, "funtoo/kits/python-kit/%s" % py_branch)]

	# We can now run all the steps that require access to metadata:

	await out_tree.run(meta_steps)

	if ctx.kit.kind == "independent":
		update_msg = "Automated updates by metatools for md5-cache and python profile settings."
	else:
		update_msg = "Autogenerated tree updates."

	out_tree.gitCommit(message=update_msg, push=hub.PUSH)

	# save in-memory metadata cache to JSON:
	hub.cache.metadata.flush_kit(out_tree)

	return ctx, out_tree, out_tree.head()


def generate_metarepo_metadata(hub, output_sha1s):
	"""
	Generates the metadata in /var/git/meta-repo/metadata/...
	:param release: the release string, like "1.3-release".
	:param hub.META_REPO: the meta-repo GitTree.
	:return: None.
	"""

	if not os.path.exists(hub.META_REPO.root + "/metadata"):
		os.makedirs(hub.META_REPO.root + "/metadata")

	with open(hub.META_REPO.root + "/metadata/kit-sha1.json", "w") as a:
		a.write(json.dumps(output_sha1s, sort_keys=True, indent=4, ensure_ascii=False))

	outf = hub.META_REPO.root + "/metadata/kit-info.json"
	all_kit_names = sorted(output_sha1s.keys())

	with open(outf, "w") as a:
		k_info = {}
		out_settings = defaultdict(lambda: defaultdict(dict))
		for kit_dict in hub.KIT_GROUPS:
			kit_name = kit_dict["name"]
			# specific keywords that can be set for each branch to identify its current quality level
			out_settings[kit_name]["stability"][kit_dict["branch"]] = kit_dict["stability"]
			kind = kit_dict["kind"]
			if kind == "autogenerated":
				kind_json = "auto"
			elif kind == "independent":
				kind_json = "indy"
			else:
				raise ValueError(f"For kit {kit_name}: Kit type of {kind} not recognized.")
			out_settings[kit_name]["type"] = kind_json
		k_info["kit_order"] = all_kit_names
		k_info["kit_settings"] = out_settings

		# auto-generate release-defs. We used to define them manually in foundation:
		rdefs = {}
		for kit_name in all_kit_names:
			rdefs[kit_name] = []
			for def_kit in filter(lambda x: x["name"] == kit_name and x["stability"] not in ["deprecated"], hub.KIT_GROUPS):
				rdefs[kit_name].append(def_kit["branch"])

		rel_info = hub.merge.foundations.release_info()

		k_info["release_defs"] = rdefs
		k_info["release_info"] = rel_info
		a.write(json.dumps(k_info, sort_keys=True, indent=4, ensure_ascii=False))

	with open(hub.META_REPO.root + "/metadata/version.json", "w") as a:
		a.write(json.dumps(rel_info, sort_keys=True, indent=4, ensure_ascii=False))


def mirror_repository(hub, repo_obj):
	"""
	Mirror a repository to its mirror location, ie. GitHub.
	"""
	base_path = os.path.join(hub.MERGE_CONFIG.temp_path, "mirror_repos")
	os.makedirs(base_path, exist_ok=True)
	runShell(f"git clone --bare {repo_obj.root} {base_path}/{repo_obj.name}.pushme")
	runShell(
		f"cd {base_path}/{repo_obj.name}.pushme && git remote add upstream {repo_obj.mirror} && git push --mirror upstream"
	)
	runShell(f"rm -rf {base_path}/{repo_obj.name}.pushme")
	return repo_obj.name
