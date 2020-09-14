#!/usr/bin/env python3
import os

from merge.tree import runShell, run

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
		"INHERITED",
		"IUSE",
		"REQUIRED_USE",
		"PDEPEND",
		"BDEPEND",
		"EAPI",
		"PROPERTIES",
		"DEFINED_PHASES",
	]
)


def strip_rev(s):
	num_strip = s.rstrip("0123456789")
	if num_strip != s and num_strip[-2:] == "-r":
		rev_strip = num_strip[:-2]
		rev = s[len(num_strip) :]
		return rev_strip, rev
	return s, None


def gen_metadata(hub, ebuild_path, md5_outpath=None):
	env = {}
	# enable EAPI 7 functions in ebuild.sh -- ebuild can lower this later...
	env["EAPI"] = "7"
	env["PORTAGE_GID"] = "250"
	env["PORTAGE_BIN_PATH"] = "/usr/lib/portage/python3.7"
	env["PORTAGE_ECLASS_LOCATIONS"] = "/var/git/meta-repo/kits/core-kit"
	env["EBUILD"] = ebuild_path
	env["EBUILD_PHASE"] = "depend"
	env["PF"] = os.path.basename(ebuild_path)[:-7]
	env["CATEGORY"] = ebuild_path.split("/")[-3]
	pkg_only = ebuild_path.split("/")[-2]  # JUST the pkg name "foobar"
	reduced, rev = strip_rev(env["PF"])
	if rev is None:
		env["R"] = "r0"
		pkg_and_ver = env["PF"]
	else:
		env["R"] = f"r{rev}"
		pkg_and_ver = reduced
	env["P"] = pkg_and_ver
	env["PV"] = pkg_and_ver[len(pkg_only) + 1 :]
	env["PN"] = pkg_only
	env["PVR"] = env["PF"][len(env["PN"]) :]
	env["dbkey"] = "/var/tmp/" + os.path.basename(ebuild_path) + ".meta"
	print(env)
	result = run(os.path.join(env["PORTAGE_BIN_PATH"], "ebuild.sh"), env=env)
	infos = {}
	try:
		with open(env["dbkey"], "r") as f:
			lines = f.read().split("\n")
			line = 0
			while line < len(METADATA_LINES):
				infos[METADATA_LINES[line]] = lines[line]
				line += 1
		os.unlink(env["dbkey"])
		if md5_outpath:
			basespl = ebuild_path.split("/")
			metapath = basespl[-3] + "/" + basespl[-1][:-7]
			final_md5_outpath = os.path.join(md5_outpath, metapath)
			os.makedirs(os.path.dirname(final_md5_outpath), exist_ok=True)
			with open(os.path.join(md5_outpath, metapath), "w") as f:
				for key in AUXDB_LINES:
					if infos[key] != "":
						if key == "KEYWORDS":
							k_split = set(infos[key].split())
							my_set = {"amd64", "arm", "arm64", "x86", "~amd64", "~arm", "~arm64", "~x86"}
							k_final = k_split & my_set
							f.write(key + "=" + " ".join(sorted(k_final)) + "\n")
						else:
							f.write(key + "=" + infos[key] + "\n")
	except (FileNotFoundError, IndexError) as e:
		# TODO: ebuild.sh failed for some reason. This should be logged for investigation.
		return "FATAL", None, ""
	if result.returncode == 0 and result.stderr == b"":
		return "OK", infos, ""
	else:
		return "NONFATAL", infos, result.stderr
