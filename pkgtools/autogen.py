#!/usr/bin/env python3

import subprocess
import os
import logging

async def start(hub, start_path=None, out_path=None, name=None, update=False, cache_path=None):

	"""
	This method will start the auto-generation of packages in an ebuild repository.
	"""
	hub.pkgtools.repository.set_context(start_path, out_path=out_path, name=name)
	hub.pkgtools.ebuild.set_cache_path(cache_path)
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

		metadata = None

		# If update is False, then we simply attempt to read the cached metadata on disk rather than
		# updating it:

		if not update:
			try:
				metadata = hub.pkgtools.metadata.get_metadata(subpath)
			except hub.pkgtools.ebuild.BreezyError as e:
				pass

		# Now, if the previous non-update read of metadata failed, or we are in update mode, we will
		# attempt to generate/update the metadata on disk:

		if metadata is None:
			try:
				metadata = await hub.my_catpkg.autogen.update_metadata()
				print("GOT METADATA", metadata)
				await hub.pkgtools.metadata.write_metadata(subpath, metadata)
			except hub.pkgtools.ebuild.BreezyError:
				metadata = hub.pkgtools.metadata.get_metadata(subpath)

		# TODO: check digests
		await hub.my_catpkg.autogen.generate(metadata)

		# we need to execute all our pending futures before removing the sub:
		await hub.pkgtools.ebuild.go()
		hub.pop.sub.remove("my_catpkg")

# vim: ts=4 sw=4 noet
