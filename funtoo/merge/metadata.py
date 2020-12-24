#!/usr/bin/env python3

import hashlib
import json
import logging
import os
import re
import sys
from collections import defaultdict
from concurrent.futures.thread import ThreadPoolExecutor
from multiprocessing import cpu_count
from concurrent.futures import as_completed

from merge_utils.tree import run


def __init__(hub):
	hub.METADATA_GEN_ERRORS = defaultdict(list)
	hub.METADATA_MISC_ERRORS = defaultdict(list)


def display_error_summary(hub):
	repo_objs_sorted = sorted(list(hub.METADATA_GEN_ERRORS.keys()), key=lambda x: len(hub.METADATA_GEN_ERRORS[x]))
	if len(repo_objs_sorted):
		logging.warning("The following kits had errors during metadata extraction:")
		for repo_obj in repo_objs_sorted:
			branch_info = f"{repo_obj.name} branch {repo_obj.branch}".ljust(30)
			logging.warning(f"* {branch_info} -- {len(hub.METADATA_GEN_ERRORS[repo_obj])} errors.")
			outpath = os.path.join(hub.MERGE_CONFIG.temp_path, f"metadata-errors-{repo_obj.name}-{repo_obj.branch}.log")
			out = []
			for item in hub.METADATA_GEN_ERRORS[repo_obj]:
				out.append({"ebuild_path": item.ebuild_path, "msg": item.msg, "output": item.output})
			with open(outpath, "w") as f:
				f.write(json.dumps(out, indent=4))
		logging.warning(f"Metadata errors logged to {hub.MERGE_CONFIG.temp_path}.")


def get_thirdpartymirrors(hub, repo_path):
	mirr_dict = {}
	with open(os.path.join(repo_path, "profiles/thirdpartymirrors"), "r") as f:
		lines = f.readlines()
		for line in lines:
			ls = line.split()
			mirr_dict[ls[0]] = ls[1:]
	return mirr_dict


def iter_thirdpartymirror(hub, mirr_dict, mirror):
	if mirror not in mirr_dict:
		return None
	for mirr_url in mirr_dict[mirror]:
		yield mirr_url


def expand_thirdpartymirror(hub, mirr_dict, url):

	non_mirr_part = url[9:]
	mirr_split = non_mirr_part.split("/")
	mirror = mirr_split[0]
	rest_of_url = "/".join(mirr_split[1:])
	if mirror not in mirr_dict:
		print("Mirror", mirror, "not found")
		return None
	for mirr_url in mirr_dict[mirror]:
		if mirror == "gentoo" and mirr_url.startswith("https://fastpull-us"):
			continue
		final_url = mirr_url.rstrip("/") + "/" + rest_of_url
		return final_url


class MetadataError:
	def __init__(self, repo=None, ebuild_path=None, output=None, msg=None):
		self.repo = repo
		self.ebuild_path = ebuild_path
		self.output = output
		self.msg = msg


METADATA_LINES = [
	"DEPEND",
	"RDEPEND",
	"SLOT",
	"SRC_URI",
	"RESTRICT",
	"HOMEPAGE",
	"LICENSE",
	"DESCRIPTION",
	"KEYWORDS",
	"INHERITED",
	"IUSE",
	"REQUIRED_USE",
	"PDEPEND",
	"BDEPEND",
	"EAPI",
	"PROPERTIES",
	"DEFINED_PHASES",
	"HDEPEND",
	"PYTHON_COMPAT",
]

AUXDB_LINES = sorted(
	[
		"DEPEND",
		"RDEPEND",
		"SLOT",
		"SRC_URI",
		"RESTRICT",
		"HOMEPAGE",
		"LICENSE",
		"DESCRIPTION",
		"KEYWORDS",
		"IUSE",
		"REQUIRED_USE",
		"PDEPEND",
		"BDEPEND",
		"EAPI",
		"PROPERTIES",
		"DEFINED_PHASES",
	]
)


