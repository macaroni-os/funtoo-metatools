#!/usr/bin/env python3
import os

from merge.tree import runShell

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


async def gen_metadata(hub):
	env = {}
	env["PORTAGE_GID"] = "250"
	env["PORTAGE_BIN_PATH"] = "/usr/lib/portage/python3.7"
	env["PORTAGE_ECLASS_LOCATIONS"] = "/var/git/meta-repo/kits/core-kit"
	env["EBUILD"] = "/home/drobbins/development/kit-fixups-dr/core-kit/curated/sys-apps/portage/portage-2.3.78-r1.ebuild"
	env["EBUILD_PHASE"] = "depend"
	env["dbkey"] = "/var/tmp/foob"
	await runShell(os.path.join(env["PORTAGE_BIN_PATH"], "ebuild.sh"), env=env)
	infos = {}
	with open("/var/tmp/foob", "r") as f:
		lines = f.read().split("\n")
		line = 0
		while line < len(METADATA_LINES):
			infos[METADATA_LINES[line]] = lines[line]
			line += 1
	print(infos)
