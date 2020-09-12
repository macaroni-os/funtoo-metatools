#!/usr/bin/python3
import grp
import itertools
import multiprocessing
import re
import shutil
import sys

from merge.tree import runShell, GitTree


class MergeStep:

	# This is only used for Repository Steps:
	collector = None

	async def run(self, tree):
		pass


class ThirdPartyMirrors(MergeStep):
	"Add funtoo's distfiles mirror, and add funtoo's mirrors as gentoo back-ups."

	async def run(self, tree):
		orig = "%s/profiles/thirdpartymirrors" % tree.root
		new = "%s/profiles/thirdpartymirrors.new" % tree.root
		mirrors = "https://fastpull-us.funtoo.org/distfiles"
		a = open(orig, "r")
		b = open(new, "w")
		for line in a:
			ls = line.split()
			if len(ls) and ls[0] == "gentoo":
				b.write("gentoo\t" + ls[1] + " " + mirrors + " " + " ".join(ls[2:]) + "\n")
			else:
				b.write(line)
		b.write("funtoo %s\n" % mirrors)
		a.close()
		b.close()
		os.unlink(orig)
		os.link(new, orig)
		os.unlink(new)


class SyncDir(MergeStep):
	def __init__(self, srcroot, srcdir=None, destdir=None, exclude=None, delete=False):
		self.srcroot = srcroot
		self.srcdir = srcdir
		self.destdir = destdir
		self.exclude = exclude if exclude is not None else []
		self.delete = delete

	async def run(self, tree):
		if self.srcdir:
			src = os.path.join(self.srcroot, self.srcdir) + "/"
		else:
			src = os.path.normpath(self.srcroot) + "/"
		if self.destdir:
			dest = os.path.join(tree.root, self.destdir) + "/"
		else:
			if self.srcdir:
				dest = os.path.join(tree.root, self.srcdir) + "/"
			else:
				dest = os.path.normpath(tree.root) + "/"
		if not os.path.exists(dest):
			os.makedirs(dest)
		cmd = 'rsync -a --exclude CVS --exclude .svn --filter="hide /.git" --filter="protect /.git" '
		for e in self.exclude:
			cmd += "--exclude %s " % e
		if self.delete:
			cmd += "--delete --delete-excluded "
		cmd += "%s %s" % (src, dest)
		await runShell(cmd)


class GenerateRepoMetadata(MergeStep):
	def __init__(self, name, masters=None, aliases=None, priority=None):
		self.name = name
		self.aliases = aliases if aliases is not None else []
		self.masters = masters if masters is not None else []
		self.priority = priority

	async def run(self, tree):
		meta_path = os.path.join(tree.root, "metadata")
		if not os.path.exists(meta_path):
			os.makedirs(meta_path)
		a = open(meta_path + "/layout.conf", "w")
		out = (
			"""repo-name = %s
thin-manifests = true
sign-manifests = false
profile-formats = portage-2
cache-formats = md5-dict
"""
			% self.name
		)
		if self.aliases:
			out += "aliases = %s\n" % " ".join(self.aliases)
		if self.masters:
			out += "masters = %s\n" % " ".join(self.masters)
		a.write(out)
		a.close()
		rn_path = os.path.join(tree.root, "profiles")
		if not os.path.exists(rn_path):
			os.makedirs(rn_path)
		a = open(rn_path + "/repo_name", "w")
		a.write(self.name + "\n")
		a.close()


class RemoveFiles(MergeStep):
	def __init__(self, globs=None):
		if globs is None:
			globs = []
		self.globs = globs

	async def run(self, tree):
		for glob in self.globs:
			cmd = "rm -rf %s/%s" % (tree.root, glob)
			await runShell(cmd)


class CopyAndRename(MergeStep):
	def __init__(self, src, dest, ren_fun):
		self.src = src
		self.dest = dest
		# renaming function ... accepts source file path, and returns destination filename
		self.ren_fun = ren_fun

	async def run(self, tree):
		srcpath = os.path.join(tree.root, self.src)
		for f in os.listdir(srcpath):
			destfile = os.path.join(tree.root, self.dest)
			destfile = os.path.join(destfile, self.ren_fun(f))
			await runShell("( cp -a %s/%s %s )" % (srcpath, f, destfile))


class SyncFiles(MergeStep):
	def __init__(self, srcroot, files):
		self.srcroot = srcroot
		self.files = files
		if not isinstance(files, dict):
			raise TypeError("'files' argument should be a dict of source:destination items")

	async def run(self, tree):
		for src, dest in self.files.items():
			if dest is not None:
				dest = os.path.join(tree.root, dest)
			else:
				dest = os.path.join(tree.root, src)
			src = os.path.join(self.srcroot, src)
			if os.path.exists(dest):
				print("%s exists, attempting to unlink..." % dest)
				try:
					os.unlink(dest)
				except (IOError, PermissionError) as e:
					print("Unlinking failed: %s" % str(e))
					pass
			dest_dir = os.path.dirname(dest)
			if os.path.exists(dest_dir) and os.path.isfile(dest_dir):
				os.unlink(dest_dir)
			if not os.path.exists(dest_dir):
				os.makedirs(dest_dir)
			print("copying %s to final location %s" % (src, dest))
			shutil.copyfile(src, dest)