def get_md5(filename):
	"""
	Simple function to get an md5 hex digest of a file.
	"""

	h = hashlib.md5()
	with open(filename, "rb") as f:
		h.update(f.read())
	return h.hexdigest()


def strip_rev(hub, s):
	"""
	A short function to strip the revision from the end of an ebuild, returning either
	`( 'string_with_revision_missing', '<revision_num_as_string>' )` or
	`( 'original_string', None )` if no revision was found.
	"""

	num_strip = s.rstrip("0123456789")
	if num_strip != s and num_strip[-2:] == "-r":
		rev_strip = num_strip[:-2]
		rev = s[len(num_strip) :]
		return rev_strip, rev
	return s, None


def get_catpkg_from_cpvs(hub, cpv_list):
	"""
	This function takes a list of things that look like 'sys-apps/foboar-1.2.0-r1' and returns a dict of
	unique catpkgs found (as dict keys) and exact matches (in dict value, as a member of a set.)

	Note that the input to this function must have version information. This method is not designed to
	distinguish between non-versioned atoms and versioned ones.
	"""
	catpkgs = defaultdict(set)
	for cpv in cpv_list:
		reduced, rev = hub._.strip_rev(cpv)
		last_hyphen = reduced.rfind("-")
		cp = cpv[:last_hyphen]
		catpkgs[cp].add(cpv)
	return catpkgs


def get_eapi_of_ebuild(hub, ebuild_path):
	"""
	This function is used to parse the first few lines of the ebuild looking for an EAPI=
	line. This is annoying but necessary.
	"""

	# This pattern is specified by PMS section 7.3.1.
	_pms_eapi_re = re.compile(r"^[ \t]*EAPI=(['\"]?)([A-Za-z0-9+_.-]*)\1[ \t]*([ \t]#.*)?$")
	_comment_or_blank_line = re.compile(r"^\s*(#.*)?$")

	def _parse_eapi_ebuild_head(f):
		eapi = None
		eapi_lineno = None
		lineno = 0
		for line in f:
			lineno += 1
			m = _comment_or_blank_line.match(line)
			if m is None:
				eapi_lineno = lineno
				m = _pms_eapi_re.match(line)
				if m is not None:
					eapi = m.group(2)
				break

		return (eapi, eapi_lineno)

	with open(ebuild_path, "r") as fobj:
		return _parse_eapi_ebuild_head(fobj.readlines())


def extract_manifest_hashes(hub, man_file):
	"""
	Given a manifest path as an argument, attempt to open `Manifest` and extract all digests for each
	DIST entry, and return this info along with filesize in a dict.
	"""
	man_info = {}
	if os.path.exists(man_file):
		with open(man_file, "r") as man_f:
			for line in man_f.readlines():
				ls = line.split()
				if len(ls) <= 3 or ls[0] != "DIST":
					continue
				pos = 3
				digests = {}
				while pos < len(ls):
					hash_type = ls[pos].lower()
					hash_digest = ls[pos + 1]
					digests[hash_type] = hash_digest
					pos += 2
				man_info[ls[1]] = {"size": ls[2], "hashes": digests}
	return man_info


def extract_uris(hub, src_uri):
	"""
	This function will take a SRC_URI value from an ebuild, and it will return a dictionary in the following format:

	{ "filename1.tar.gz" : { "src_uri" : [ "https://url1", "https//url2" ] } }

	All possible download locations will be returned for files in the format above.

	Note that in the code below, a "blob" is simply a piece of parsed SRC_URI information that *may* be a URL.
	"""
	fn_urls = {}

	def record_fn_url(my_fn, p_blob):
		if my_fn not in fn_urls:
			fn_urls[my_fn] = {"src_uri": [p_blob]}
		else:
			fn_urls[my_fn]["src_uri"].append(p_blob)

	blobs = src_uri.split()
	prev_blob = None
	pos = 0

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
			try:
				fn = blobs[pos + 1]
			except IndexError:
				# A -> at the end of a SRC_URI. Shouldn't happen but you never know.
				fn = None
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

	return fn_urls


