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
