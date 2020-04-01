#!/usr/bin/env python3

import subprocess
import os
import logging
import traceback


async def start(hub, start_path=None, out_path=None):

	"""
	This method will start the auto-generation of packages in an ebuild repository.
	"""

	hub.pkgtools.repository.set_context(
		start_path if start_path is not None else hub.OPT.pkgtools.start_path,
		out_path=out_path if out_path is not None else hub.OPT.pkgtools.out_path, name=hub.OPT.pkgtools.name)

	s, o = subprocess.getstatusoutput("find %s -iname autogen.py 2>&1" % hub.OPT.pkgtools['start_path'])
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
		except Exception as e:
			logging.error("Encountered problem in autogen script: \n\n" + traceback.format_exc())
			continue
		# we need to wait for all our pending futures before removing the sub:
		await hub.pkgtools.ebuild.parallelize_pending_tasks()
		hub.pop.sub.remove("my_catpkg")

		for manifest_file, manifest_lines in hub.MANIFEST_LINES.items():
			manifest_lines = sorted(list(manifest_lines))
			with open(manifest_file, "w") as myf:
				pos = 0
				while pos < len(manifest_lines):
					if pos != 0:
						myf.write('\n')
					myf.write(manifest_lines[pos])
					pos += 1
			logging.debug(f"Manifest {manifest_file} generated.")

# vim: ts=4 sw=4 noet