def get_catpkg_relations_from_depstring(hub, depstring):
	"""
	This is a handy function that will take a dependency string, like something you would see in DEPEND, and it will
	return a set of all catpkgs referenced in the dependency string. It does not evaluate USE conditionals, nor does
	it return any blockers.

	This method is used to determine package relationships, in a general sense. Does one package reference another
	package in a dependency in some way? That's what this is used for.

	What is returned is a python set of catpkg atoms (no version info, just cat/pkg).
	"""
	catpkgs = set()

	for part in depstring.split():

		# 1. Strip out things we are not interested in:
		if part in ["(", ")", "||"]:
			continue
		if part.endswith("?"):
			continue
		if part.startswith("!"):
			# we are not interested in blockers
			continue

		# 2. For remaining catpkgs, strip comparison operators:
		has_version = False
		for op in [">=", "<=", ">", "<", "=", "~"]:
			if part.startswith(op):
				part = part[len(op) :]
				has_version = True
				break

		# 3. From the end, strip SLOT and USE info:
		for ender in [":", "["]:
			# strip everything from slot or USE spec onwards
			pos = part.rfind(ender)
			if pos == -1:
				continue
			part = part[:pos]

		# 4. Strip any trailing '*':
		part = part.rstrip("*")

		# 5. We should now have a catpkg or catpgkg-version(-rev). If we have a version, remove it.

		if has_version:
			ps = part.split("-")
			part = "-".join(ps[:-1])

		catpkgs.add(part)
	return catpkgs


class EclassHashCollection:
	"""
	This is just a simple class for storing the path where we grabbed all the eclasses from plus
	the mapping from eclass name (ie. 'eutils') to the hexdigest of the generated hash.
	"""

	def __init__(self, path):
		self.path = path
		self.hashes = {}

	def copy(self):
		new_obj = EclassHashCollection(self.path)
		new_obj.hashes = self.hashes.copy()
		return new_obj


def record_gen_error(hub, repo=None, ebuild_path=None, output=None, msg=None):
	hub.METADATA_GEN_ERRORS[repo].append(MetadataError(repo=repo, ebuild_path=ebuild_path, output=output, msg=msg))


def record_misc_error(hub, repo=None, ebuild_path=None, output=None, msg=None):
	hub.METADATA_MISC_ERRORS[repo].append(MetadataError(repo=repo, ebuild_path=ebuild_path, output=output, msg=msg))


def extract_ebuild_metadata(hub, repo_obj, atom, ebuild_path=None, env=None, eclass_paths=None):
	infos = {"HASH_KEY": atom}
	env["PATH"] = "/bin:/usr/bin"
	env["LC_COLLATE"] = "POSIX"
	env["LANG"] = "en_US.UTF-8"
	# For things to work correctly, the EAPI of the ebuild has to be manually extracted:
	eapi, lineno = hub._.get_eapi_of_ebuild(ebuild_path)
	if eapi is not None and eapi in "01234567":
		env["EAPI"] = eapi
	else:
		env["EAPI"] = "0"
	env["PORTAGE_GID"] = "250"
	env["PORTAGE_BIN_PATH"] = "/usr/lib/portage/python3.7"
	env["PORTAGE_ECLASS_LOCATIONS"] = " ".join(eclass_paths)
	env["EBUILD"] = ebuild_path
	env["EBUILD_PHASE"] = "depend"
	# This tells ebuild.sh to write out the metadata to stdout (fd 1) which is where we will grab
	# it from:
	env["PORTAGE_PIPE_FD"] = "1"
	result = run("/bin/bash " + os.path.join(env["PORTAGE_BIN_PATH"], "ebuild.sh"), env=env)
	if result.returncode != 0:
		hub._.record_gen_error(
			repo=repo_obj, msg=f"non-zero returncode {result.returncode}", ebuild_path=ebuild_path, output=result.stderr
		)
	try:
		# Extract results:
		lines = result.stdout.split("\n")
		line = 0
		found = set()
		while line < len(METADATA_LINES) and line < len(lines):
			found.add(METADATA_LINES[line])
			infos[METADATA_LINES[line]] = lines[line]
			line += 1
		if line != len(METADATA_LINES):
			missing = set(METADATA_LINES) - found
			hub._.record_gen_error(
				msg=f"Missing metadata: {' '.join(missing)}", repo=repo_obj, ebuild_path=ebuild_path, output=result.stderr
			)
			return None
		return infos
	except (FileNotFoundError, IndexError) as e:
		hub._.record_gen_error(repo=repo_obj, msg=f"Exception: {str(e)}", ebuild_path=ebuild_path)
		return None