class CleanTree(MergeStep):
	# remove all files from tree, except dotfiles/dirs.

	def __init__(self, exclude=None):
		if exclude is None:
			exclude = []
		self.exclude = exclude

	async def run(self, tree):
		for fn in os.listdir(tree.root):
			if fn[:1] == ".":
				continue
			if fn in self.exclude:
				continue
			await runShell("rm -rf %s/%s" % (tree.root, fn))


class ELTSymlinkWorkaround(MergeStep):
	async def run(self, tree):
		dest = os.path.join(tree.root + "/eclass/ELT-patches")
		if not os.path.lexists(dest):
			os.makedirs(dest)


regextype = type(re.compile("hello, world"))


class InsertFilesFromSubdir(MergeStep):
	def __init__(self, srctree, subdir, suffixfilter=None, select="all", skip=None, src_offset=""):
		self.subdir = subdir
		self.suffixfilter = suffixfilter
		self.select = select
		self.srctree = srctree
		self.skip = skip
		self.src_offset = src_offset

	async def run(self, desttree):
		desttree.logTree(self.srctree)
		src = self.srctree.root
		if self.src_offset:
			src = os.path.join(src, self.src_offset)
		if self.subdir:
			src = os.path.join(src, self.subdir)
		if not os.path.exists(src):
			return
		dst = desttree.root
		if self.subdir:
			dst = os.path.join(dst, self.subdir)
		if not os.path.exists(dst):
			os.makedirs(dst)
		for e in os.listdir(src):
			if self.suffixfilter and not e.endswith(self.suffixfilter):
				continue
			if isinstance(self.select, list):
				if e not in self.select:
					continue
			elif isinstance(self.select, regextype):
				if not self.select.match(e):
					continue
			if isinstance(self.skip, list):
				if e in self.skip:
					continue
			elif isinstance(self.skip, regextype):
				if self.skip.match(e):
					continue
			real_dst = os.path.basename(os.path.join(dst, e))
			await runShell("cp -a %s/%s %s" % (src, e, dst))


class InsertEclasses(InsertFilesFromSubdir):
	def __init__(self, srctree, select="all", skip=None):
		InsertFilesFromSubdir.__init__(self, srctree, "eclass", ".eclass", select=select, skip=skip)


class InsertLicenses(InsertFilesFromSubdir):
	def __init__(self, srctree, select="all", skip=None):
		InsertFilesFromSubdir.__init__(self, srctree, "licenses", select=select, skip=skip)


class CreateCategories(MergeStep):
	async def run(self, desttree):
		catset = set()
		for maybe_cat in os.listdir(desttree.root):
			full_path = os.path.join(desttree.root, maybe_cat)
			if not os.path.isdir(full_path):
				continue
			if "-" in maybe_cat or maybe_cat == "virtual":
				catset.add(maybe_cat)
		if not os.path.exists(desttree.root + "/profiles"):
			os.makedirs(desttree.root + "/profiles")
		with open(desttree.root + "/profiles/categories", "w") as g:
			for cat in sorted(list(catset)):
				g.write(cat + "\n")


class ZapMatchingEbuilds(MergeStep):
	def __init__(self, srctree, select="all", branch=None):
		self.select = select
		self.srctree = srctree
		self.branch = branch

	async def run(self, desttree):
		if self.branch is not None:
			# Allow dynamic switching to different branches/commits to grab things we want:
			await self.srctree.gitCheckout(branch=self.branch)
		# Figure out what categories to process:
		dest_cat_path = os.path.join(desttree.root, "profiles/categories")
		if os.path.exists(dest_cat_path):
			with open(dest_cat_path, "r") as f:
				dest_cat_set = set(f.read().splitlines())
		else:
			dest_cat_set = set()

		# Our main loop:
		print("# Zapping builds from %s" % desttree.root)
		for cat in os.listdir(desttree.root):
			if cat not in dest_cat_set:
				continue
			src_catdir = os.path.join(self.srctree.root, cat)
			if not os.path.isdir(src_catdir):
				continue
			for src_pkg in os.listdir(src_catdir):
				dest_pkgdir = os.path.join(desttree.root, cat, src_pkg)
				if not os.path.exists(dest_pkgdir):
					# don't need to zap as it doesn't exist
					continue
				await runShell("rm -rf %s" % dest_pkgdir)


class RecordAllCatPkgs(MergeStep):
	"""
	This is used for non-auto-generated kits where we should record the catpkgs as belonging to a particular kit
	but perform no other action. A kit generation NO-OP, comparted to InsertEbuilds
	"""

	def __init__(self, hub, srctree: GitTree):
		self.srctree = srctree
		self.hub = hub

	async def run(self, desttree=None):
		for catpkg in self.srctree.getAllCatPkgs():
			self.hub.CPM_LOGGER.record(self.srctree.name, catpkg, is_fixup=False)


