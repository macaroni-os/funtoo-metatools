#!/usr/bin/env python3

import os
from glob import glob
from collections import defaultdict
import itertools

async def get_meson_mappings(hub, ebuild):

	"""
	Returns a list of entries from the meson files -- each entry in the
	list is a tuple containing cpv of our xproto ebuild, the meson package
	name, and the meson version.
	"""
	master_cpv = ebuild.catpkg_version_rev
	artifact = ebuild.artifacts[0]
	await artifact.fetch()
	artifact.extract()
	meson_file = os.path.expanduser(artifact.extract_path + "/*/meson.build")
	meson_file = glob(meson_file)
	if len(meson_file) != 1 or not os.path.exists(meson_file[0]):
		raise hub.pkgtools.ebuild.BreezyError("File not found or too many found: meson.build")
	meson_file = meson_file[0]
	meta_mappings = defaultdict(set)
	for master_cpv, pkg, ver in itertools.chain(
		get_pkgs_from_meson(master_cpv, meson_file),
		get_pkgs_from_meson(master_cpv, meson_file, "legacy_pcs")
	):
		meta_mappings[(pkg, ver)].add(master_cpv)
	artifact.cleanup()
	return meta_mappings

def get_pkgs_from_meson(master_cpv, fn, prefix="pcs"):
	"""
	This is a helper method that grabs package names from meson build files in xproto sources.

	It accepts the master_cpv we are processing as an argument, so we can also
	return it and process the results in a more pipeline-oriented fashion. We
	also accept the arguments ``fn`` -- filename of the meson file, and a
	prefix parameter used to tweak the specific result sets we want to grab
	from the meson file.  """

	capture = False
	with open(fn, "r") as f:
		lines = f.readlines()
		for line in lines:
			ls = line.strip()
			if ls.startswith("%s = [" % prefix):
				capture = True
			elif capture is True:
				if ls == "]":
					break
				else:
					ls = ls.lstrip("[").rstrip("],").split(",")
					pkg = ls[0].strip().strip("'")
					ver = ls[1].strip().strip("'")
					yield master_cpv, pkg, ver

async def generate(hub):

	"""
	The goal here is to generate the xorg-proto ebuild(s) -- as well as a bunch of "stub" ebuilds.
	
	We get the names of the necessary stub ebuilds from the meson.build file which is part of
	the xorg-proto sources.

	First we will extract the xorg-proto tarball and look at meson.build. We will grab the names
	and versions of all the 'stub' ebuilds we need to create.

	We will then add these 'stub' ebuilds to the queue for generation. And finally we will
	generate the xorg-proto ebuild too.

	The 'stub' ebuilds don't actually contain anything. They just will DEPEND on the main
	xorg-proto ebuild. We can in theory have a single stub ebuild that could depend on two
	or more xorg-proto ebuilds using '||' dependencies.

	For example, say xorg-proto-1 and xorg-proto-2 both use fooproto-2.1. The fooproto-2.1
	ebuild will depend on '|| ( x11-base/xorg-proto-2 x11-base/xorg-proto-1 )'

	"""

	ebuild = hub.pkgtools.ebuild.BreezyBuild(
		hub,
		cat="x11-base",
		name="xorg-proto",
		version="2018.4_p20180627",
		revision=2,
		GITHUB_REPO="xorg-xorgproto",
		GITHUB_USER="freedesktop",
		GITHUB_TAG="af9b5f43439378efd1e12d11d487a71f42790fec",
		artifacts = [
			dict(url="https://www.github.com/{GITHUB_USER}/{GITHUB_REPO}/tarball/{GITHUB_TAG}", final_name="{name}-{GITHUB_TAG}.tar.gz")
		]
	)
	ebuild.push()
	template_text = "foo"
	meta_mappings = defaultdict(set)
	for pv_key, new_set in (await get_meson_mappings(hub, ebuild)).items():
		meta_mappings[pv_key] |= new_set

	for pv_key, all_meta_atoms in meta_mappings.items():
		all_meta_atoms = sorted(list(all_meta_atoms))
		sub_ebuild = hub.pkgtools.ebuild.BreezyBuild(
			hub,
			name=pv_key[0],
			cat='x11-proto',
			version=pv_key[1],
			template_vars={ "all_meta_atoms" : all_meta_atoms },
			template_text=template_text
		)
		sub_ebuild.push()

# vim: ts=4 sw=4 noet