def get_filedata(hub, src_uri, manifest_path):
	"""
	This function is given `src_uri` which is the literal `SRC_URI` data from an ebuild, and a path to a `Manifest`
	for the catpkg.

	What is returned is a list of dictionaries. Each dictionary represents a file that will be downloaded for a
	particular ebuild.

	Each dictionary has the following keys:

	*. `name` (dest. filename),
	*. `src_uri` (a list of URIs to download the file, and may include 'mirror://' URLs),
	*. `size` (size of file in bytes)
	*. `hashes` (digests from the `Manifest` file associated with this file.

	Note that any files that appear in the `Manifest` but not in `SRC_URI` are ignored. This function is purely
	intended to "complete" the `SRC_URI` data with data that is in the `Manifest`.

	This function uses two sub-functions to do most of the dirty work, and then merges the results.

	MongoDB is happiest when we don't use filenames as keys, since they have periods in them which is not allowed.
	This normalizes our filedata for MongoDB. `extract_uris` and `extract_manifest_hashes` are all indexed by filename,
	but instead we want to return a list consisting of dictionaries. We move the key inside each dict.

	{"file1.tar.gz" : { ... }} -> [ { "name" : "file1.tar.gz", ... }, ... ]
	"""

	filedata = extract_manifest_hashes(hub, manifest_path)
	extracted_uris = extract_uris(hub, src_uri)

	for fn, sub_dict in extracted_uris.items():
		# just augment SRC_URI data with Manifest data, if available.
		if fn in filedata:
			extracted_uris[fn].update(filedata[fn])

	outdata = []
	for fn, datums in extracted_uris.items():
		datums["name"] = fn
		outdata.append(datums)

	return outdata