class InsertEbuilds(MergeStep):
	"""
	Insert ebuilds in source tre into destination tree.

	select: Ebuilds to copy over.
		By default, all ebuilds will be selected. This can be modified by setting select to a
		list of ebuilds to merge (specify by catpkg, as in "x11-apps/foo"). It is also possible
		to specify "x11-apps/*" to refer to all source ebuilds in a particular category.

	skip: Ebuilds to skip.
		By default, no ebuilds will be skipped. If you want to skip copying certain ebuilds,
		you can specify a list of ebuilds to skip. Skipping will remove additional ebuilds from
		the set of selected ebuilds. Specify ebuilds to skip using catpkg syntax, ie.
		"x11-apps/foo". It is also possible to specify "x11-apps/*" to skip all ebuilds in
		a particular category.

	replace: Ebuilds to replace.
		By default, if an catpkg dir already exists in the destination tree, it will not be overwritten.
		However, it is possible to change this behavior by setting replace to True, which means that
		all catpkgs should be overwritten. It is also possible to set replace to a list containing
		catpkgs that should be overwritten. Wildcards such as "x11-libs/*" will be respected as well.

	categories: Categories to process.
		categories to process for inserting ebuilds. Defaults to all categories in tree, using
		profiles/categories and all dirs with "-" in them and "virtuals" as sources.


	"""

	def __init__(
		self,
		hub,
		srctree: GitTree,
		select="all",
		select_only="all",
		skip=None,
		replace=False,
		categories=None,
		ebuildloc=None,
		move_maps: dict = None,
		skip_duplicates=True,
	):
		self.select = select
		self.skip = skip
		self.srctree = srctree
		self.replace = replace
		self.categories = categories
		self.hub = hub
		self.skip_duplicates = skip_duplicates
		if move_maps is None:
			self.move_maps = {}
		else:
			self.move_maps = move_maps
		if select_only is None:
			self.select_only = []
		else:
			self.select_only = select_only
		self.ebuildloc = ebuildloc

	def __repr__(self):
		return "<InsertEbuilds: %s>" % self.srctree.root

	async def run(self, desttree):

		if self.ebuildloc:
			srctree_root = self.srctree.root + "/" + self.ebuildloc
		else:
			srctree_root = self.srctree.root

		if self.srctree.should_autogen:
			await self.srctree.autogen(src_offset=self.ebuildloc)

		desttree.logTree(self.srctree)
		# Figure out what categories to process:
		src_cat_path = os.path.join(srctree_root, "profiles/categories")
		dest_cat_path = os.path.join(desttree.root, "profiles/categories")
		if self.categories is not None:
			# categories specified in __init__:
			src_cat_set = set(self.categories)
		else:
			src_cat_set = set()
			if os.path.exists(src_cat_path):
				# categories defined in profile:
				with open(src_cat_path, "r") as f:
					src_cat_set.update(f.read().splitlines())
			# auto-detect additional categories:
			cats = os.listdir(srctree_root)
			for cat in cats:
				# All categories have a "-" in them and are directories:
				if os.path.isdir(os.path.join(srctree_root, cat)):
					if "-" in cat or cat == "virtual":
						src_cat_set.add(cat)
		if os.path.exists(dest_cat_path):
			with open(dest_cat_path, "r") as f:
				dest_cat_set = set(f.read().splitlines())
		else:
			dest_cat_set = set()
		# Our main loop:
		print("# Merging in ebuilds from %s" % srctree_root)
		for cat in src_cat_set:
			catdir = os.path.join(srctree_root, cat)
			if not os.path.isdir(catdir):
				# not a valid category in source overlay, so skip it
				continue
			# runShell("install -d %s" % catdir)
			for pkg in os.listdir(catdir):
				catpkg = "%s/%s" % (cat, pkg)
				pkgdir = os.path.join(catdir, pkg)
				if self.select_only != "all" and catpkg not in self.select_only:
					# we don't want this catpkg
					continue
				if not os.path.isdir(pkgdir):
					# not a valid package dir in source overlay, so skip it
					continue
				if isinstance(self.select, list):
					if catpkg not in self.select:
						# we have a list of pkgs to merge, and this isn't on the list, so skip:
						continue
				elif isinstance(self.select, regextype):
					if not self.select.match(catpkg):
						# no regex match:
						continue
				if isinstance(self.skip, list):
					if catpkg in self.skip:
						# we have a list of pkgs to skip, and this catpkg is on the list, so skip:
						continue
				elif isinstance(self.skip, regextype):
					if self.select.match(catpkg):
						# regex skip match, continue
						continue
				dest_cat_set.add(cat)
				tpkgdir = None
				tcatpkg = None
				if catpkg in self.move_maps:
					if os.path.exists(pkgdir):
						# old package exists, so we'll want to rename.
						tcatpkg = self.move_maps[catpkg]
						tpkgdir = os.path.join(desttree.root, tcatpkg)
					else:
						tcatpkg = self.move_maps[catpkg]
						# old package doesn't exist, so we'll want to use the "new" pkgname as the source, hope it's there...
						pkgdir = os.path.join(srctree_root, tcatpkg)
						# and use new package name as destination...
						tpkgdir = os.path.join(desttree.root, tcatpkg)
				else:
					tpkgdir = os.path.join(desttree.root, catpkg)
				tcatdir = os.path.dirname(tpkgdir)
				copied = False
				if self.replace is True or (isinstance(self.replace, list) and (catpkg in self.replace)):
					if not os.path.exists(tcatdir):
						os.makedirs(tcatdir)
					if os.path.exists(tpkgdir):
						await runShell("rm -rf " + tpkgdir)
					await runShell(["/bin/cp", "-a", pkgdir, tpkgdir])
					copied = True
				else:
					if not os.path.exists(tpkgdir):
						copied = True
					if not os.path.exists(tcatdir):
						os.makedirs(tcatdir)
					if not os.path.exists(tpkgdir):
						await runShell(["/bin/cp", "-a", pkgdir, tpkgdir])
				if os.path.exists("%s/__pycache__" % tpkgdir):
					await runShell("rm -rf %s/__pycache__" % tpkgdir)
				if copied:
					# log XML here.
					if self.hub.CPM_LOGGER:
						self.hub.CPM_LOGGER.recordCopyToXML(self.srctree, desttree, catpkg)
						if isinstance(self.select, regextype):
							# If a regex was used to match the copied catpkg, record the regex.
							self.hub.CPM_LOGGER.record(desttree.name, catpkg, regex_matched=self.select)
						else:
							# otherwise, record the literal catpkg matched.
							self.hub.CPM_LOGGER.record(desttree.name, catpkg)
							if tcatpkg is not None:
								# This means we did a package move. Record the "new name" of the package, too. So both
								# old name and new name get marked as being part of this kit.
								self.hub.CPM_LOGGER.record(desttree.name, tcatpkg)
		if os.path.isdir(os.path.dirname(dest_cat_path)):
			with open(dest_cat_path, "w") as f:
				f.write("\n".join(sorted(dest_cat_set)))


