#!/usr/bin/env python3

import hashlib
import os
import re
import sys
from concurrent.futures.thread import ThreadPoolExecutor
from enum import Enum
from multiprocessing import cpu_count
from concurrent.futures import as_completed

from merge_utils.tree import run


def __init__(hub):
	hub.METADATA_ERRORS = []


class Severity(Enum):
	FATAL = 0
	VERYBAD = 1
	NONFATAL = 2
	WARNING = 3
	SHOULDFIX = 4
	ANOMALY = 5
	NOTE = 6


class MetadataError:
	def __init__(self, severity=None, ebuild_path=None, output=None, msg=None):
		self.severity = severity
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


class EclassHashCollection:

	"""
	This is just a simple class for storing the path where we grabbed all the eclasses from plus
	the mapping from eclass name (ie. 'eutils') to the hexdigest of the generated hash.
	"""

	def __init__(self, path):
		self.path = path
		self.hashes = {}


def gen_cache_entry(hub, ebuild_path, metadata_outpath=None, eclass_hashes: EclassHashCollection = None):

	"""
	This function will grab metadata from a single ebuild pointed to by `ebuild_path`.
	`metadata_outpath` will point to something like `/foo/bar/oni-kit/metadata/md5-cache` and is
	where the metadata file will get written. `eclass_hashes` provides our collection of eclass
	md5 hashes which are used to generate the metadata cache.

	This function sets up a clean environment and spawns a bash process which runs `ebuild.sh`,
	which is a file from Portage that processes the ebuild and eclasses and outputs the metadata
	so we can grab it. We do a lot of the environment setup inline in this function for clarity
	(helping the reader understand the process) and also to avoid bunches of function calls.

	TODO: Currently hard-coded to assume a python3.7 installation. We should fix that at some point.
	"""

	env = {}

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
	env["PORTAGE_ECLASS_LOCATIONS"] = eclass_hashes.path
	env["EBUILD"] = ebuild_path
	env["EBUILD_PHASE"] = "depend"
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
	# This tells ebuild.sh to write out the metadata to stdout (fd 1) which is where we will grab
	# it from:
	env["PORTAGE_PIPE_FD"] = "1"
	result = run("/bin/bash " + os.path.join(env["PORTAGE_BIN_PATH"], "ebuild.sh"), env=env)
	infos = {}
	try:
		lines = result.stdout.split("\n")
		line = 0
		while line < len(METADATA_LINES):
			infos[METADATA_LINES[line]] = lines[line]
			line += 1
		basespl = ebuild_path.split("/")
		infos["HASH_KEY"] = metapath = basespl[-3] + "/" + basespl[-1][:-7]
		if metadata_outpath:
			final_md5_outpath = os.path.join(metadata_outpath, metapath)
			os.makedirs(os.path.dirname(final_md5_outpath), exist_ok=True)
			with open(os.path.join(metadata_outpath, metapath), "w") as f:
				for key in AUXDB_LINES:
					if infos[key] != "":
						f.write(key + "=" + infos[key] + "\n")
				# eclasses are recorded in a special way with their md5sums:
				if infos["INHERITED"] != "":
					eclass_out = ""
					for eclass_name in sorted(infos["INHERITED"].split()):
						try:
							eclass_out += f"\t{eclass_name}\t{eclass_hashes.hashes[eclass_name]}"
						except KeyError as ke:
							print(f"When processing {ebuild_path}:")
							print(f"Could not find eclass '{eclass_name}' (from '{infos['INHERITED']}')")
							sys.exit(1)
					f.write("_eclasses_=" + eclass_out[1:] + "\n")
				# final line is the md5sum of the ebuild itself:
				f.write("_md5_=" + get_md5(ebuild_path) + "\n")
	except (FileNotFoundError, IndexError) as e:
		hub.METADATA_ERRORS.append(
			MetadataError(severity=Severity.FATAL, msg="Ebuild triggered exception {e}", ebuild_path=ebuild_path)
		)
		return None
	if result.returncode != 0:
		hub.METADATA_ERRORS.append(
			MetadataError(
				severity=Severity.NONFATAL,
				msg=f"Ebuild had non-zero returncode {result.returncode}",
				ebuild_path=ebuild_path,
				output=result.stderr,
			)
		)
	return infos


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


def gen_cache(hub, eclass_src=None, metadata_out=None, ebuild_src=None):

	"""

	Generate md5-cache metadata from a bunch of ebuilds.

	`eclass_src` should be a path pointing to a kit that has all the eclasses. Typically you point this
	to a `core-kit` that already has all of the eclasses finalized and copied over.

	`metadata_out` tells gencache where to write the metadata. You want to point this to something like
	`/path/to/kit/metadata/md5-cache`.

	`ebuild_src` points to a kit that contains all the ebuilds you want to generate metadata for. You
	just point to the root of the kit and all eclasses are found and metadata is generated.

	"""
	hub.METADATA_ENTRIES = {}

	with ThreadPoolExecutor(max_workers=cpu_count()) as executor:
		count = 0
		futures = []
		fut_map = {}

		eclass_hashes = hub.ECLASS_HASHES
		for ebpath in ebuild_generator(ebuild_src=ebuild_src):
			future = executor.submit(
				hub._.gen_cache_entry, ebuild_path=ebpath, metadata_outpath=metadata_out, eclass_hashes=eclass_hashes,
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
				hub.METADATA_ENTRIES[hash_key] = data

				sys.stdout.write(".")
			sys.stdout.flush()

		print(f"{count} ebuilds processed.")