def get_ebuild_metadata(hub, repo, ebuild_path, eclass_hashes=None, eclass_paths=None, write_cache=False):
	"""
	This function will grab metadata from a single ebuild pointed to by `ebuild_path` and
	return it as a dictionary.

	If `write_cache` is True, a `metadata/md5-cache/cat/pvr` file will be written out to the
	repository as well. If `write_cache` is True, then `eclass_paths` and `eclass_hashes`
	must be supplied.

	This function sets up a clean environment and spawns a bash process which runs `ebuild.sh`,
	which is a file from Portage that processes the ebuild and eclasses and outputs the metadata
	so we can grab it. We do a lot of the environment setup inline in this function for clarity
	(helping the reader understand the process) and also to avoid bunches of function calls.

	TODO: Currently hard-coded to assume a python3.7 installation. We should fix that at some point.
	"""

	basespl = ebuild_path.split("/")
	atom = basespl[-3] + "/" + basespl[-1][:-7]
	ebuild_md5 = get_md5(ebuild_path)
	cp_dir = ebuild_path[: ebuild_path.rfind("/")]
	manifest_path = cp_dir + "/Manifest"

	if not os.path.exists(manifest_path):
		manifest_md5 = None
	else:
		# TODO: this is a potential area of performance improvement. Multiple ebuilds in a single catpkg
		#       directory will result in get_md5() being called on the same Manifest file multiple times
		#       during a run. Cache might be good here.
		manifest_md5 = get_md5(manifest_path)

	# Try to see if we already have this metadata in our kit metadata cache.
	existing = hub.cache.metadata.get_atom(repo, atom, ebuild_md5, manifest_md5, eclass_hashes)
	repo.KIT_CACHE_RETRIEVED_ATOMS.add(atom)

	if existing:
		infos = existing["metadata"]
		metadata_out = existing["metadata_out"]
	# TODO: Note - this may be a 'dud' existing entry where there was a metadata failure previously.
	else:
		sys.stdout.write("*")
		sys.stdout.flush()
		repo.KIT_CACHE_MISSES.add(atom)
		env = {}
		env["PF"] = os.path.basename(ebuild_path)[:-7]
		env["CATEGORY"] = ebuild_path.split("/")[-3]
		pkg_only = ebuild_path.split("/")[-2]  # JUST the pkg name "foobar"
		reduced, rev = hub._.strip_rev(env["PF"])
		if rev is None:
			env["PR"] = "r0"
			pkg_and_ver = env["PF"]
		else:
			env["PR"] = f"r{rev}"
			pkg_and_ver = reduced
		env["P"] = pkg_and_ver
		env["PV"] = pkg_and_ver[len(pkg_only) + 1 :]
		env["PN"] = pkg_only
		env["PVR"] = env["PF"][len(env["PN"]) + 1 :]

		infos = hub._.extract_ebuild_metadata(repo, atom, ebuild_path, env, eclass_paths)

		eclass_out = ""
		eclass_tuples = []

		# TODO: do we have a situation where because we can't extract inheritance information, if we fail with
		# metadata extraction then we will not know if and when we should attempt to re-try the metadata extraction?
		# Therefore we should record *all* eclass hashes (or a hash of hashes) that we check to see if changed along
		# with the ebuild md5 to tell if we should attempt to retry the extraction. Or we could keep retrying every
		# time. Maybe?

		if infos and infos["INHERITED"]:

			# Do common pre-processing for eclasses:

			for eclass_name in sorted(infos["INHERITED"].split()):
				if eclass_name not in eclass_hashes:
					hub._.record_misc_error(repo=repo, msg=f"Can't find eclass hash for {eclass_name}", ebuild_path=ebuild_path)
					continue
				try:
					eclass_out += f"\t{eclass_name}\t{eclass_hashes[eclass_name]}"
					eclass_tuples.append((eclass_name, eclass_hashes[eclass_name]))
				except KeyError as ke:
					hub._.record_misc_error(
						repo=repo, msg=f"Can't find eclass {eclass_name} when processing {ebuild_path}", ebuild_path=ebuild_path
					)

		metadata_out = ""
		if infos:
			# if metdata extraction successful...
			for key in AUXDB_LINES:
				if infos[key] != "":
					metadata_out += key + "=" + infos[key] + "\n"
			if len(eclass_out):
				metadata_out += "_eclasses_=" + eclass_out[1:] + "\n"
			metadata_out += "_md5_=" + ebuild_md5 + "\n"

		# Extended metadata calculation:

		td_out = {}
		relations = defaultdict(set)
		if infos:
			# if metadata extraction successful...
			for key in ["DEPEND", "RDEPEND", "PDEPEND", "BDEPEND", "HDEPEND"]:
				if infos[key]:
					relations[key] = hub._.get_catpkg_relations_from_depstring(infos[key])
		all_relations = set()
		relations_by_kind = dict()

		for key, relset in relations.items():
			all_relations = all_relations | relset
			relations_by_kind[key] = sorted(list(relset))

		td_out["relations"] = sorted(list(relations))
		td_out["relations_by_kind"] = relations_by_kind
		td_out["category"] = env["CATEGORY"]
		td_out["revision"] = env["PR"].lstrip("r")
		td_out["package"] = env["PN"]
		td_out["catpkg"] = env["CATEGORY"] + "/" + env["PN"]
		td_out["atom"] = atom
		td_out["eclasses"] = eclass_tuples
		td_out["kit"] = repo.name
		td_out["branch"] = repo.branch
		td_out["metadata"] = infos
		td_out["md5"] = ebuild_md5
		td_out["metadata_out"] = metadata_out
		td_out["manifest_md5"] = manifest_md5
		if infos and manifest_md5 is not None and "SRC_URI" in infos:
			td_out["files"] = get_filedata(hub, infos["SRC_URI"], manifest_path)
		hub.cache.metadata.update_atom(repo, td_out)

	if infos and write_cache:
		# if we successfully extracted metadata and we are told to write cache, write the cache entry:
		metadata_outpath = os.path.join(repo.root, "metadata/md5-cache")
		final_md5_outpath = os.path.join(metadata_outpath, atom)
		os.makedirs(os.path.dirname(final_md5_outpath), exist_ok=True)
		with open(os.path.join(metadata_outpath, atom), "w") as f:
			f.write(metadata_out)

	return infos