class ProfileDepFix(MergeStep):
	"""ProfileDepFix undeprecates profiles marked as deprecated."""

	async def run(self, tree):
		fpath = os.path.join(tree.root, "profiles/profiles.desc")
		if os.path.exists(fpath):
			a = open(fpath, "r")
			for line in a:
				if line[0:1] == "#":
					continue
				sp = line.split()
				if len(sp) >= 2:
					prof_path = sp[1]
					await runShell("rm -f %s/profiles/%s/deprecated" % (tree.root, prof_path))


class RunSed(MergeStep):
	"""
	Run sed commands on specified files.

	files: List of files.

	commands: List of commands.
	"""

	def __init__(self, files, commands):
		self.files = files
		self.commands = commands

	async def run(self, tree):
		commands = list(itertools.chain.from_iterable(("-e", command) for command in self.commands))
		files = [os.path.join(tree.root, file) for file in self.files]
		await runShell(["sed"] + commands + ["-i"] + files)


class GenCache(MergeStep):
	"""GenCache runs egencache --update to update metadata."""

	def __init__(self, cache_dir=None, release=None):
		self.cache_dir = cache_dir
		self.release = release

	async def run(self, tree):

		if tree.name != "core-kit":
			repos_conf = (
				"[DEFAULT]\nmain-repo = core-kit\n\n[core-kit]\nlocation = %s/core-kit\n\n[%s]\nlocation = %s\n"
				% (tree.config.kit_dest, tree.reponame if tree.reponame else tree.name, tree.root)
			)

			# Perform QA check to ensure all eclasses are in place prior to performing egencache, as not having this can
			# cause egencache to hang.

			result = await getAllEclasses(tree, self.release)
			if None in result and len(result[None]):
				missing_eclasses = []
				for ec in result[None]:
					# if a missing eclass is not in core-kit, then we'll be concerned:
					if not os.path.exists("%s/core-kit/eclass/%s" % (tree.config.kit_dest, ec)):
						missing_eclasses.append(ec)
				if len(missing_eclasses):
					print("!!! Error: QA check on kit %s failed -- missing eclasses:" % tree.name)
					print("!!!      : " + " ".join(missing_eclasses))
					print(
						"!!!      : Please be sure to use kit-fixups or the overlay's eclass list to copy these necessary eclasses into place."
					)
					sys.exit(1)
		else:
			repos_conf = "[DEFAULT]\nmain-repo = core-kit\n\n[core-kit]\nlocation = %s/core-kit\n" % tree.config.kit_dest
		cmd = [
			"egencache",
			"--update",
			"--tolerant",
			"--repo",
			tree.reponame if tree.reponame else tree.name,
			"--repositories-configuration",
			repos_conf,
			"--config-root=/tmp",
			"--jobs",
			repr(multiprocessing.cpu_count() * 2),
		]
		if self.cache_dir:
			cmd += ["--cache-dir", self.cache_dir]
			if not os.path.exists(self.cache_dir):
				os.makedirs(self.cache_dir)
				os.chown(self.cache_dir, -1, grp.getgrnam("portage").gr_gid)
		attempts = 10
		attempt = 1
		while attempt <= attempts:
			if attempt != 1:
				print("Restarting egencache -- sometimes it dies... this is expected.")
			success = await runShell(cmd, abort_on_failure=False)
			if success:
				break
			attempt += 1
		if attempt > attempts:
			print("Couldn't get egencache to finish. Exiting.")
			sys.exit(1)


