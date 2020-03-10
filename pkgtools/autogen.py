#!/usr/bin/env python3

import subprocess
import os

async def start(hub, path=None, name=None):

	"""
	This method will start the auto-generation of packages in an ebuild repository.
	"""
	hub.pkgtools.repository.set_context(path, name=name)
	s, o = subprocess.getstatusoutput("find %s -iname autogen.py 2>&1" % hub.OPTS['repo'])
	files = o.split('\n')
	for file in files:
		subpath = os.path.dirname(file)
		if subpath.endswith("pkgtools"):
			continue
		hub.pop.sub.add(static=subpath, subname="my_catpkg")
		await hub.my_catpkg.autogen.generate()
		hub.pop.sub.remove("my_catpkg")
	await hub.pkgtools.ebuild.go()


# vim: ts=4 sw=4 noet
