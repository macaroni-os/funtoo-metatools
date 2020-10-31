#!/usr/bin/python3

# This generator is designed for "simple" pypi cases where we don't need compatibility ebuilds, but we want more
# automation so we don't need a template. It supports general needs for pypi packages that are pretty much just
# standard pypi, plus some deviations.

import json
import os
from collections import OrderedDict

GLOBAL_DEFAULTS = {"cat": "dev-python", "refresh_interval": None, "python_compat": "python3+"}


def add_ebuild(hub, json_dict=None, **pkginfo):
	local_pkginfo = pkginfo.copy()
	hub.pkgtools.pyhelper.expand_pydeps(local_pkginfo)

	if "version" in local_pkginfo and local_pkginfo["version"] != "latest":
		version_specified = True
	else:
		version_specified = False
		# get latest version
		local_pkginfo["version"] = json_dict["info"]["version"]

	artifact_url = hub.pkgtools.pyhelper.pypi_get_artifact_url(local_pkginfo, json_dict, strict=version_specified)

	assert (
		artifact_url is not None
	), f"Artifact URL could not be found in {pkginfo['name']} {local_pkginfo['version']}. This can indicate a PyPi package without a 'source' distribution."

	local_pkginfo["template_path"] = os.path.normpath(os.path.join(os.path.dirname(__file__), "../../templates"))
	ebuild = hub.pkgtools.ebuild.BreezyBuild(
		**local_pkginfo, artifacts=[hub.pkgtools.ebuild.Artifact(url=artifact_url)], template="pypi-simple-1.tmpl"
	)
	ebuild.push()


async def generate(hub, **pkginfo):
	if "pypi_name" in pkginfo:
		pypi_name = pkginfo["pypi_name"]
	else:
		pypi_name = pkginfo["name"]
		pkginfo["pypi_name"] = pypi_name
	json_data = await hub.pkgtools.fetch.get_page(
		f"https://pypi.org/pypi/{pypi_name}/json", refresh_interval=pkginfo["refresh_interval"]
	)
	json_dict = json.loads(json_data, object_pairs_hook=OrderedDict)
	add_ebuild(hub, json_dict, **pkginfo)


# vim: ts=4 sw=4 noet