class GenUseLocalDesc(MergeStep):
	"""GenUseLocalDesc runs egencache to update use.local.desc"""

	async def run(self, tree):
		if tree.name != "core-kit":
			repos_conf = (
				"[DEFAULT]\nmain-repo = core-kit\n\n[core-kit]\nlocation = %s/core-kit\n\n[%s]\nlocation = %s\n"
				% (tree.config.kit_dest, tree.reponame if tree.reponame else tree.name, tree.root)
			)
		else:
			repos_conf = "[DEFAULT]\nmain-repo = core-kit\n\n[core-kit]\nlocation = %s/core-kit\n" % tree.config.kit_dest
		await runShell(
			[
				"egencache",
				"--update-use-local-desc",
				"--tolerant",
				"--config-root=/tmp",
				"--repo",
				tree.reponame if tree.reponame else tree.name,
				"--repositories-configuration",
				repos_conf,
			],
			abort_on_failure=False,
		)


class GitCheckout(MergeStep):
	def __init__(self, branch):
		self.branch = branch

	async def run(self, tree):
		await runShell(
			"(cd %s && git checkout %s || git checkout -b %s --track origin/%s || git checkout -b %s)"
			% (tree.root, self.branch, self.branch, self.branch, self.branch)
		)


class CreateBranch(MergeStep):
	def __init__(self, branch):
		self.branch = branch

	async def run(self, tree):
		await runShell("( cd %s && git checkout -b %s --track origin/%s )" % (tree.root, self.branch, self.branch))


class Minify(MergeStep):
	"""Minify removes ChangeLogs and shrinks Manifests."""

	async def run(self, tree):
		await runShell("( cd %s && find -iname ChangeLog | xargs rm -f )" % tree.root, abort_on_failure=False)
		await runShell("( cd %s && find -iname Manifest | xargs -i@ sed -ni '/^DIST/p' @ )" % tree.root)


#!/usr/bin/env python3
import logging
import os
from collections import defaultdict

import portage

from merge.async_engine import AsyncEngine
from merge.async_portage import async_xmatch
from merge.steps import MergeStep
from merge.tree import getcommandoutput, GitTree

portage._internal_caller = True
from portage.util.futures.iter_completed import async_iter_completed


# getAllEclasses() and getAllLicenses() uses the function getAllMeta() below to do all heavy lifting.  What getAllMeta() returns
# is a list of eclasses that are used by our kit, but this list doesn't indicate what repository holds the eclasses.

# So we don't know if the eclass is in the dest_kit or in the parent_repo and still needs to be copied over.  as an eclass
# 'fixup'. getAllEclasses() is designed to locate the actual eclass that we care about so we know what repo it lives in and what
# steps need to be taken, if any.

# First, we will look in our dest-kit repository. If it exists there, then it was already copied into place by a kit-fixup and
# we do not want to overwrite it with another eclass! Then we will look in the parent_repo (which is designed to be 'gentoo'),
# and see if the eclass is there. We expect to find it there. If we don't, it is a MISSING eclass (or license).

# getAllEclasses and getAllLicenses return a dictionary with the following keys, and with a list of files relative to the
# repo root as the dictionary value:
#
# 'parent_repo' : list of all eclasses that should be copied from parent repo
# 'dest_kit'	: list of all eclasses that were found in our kit and don't need to be copied (they are already in place)
# None			: list of all eclasses that were NOT found. This is an error and indicates we need some kit-fixups or
# 				  overlay-specific eclasses.


async def _getAllDriver(metadata, path_prefix, dest_kit, release):
	# these may be eclasses or licenses -- we use the term 'eclass' here:
	eclasses = await getAllMeta(metadata, dest_kit, release)
	out = {None: [], "dest_kit": []}
	for eclass in eclasses:
		ep = os.path.join(dest_kit.root, path_prefix, eclass)
		if os.path.exists(ep):
			out["dest_kit"].append(eclass)
			continue
		out[None].append(eclass)
	return out


def simpleGetAllLicenses(dest_kit, parent_repo):
	out = []
	for my_license in os.listdir(parent_repo.root + "/licenses"):
		if os.path.exists(dest_kit.root + "/licenses/" + my_license):
			continue
		out.append(my_license)
	return out