def catpkg_generator(hub, repo_path=None):
	"""
	This function is a generator that will scan a specified path for all valid category/
	package directories (catpkgs). It will yield paths to these directories. It defines
	a valid catpkg as a path two levels deep that contains at least one .ebuild file.
	"""

	cpdirs = defaultdict(set)

	for catdir in os.listdir(repo_path):
		catpath = os.path.join(repo_path, catdir)
		if not os.path.isdir(catpath):
			continue
		for pkgdir in os.listdir(catpath):
			pkgpath = os.path.join(catpath, pkgdir)
			if not os.path.isdir(pkgpath):
				continue
			for ebfile in os.listdir(pkgpath):
				if ebfile.endswith(".ebuild"):
					if pkgdir not in cpdirs[catdir]:
						cpdirs[catdir].add(pkgdir)
						yield os.path.join(pkgpath)


def ebuild_generator(ebuild_src=None):
	"""

	This function is a generator that scans the specified path for ebuilds and yields all
	the ebuilds it finds. You should point it to the root path of a kit or overlay.

	"""

	for catdir in os.listdir(ebuild_src):
		catpath = os.path.join(ebuild_src, catdir)
		if not os.path.isdir(catpath):
			continue
		for pkgdir in os.listdir(catpath):
			pkgpath = os.path.join(catpath, pkgdir)
			if not os.path.isdir(pkgpath):
				continue
			for ebfile in os.listdir(pkgpath):
				if ebfile.endswith(".ebuild"):
					yield os.path.join(pkgpath, ebfile)


def get_eclass_hashes(hub, eclass_sourcedir):
	"""

	For generating metadata, we need md5 hashes of all eclasses for writing out into the metadata.

	This function grabs all the md5sums for all eclasses.

	"""

	eclass_hashes = EclassHashCollection(eclass_sourcedir)
	ecrap = os.path.join(eclass_sourcedir, "eclass")
	for eclass in os.listdir(ecrap):
		if not eclass.endswith(".eclass"):
			continue
		eclass_path = os.path.join(ecrap, eclass)
		eclass_name = eclass[:-7]
		eclass_hashes.hashes[eclass_name] = get_md5(eclass_path)
	return eclass_hashes


# TODO: maybe change this name to post_actions(). And integrate Manifest generation here. We want
#       to avoiding having MANIFEST_LINES or integrate MANIFEST_LINES better into the kit-cache.
#       This is not ABSOLUTELY necessary but may make things a bit simpler. MANIFEST_LINES was
#       created before we had the kit-cache and deepdive.


