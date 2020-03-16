#!/usr/bin/env python3

import subprocess
import os
import logging

async def start(hub, start_path=None, out_path=None, name=None, temp_name=None):

	"""
	This method will start the auto-generation of packages in an ebuild repository.
	"""
	hub.pkgtools.repository.set_context(start_path, out_path=out_path, name=name)
	s, o = subprocess.getstatusoutput("find %s -iname autogen.py 2>&1" % start_path)
	files = o.split('\n')
	for file in files:
		file = file.strip()
		if not len(file):
			continue
		subpath = os.path.dirname(file)
		if subpath.endswith("pkgtools"):
			continue
		logging.info("ADDING SUB: %s" % subpath)
		hub.pop.sub.add(static=subpath, subname="my_catpkg")

		# Attempt to update metadata, but on failure, fall back on our cached metadata:

		try:
			metadata = hub.my_catpkg.autogen.update_metadata()
			hub.pkgtools.metadata.write_metadata(subpath, metadata)
		except hub.pkgtools.ebuild.BreezyError:
			metadata = hub.pkgtools.metadata.get_metadata(subpath)

		await hub.my_catpkg.autogen.generate(metadata)

		# we need to execute all our pending futures before removing the sub:
		await hub.pkgtools.ebuild.go()
		hub.pop.sub.remove("my_catpkg")

# vim: ts=4 sw=4 noet