def simpleGetAllEclasses(dest_kit, parent_repo):
	"""
	A simpler method to get all eclasses copied into a kit. If the eclass exists in parent repo, but not in dest_kit,
	return it in a list.

	:param dest_kit:
	:param parent_repo:
	:return:
	"""
	out = []
	for eclass in os.listdir(parent_repo.root + "/eclass"):
		if not eclass.endswith(".eclass"):
			continue
		if os.path.exists(dest_kit.root + "/eclass/" + eclass):
			continue
		out.append(eclass)
	return out


async def getAllEclasses(dest_kit, release):
	return await _getAllDriver("INHERITED", "eclass", dest_kit, release)


async def getAllLicenses(dest_kit, release):
	return await _getAllDriver("LICENSE", "licenses", dest_kit, release)


# getAllMeta uses the Portage API to query metadata out of a set of repositories. It is designed to be used to figure
# out what licenses or eclasses to copy from a parent repository to the current kit so that the current kit contains a
# set of all eclasses (and licenses) it needs within itself, without any external dependencies on other repositories
# for these items -- this is a key design feature of kits to improve stability.

# It supports being called this way:
#
#  (parent_repo) -- all eclasses/licenses here
# 	 |
# 	 |
# 	 \-------------------------(dest_kit) -- no eclasses/licenses here yet
# 											 (though some may exist due to being copied by fixups)
#
#  getAllMeta() returns a set of actual files (without directories) that are used, so [ 'foo.eclass', 'bar.eclass']
#  or [ 'GPL-2', 'bleh' ].
#


async def getAllMeta(metadata, dest_kit, release):
	metadict = {"LICENSE": 0, "INHERITED": 1}
	metapos = metadict[metadata]

	env = os.environ.copy()
	env["PORTAGE_DEPCACHEDIR"] = "/var/cache/edb/%s-%s-%s-meta" % (release, dest_kit.name, dest_kit.branch)
	if dest_kit.name != "core-kit":
		env[
			"PORTAGE_REPOSITORIES"
		] = """
	[DEFAULT]
	main-repo = core-kit

	[core-kit]
	location = %s/core-kit
	aliases = gentoo

	[%s]
	location = %s
		""" % (
			dest_kit.config.kit_dest,
			dest_kit.name,
			dest_kit.root,
		)
	else:
		# we are testing a stand-alone kit that should have everything it needs included
		env[
			"PORTAGE_REPOSITORIES"
		] = """
	[DEFAULT]
	main-repo = core-kit

	[%s]
	location = %s
	aliases = gentoo
		""" % (
			dest_kit.name,
			dest_kit.root,
		)

	p = portage.portdbapi(mysettings=portage.config(env=env, config_profile_path=""))
	mymeta = set()

	future_aux = {}
	cpv_map = {}

	def future_generator():
		for catpkg in p.cp_all(trees=[dest_kit.root]):
			for cpv in p.cp_list(catpkg, mytree=dest_kit.root):
				if cpv == "":
					print("No match for %s" % catpkg)
					continue
				cpv_map[cpv] = catpkg
				my_future = p.async_aux_get(cpv, ["LICENSE", "INHERITED"], mytree=dest_kit.root)
				future_aux[id(my_future)] = cpv
				yield my_future

	for fu_fu in async_iter_completed(future_generator()):
		future_set = await fu_fu
		for future in future_set:
			cpv = future_aux.pop(id(future))
			try:
				result = future.result()
			except KeyError as e:
				print("aux_get fail", cpv, e)
			else:
				if metadata == "INHERITED":
					for eclass in result[metapos].split():
						key = eclass + ".eclass"
						if key not in mymeta:
							mymeta.add(key)
				elif metadata == "LICENSE":
					for lic in result[metapos].split():
						if lic in [")", "(", "||"] or lic.endswith("?"):
							continue
						if lic not in mymeta:
							mymeta.add(lic)
	return mymeta


def do_package_use_line(pkg, def_python, bk_python, imps):
	if "/bin/sh:" in imps:
		logging.error("ERROR in get_python_use line: %s --" % imps)
		return None
	if def_python not in imps:
		if bk_python in imps:
			return "%s python_single_target_%s" % (pkg, bk_python)
		else:
			return "%s python_single_target_%s python_targets_%s" % (pkg, imps[0], imps[0])
	return None