def gen_cache(hub, repo):
	"""

	Generate md5-cache metadata from a bunch of ebuilds.

	`eclass_src` should be a path pointing to a kit that has all the eclasses. Typically you point this
	to a `core-kit` that already has all of the eclasses finalized and copied over.

	`metadata_out` tells gencache where to write the metadata. You want to point this to something like
	`/path/to/kit/metadata/md5-cache`.

	`ebuild_src` points to a kit that contains all the ebuilds you want to generate metadata for. You
	just point to the root of the kit and all eclasses are found and metadata is generated.

	"""

	with ThreadPoolExecutor(max_workers=cpu_count()) as executor:
		count = 0
		futures = []
		fut_map = {}

		# core-kit's eclass hashes are cached here:
		eclass_hashes = hub.ECLASS_HASHES.hashes.copy()
		eclass_paths = [hub.ECLASS_HASHES.path]

		if repo.name != "core-kit":
			# Add in any eclasses that exist local to the kit.
			local_eclass_hashes = hub._.get_eclass_hashes(repo.root)
			eclass_hashes.update(local_eclass_hashes.hashes)
			eclass_paths = [local_eclass_hashes.path] + eclass_paths  # give local eclasses priority

		for ebpath in ebuild_generator(ebuild_src=repo.root):
			future = executor.submit(
				hub._.get_ebuild_metadata,
				repo,
				ebpath,
				eclass_hashes=eclass_hashes,
				eclass_paths=eclass_paths,
				write_cache=True,
			)
			fut_map[future] = ebpath
			futures.append(future)

		for future in as_completed(futures):
			count += 1
			data = future.result()
			if data is None:
				sys.stdout.write("!")
			else:
				# Record all metadata in-memory so it's available later.
				hash_key = data["HASH_KEY"]
				sys.stdout.write(".")
				sys.stdout.flush()

		print(f"{count} ebuilds processed.")


async def get_python_use_lines(hub, repo, catpkg, cpv_list, cur_tree, def_python, bk_python):
	ebs = {}
	for cpv in cpv_list:
		metadata = repo.KIT_CACHE[cpv]["metadata"]
		if not metadata:
			imps = []
		else:
			imps = metadata["PYTHON_COMPAT"].split()

		# For anything in PYTHON_COMPAT that we would consider equivalent to python3_7, we want to
		# set python3_7 instead. This is so we match the primary python implementation correctly
		# so we don't incorrectly enable the backup python implementation. We basically have to
		# mirror the exact mapping logic in python-utils-r1.eclass.

		new_imps = set()
		for imp in imps:
			if imp in ["python3_5", "python3_6"]:
				hub._.record_misc_error(
					repo=repo,
					ebuild_path=f"{cur_tree}/{catpkg}/{cpv.split('/')[-1]}.ebuild",
					msg=f"Old {imp} referenced in PYTHON_COMPAT",
				)

				# The eclass bumps these to python3_7. We do the same to get correct results:
				new_imps.add(def_python)
			elif imp in ["python3+", "python3_7+"]:
				new_imps.update(["python3_7", "python3_8", "python3_9"])
			elif imp == "python3.8+":
				new_imps.update(["python3_8", "python3_9"])
			elif imp == "python3.9+":
				new_imps.add("python3_9")
			elif imp == "python2+":
				new_imps.update(["python2_7", "python3_7", "python3_8", "python3_9"])
			else:
				new_imps.add(imp)
				if imp in ["python2_4", "python2_5", "python2_6"]:
					hub._.record_misc_error(
						repo=repo,
						ebuild_path=f"{cur_tree}/{catpkg}/{cpv.split('/')[-1]}.ebuild",
						msg=f"Old {imp} referenced in PYTHON_COMPAT",
					)
		imps = list(new_imps)
		if len(imps):
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
			line = hub._.do_package_use_line(catpkg, def_python, bk_python, oldval)
			if line is not None:
				lines.append(line)
		else:
			for key, val in ebs.items():
				line = hub._.do_package_use_line("=%s" % key, def_python, bk_python, val)
				if line is not None:
					lines.append(line)
	return lines


def do_package_use_line(hub, pkg, def_python, bk_python, imps):
	out = None
	if def_python not in imps:
		if bk_python in imps:
			out = "%s python_single_target_%s" % (pkg, bk_python)
		else:
			out = "%s python_single_target_%s python_targets_%s" % (pkg, imps[0], imps[0])
	return out


# vim: ts=4 sw=4 noet
