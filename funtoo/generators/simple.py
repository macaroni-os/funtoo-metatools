#!/usr/bin/python3

GLOBAL_DEFAULTS = {}

import dyne.org.funtoo.metatools.pkgtools as pkgtools


async def generate(hub, **pkginfo):
	ebuild = pkgtools.ebuild.BreezyBuild(**pkginfo)
	ebuild.push()


# vim: ts=4 sw=4 noet
