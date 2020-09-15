#!/usr/bin/env python3
import hashlib
import os
import re
import sys

from merge_utils.tree import run


class MetadataError:
	def __init__(self, ebuild_path=None, msg=None):
		self.ebuild_path = ebuild_path
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


def get_md5(hub, filename):
	h = hashlib.md5()
	with open(filename, "rb") as f:
		h.update(f.read())
	return h.hexdigest()


def strip_rev(s):
	num_strip = s.rstrip("0123456789")
	if num_strip != s and num_strip[-2:] == "-r":
		rev_strip = num_strip[:-2]
		rev = s[len(num_strip) :]
		return rev_strip, rev
	return s, None


def get_eapi_of_ebuild(hub, ebuild_path):
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


def gen_metadata(hub, ebuild_path, metadata_outpath=None, eclass_hashes=None):
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
	reduced, rev = strip_rev(env["PF"])
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
	env["dbkey"] = "/var/tmp/" + os.path.basename(ebuild_path) + ".meta"
	result = run("/bin/bash " + os.path.join(env["PORTAGE_BIN_PATH"], "ebuild.sh"), env=env)
	infos = {}
	try:
		with open(env["dbkey"], "r") as f:
			lines = f.read().split("\n")
			line = 0
			while line < len(METADATA_LINES):
				infos[METADATA_LINES[line]] = lines[line]
				line += 1
		os.unlink(env["dbkey"])
		if metadata_outpath:
			basespl = ebuild_path.split("/")
			metapath = basespl[-3] + "/" + basespl[-1][:-7]
			final_md5_outpath = os.path.join(metadata_outpath, metapath)
			os.makedirs(os.path.dirname(final_md5_outpath), exist_ok=True)
			with open(os.path.join(metadata_outpath, metapath), "w") as f:
				for key in AUXDB_LINES:
					if infos[key] != "":
						f.write(key + "=" + infos[key] + "\n")
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
				f.write("_md5_=" + hub._.get_md5(ebuild_path) + "\n")
	except (FileNotFoundError, IndexError) as e:
		# TODO: ebuild.sh failed for some reason. This should be logged for investigation.
		return "FATAL", None, ""
	if result.returncode == 0 and result.stderr == b"":
		return "OK", infos, ""
	else:
		return "NONFATAL", infos, result.stderr
