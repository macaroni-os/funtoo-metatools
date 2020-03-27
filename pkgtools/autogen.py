#!/usr/bin/env python3

import subprocess
import os
import logging


async def start(hub, start_path=None, out_path=None, name=None, cacher=None, fetcher=None):

	"""
	This method will start the auto-generation of packages in an ebuild repository.
	"""

	hub.pkgtools.repository.set_context(start_path, out_path=out_path, name=name)
	hub.pkgtools.fetch.set_fetcher(fetcher)
	hub.pkgtools.fetch.set_cacher(cacher)

	s, o = subprocess.getstatusoutput("find %s -iname autogen.py 2>&1" % start_path)
	files = o.split('\n')
	for file in files:
		file = file.strip()
		if not len(file):
			continue
		subpath = os.path.dirname(file)
		if subpath.endswith("pkgtools"):
			continue
		hub.pop.sub.add(static=subpath, subname="my_catpkg")

		# TODO: pass repo_name as well as branch to the generate method below:

		pkg_name = file.split("/")[-2]
		pkg_cat = file.split("/")[-3]
		try:
			await hub.my_catpkg.autogen.generate(name=pkg_name, cat=pkg_cat)
		except hub.pkgtools.fetch.FetchError as fe:
			logging.error(fe.msg)
			continue
		except hub.pkgtools.ebuild.BreezyError as be:
			logging.error(be.msg)
			continue
		# we need to wait for all our pending futures before removing the sub:
		await hub.pkgtools.ebuild.parallelize_pending_tasks()
		hub.pop.sub.remove("my_catpkg")

# vim: ts=4 sw=4 noet