async def get_python_use_lines(p, catpkg, cur_tree, def_python, bk_python):
	ebs = {}
	for cpv in p.cp_list(catpkg):
		if len(cpv) == 0:
			continue
		cat, pvr = portage.catsplit(cpv)
		pkg, vers, rev = portage.pkgsplit(pvr)
		cmd = '( eval $(grep ^PYTHON_COMPAT %s/%s/%s/%s.ebuild 2>/dev/null); echo "${PYTHON_COMPAT[@]}" )' % (
			cur_tree,
			cat,
			pkg,
			pvr,
		)
		outp = await getcommandoutput(cmd)

		imps = outp[1].decode("ascii").split()
		new_imps = []

		# Tweak PYTHON_COMPAT just like we now do in the eclass, since we don't extract the data by pumping thru the eclass:

		for imp in imps:
			if imp in ["python3_5", "python3_6", "python3_7"]:
				new_imps.append("python3_7")
			elif imp == "python2+":
				new_imps.extend(["python2_7", "python3_7", "python3_8", "python3_9"])
			elif imp in ["python3+", "python3.7+"]:
				new_imps.extend(["python3_7", "python3_8", "python3_9"])
			elif imp == "python3_8+":
				new_imps.extend(["python3_8", "python3_9"])
			elif imp == "python3_9+":
				new_imps.append("python3_9")
			else:
				new_imps.append(imp)
		imps = new_imps
		if len(imps) != 0:
			ebs[cpv] = imps

	# ebs now is a dict containing catpkg -> PYTHON_COMPAT settings for each ebuild in the catpkg. We want to see if they are identical
	# if split == False, then we will do one global setting for the catpkg. If split == True, we will do individual settings for each version
	# of the catpkg, since there are differences. This saves space in our python-use file while keeping everything correct.

	oldval = None
	split = False
	for key, val in ebs.items():
		if oldval is None:
			oldval = val
		else:
			if oldval != val:
				split = True
				break
	lines = []
	if len(ebs.keys()):
		if not split:
			line = do_package_use_line(catpkg, def_python, bk_python, oldval)
			if line is not None:
				lines.append(line)
		else:
			for key, val in ebs.items():
				line = do_package_use_line("=%s" % key, def_python, bk_python, val)
				if line is not None:
					lines.append(line)
	return lines


class GenPythonUse(MergeStep):
	def __init__(self, hub, py_settings, out_subpath, release):
		self.hub = hub
		self.def_python = py_settings["primary"]
		self.bk_python = py_settings["alternate"]
		self.mask = py_settings["mask"]
		self.out_subpath = out_subpath
		self.release = release

	async def run(self, cur_overlay):
		cur_tree = cur_overlay.root
		try:
			with open(os.path.join(cur_tree, "profiles/repo_name")) as f:
				cur_name = f.readline().strip()
		except FileNotFoundError:
			cur_name = cur_overlay.name
		env = os.environ.copy()
		env["PORTAGE_DEPCACHEDIR"] = "/var/cache/edb/%s-%s-%s-meta" % (self.release, cur_overlay.name, cur_overlay.branch)
		if cur_name != "core-kit":
			env[
				"PORTAGE_REPOSITORIES"
			] = """
[DEFAULT]
main-repo = core-kit

[core-kit]
location = %s/core-kit
aliases = gentoo

[%s]
location = %s
""" % (
				cur_overlay.config.kit_dest,
				cur_name,
				cur_tree,
			)
		else:
			env["PORTAGE_REPOSITORIES"] = (
				"""
[DEFAULT]
main-repo = core-kit

[core-kit]
location = %s/core-kit
aliases = gentoo
"""
				% cur_overlay.config.kit_dest
			)
		p = portage.portdbapi(mysettings=portage.config(env=env, config_profile_path=""))

		all_lines = []
		for catpkg in p.cp_all():

			if not os.path.exists(cur_tree + "/" + catpkg):
				# catpkg is from core-kit, but we are not processing core kit, so skip:
				continue

			# It would be nice to use a threadpool, but tried -- doesn't work because asyncio does not like threads
			result = await get_python_use_lines(p, catpkg, cur_tree, self.def_python, self.bk_python)
			if result is not None:
				all_lines += result

		all_lines = sorted(all_lines)

		outpath = cur_tree + "/profiles/" + self.out_subpath + "/package.use"
		if not os.path.exists(outpath):
			os.makedirs(outpath)
		with open(outpath + "/python-use", "w") as f:
			for l in all_lines:
				f.write(l + "\n")
		# for core-kit, set good defaults as well.
		if cur_name == "core-kit":
			outpath = cur_tree + "/profiles/" + self.out_subpath + "/make.defaults"
			a = open(outpath, "w")
			a.write('PYTHON_TARGETS="%s %s"\n' % (self.def_python, self.bk_python))
			a.write('PYTHON_SINGLE_TARGET="%s"\n' % self.def_python)
			a.close()
			if self.mask:
				outpath = cur_tree + "/profiles/" + self.out_subpath + "/package.mask/funtoo-kit-python"
				if not os.path.exists(os.path.dirname(outpath)):
					os.makedirs(os.path.dirname(outpath))
				a = open(outpath, "w")
				a.write(self.mask + "\n")
				a.close()


def extract_uris(src_uri):
	fn_urls = defaultdict(list)

	def record_fn_url(my_fn, p_blob):
		if p_blob not in fn_urls[my_fn]:
			new_files.append(my_fn)
			fn_urls[my_fn].append(p_blob)

	blobs = src_uri.split()
	prev_blob = None
	pos = 0
	new_files = []

	while pos <= len(blobs):
		if pos < len(blobs):
			blob = blobs[pos]
		else:
			blob = ""
		if blob in [")", "(", "||"] or blob.endswith("?"):
			pos += 1
			continue
		if blob == "->":
			# We found a http://foo -> bar situation. Handle it:
			fn = blobs[pos + 1]
			if fn is not None:
				record_fn_url(fn, prev_blob)
				prev_blob = None
				pos += 2
		else:
			# Process previous item:
			if prev_blob:
				fn = prev_blob.split("/")[-1]
				record_fn_url(fn, prev_blob)
			prev_blob = blob
			pos += 1

	return fn_urls, new_files


