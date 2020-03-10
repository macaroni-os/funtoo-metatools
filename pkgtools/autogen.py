#!/usr/bin/env python3

import subprocess
import os

async def start(hub):

	"""
	This method will start the auto-generation of packages in an ebuild repository.
	"""
	print(hub.OPTS['repo'])
	# TODO: directly use mods/pop/sub.py methods to add subs
	hub.pkgtools.repository.set_context(hub.OPTS['repo'])
	s, o = subprocess.getstatusoutput("find %s -iname autogen.py 2>&1" % hub.OPTS['repo'])
	files = o.split('\n')
	for file in files:
		print(file)
		subpath = os.path.dirname(file)
		if subpath.endswith("pkgtools"):
			continue
		print(subpath)
		hub.pop.sub.add(static=subpath, subname="my_catpkg")
		await hub.my_catpkg.autogen.generate()
		hub.pop.sub.remove("my_catpkg")
	await hub.pkgtools.ebuild.go()


# vim: ts=4 sw=4 noet
