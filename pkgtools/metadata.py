#!/usr/bin/env python3

import os
from json import dumps, loads

def get_metadata(hub, path):
	try:
		metafile = os.path.join(path, "metadata.json")
		if not os.path.exists(metafile):
			raise hub.pkgtools.ebuild.BreezyError("Metadata %s does not exist." % metafile)
		with open(metafile, "r") as myf:
			metadata = loads(myf.read())
			return metadata
	except (PermissionError, IOError) as e:
		raise hub.pkgtools.ebuild.BreezyError("Unable to read metadata: %s" % e)


async def write_metadata(hub, path, metadata):
	with open(os.path.join(path, "metadata.json"), "w") as myf:
		myf.write(dumps(metadata))