class FastPullScan(MergeStep):
	def __init__(self, now, engine: AsyncEngine = None):
		self.now = now
		self.engine = engine

	async def run(self, cur_overlay: GitTree):
		if self.engine is None:
			return
		cur_tree = cur_overlay.root
		try:
			with open(os.path.join(cur_tree, "profiles/repo_name")) as f:
				cur_name = f.readline().strip()
		except FileNotFoundError:
			cur_name = cur_overlay.name
		env = os.environ.copy()
		if cur_name != "core-kit":
			env[
				"PORTAGE_REPOSITORIES"
			] = """
		[DEFAULT]
		main-repo = core-kit

		[core-kit]
		location = %s/core-kit
		aliases = gentoo

		[%s]
		location = %s
		""" % (
				cur_overlay.config.kit_dest,
				cur_name,
				cur_tree,
			)
		else:
			env["PORTAGE_REPOSITORIES"] = (
				"""
		[DEFAULT]
		main-repo = core-kit

		[core-kit]
		location = %s/core-kit
		aliases = gentoo
		"""
				% cur_overlay.config.kit_dest
			)
		env["ACCEPT_KEYWORDS"] = "~amd64 amd64"
		p = portage.portdbapi(mysettings=portage.config(env=env, config_profile_path=""))

		for pkg in p.cp_all(trees=[cur_overlay.root]):

			# src_uri now has the following format:

			# src_uri["foo.tar.gz"] = [ "https://url1", "https//url2" ... ]
			# entries in SRC_URI from fetch-restricted ebuilds will have SRC_URI prefixed by "NOMIRROR:"

			# We are scanning SRC_URI in all ebuilds in the catpkg, as well as Manifest.
			# This will give us a complete list of all archives used in the catpkg.

			# We want to prioritize SRC_URI for bestmatch-visible ebuilds. We will use bm
			# and prio to tag files that are in bestmatch-visible ebuilds.

			bm = await async_xmatch(p, "bestmatch-visible", pkg)

			fn_urls = defaultdict(list)
			fn_meta = defaultdict(dict)

			for cpv in await async_xmatch(p, "match-all", pkg):
				if len(cpv) == 0:
					continue
				try:
					aux_info = await p.async_aux_get(cpv, ["SRC_URI", "RESTRICT"], mytree=cur_overlay.root)
					restrict = aux_info[1].split()
					mirror_restrict = False
					for r in restrict:
						if r == "mirror":
							mirror_restrict = True
							break
				except portage.exception.PortageKeyError:
					print("!!! PortageKeyError on %s" % cpv)
					continue

				# record our own metadata about each file...
				new_fn_urls, new_files = extract_uris(aux_info[0])
				fn_urls.update(new_fn_urls)
				for fn in new_files:
					fn_meta[fn]["restrict"] = mirror_restrict
					fn_meta[fn]["bestmatch"] = cpv == bm

			man_info = {}
			man_file = cur_tree + "/" + pkg + "/Manifest"
			if os.path.exists(man_file):
				man_f = open(man_file, "r")
				for line in man_f.readlines():
					ls = line.split()
					if len(ls) <= 3 or ls[0] != "DIST":
						continue
					try:
						digest_index = ls.index("SHA512") + 1
						digest_type = "sha512"
					except ValueError:
						try:
							digest_index = ls.index("SHA256") + 1
							digest_type = "sha256"
						except ValueError:
							print("Error: Manifest file %s has invalid format: " % man_file)
							print(" ", line)
							continue
					man_info[ls[1]] = {"size": ls[2], "digest": ls[digest_index], "digest_type": digest_type}
				man_f.close()

			# for each catpkg:

			for f, uris in fn_urls.items():

				if f not in man_info:
					print(
						"Error: %s/%s: %s Manifest file contains nothing for %s, skipping..."
						% (cur_overlay.name, cur_overlay.branch, pkg, f)
					)
					continue

				s_out = ""
				for u in uris:
					s_out += u + "\n"

				# If we have already grabbed this distfile, then let's not queue it for fetching...

				if man_info[f]["digest_type"] == "sha512":
					# enqueue this distfile to potentially be added to distfile-spider. This is done asynchronously.
					self.engine.enqueue(
						file=f,
						digest=man_info[f]["digest"],
						size=man_info[f]["size"],
						restrict=fn_meta[f]["restrict"],
						catpkg=pkg,
						src_uri=s_out,
						kit_name=cur_overlay.name,
						kit_branch=cur_overlay.branch,
						digest_type=man_info[f]["digest_type"],
						bestmatch=fn_meta[f]["bestmatch"],
					)
