#!/usr/bin/python3

# This generator is designed for "simple" pypi cases where we don't need compatibility ebuilds, but we want more
# automation so we don't need a template. It supports general needs for pypi packages that are pretty much just
# standard pypi, plus some deviations.

import json
import os
from collections import OrderedDict

GLOBAL_DEFAULTS = {
	'cat': 'dev-python',
	'refresh_interval': None,
	'python_compat': 'python3+'
}

def sdist_artifact_url(releases, version):
	# Sometimes a version does not have a source tarball. This function lets us know if our version is legit.
	# Returns artifact_url for version, or None if no sdist release was available.
	for artifact in releases[version]:
		if artifact['packagetype'] == 'sdist':
			return artifact['url']
	return None

def add_ebuild(hub, json_dict=None, **pkginfo):
	local_pkginfo = pkginfo.copy()
	artifact_url = None

	if 'version' not in local_pkginfo or local_pkginfo['version'] == 'latest':
		local_pkginfo['version'] = json_dict['info']['version']
		artifact_url = sdist_artifact_url(json_dict['releases'], local_pkginfo['version'])
		if artifact_url is None:
			# dang, the latest official release doesn't have a source tarball. Let's scan for the most recent release with a source tarball:
			for version in reversed(json_dict['releases'].keys()):
				print(f"TRYING {local_pkginfo['name']} {version}")
				artifact_url = sdist_artifact_url(json_dict['releases'], version)
				if artifact_url is not None:
					local_pkginfo['version'] = version
					break
		else:
			artifact_url = sdist_artifact_url(json_dict['releases'], local_pkginfo['version'])
	assert artifact_url is not None, f"Artifact URL could not be found in {pkginfo['name']} {local_pkginfo['version']}. This can indicate a PyPi package without a 'source' distribution."
	local_pkginfo['template_path'] = os.path.normpath(os.path.join(os.path.dirname(__file__), '../../templates'))
	ebuild = hub.pkgtools.ebuild.BreezyBuild(
		**local_pkginfo,
		artifacts=[
			hub.pkgtools.ebuild.Artifact(url=artifact_url)
		],
		template='pypi-simple-1.tmpl'
	)
	ebuild.push()

async def generate(hub, **pkginfo):
	if 'pypi_name' in pkginfo:
		pypi_name = pkginfo['pypi_name']
	else:
		pypi_name = pkginfo['name']
		pkginfo['pypi_name'] = pypi_name
	json_data = await hub.pkgtools.fetch.get_page(f'https://pypi.org/pypi/{pypi_name}/json', refresh_interval=pkginfo['refresh_interval'])
	json_dict = json.loads(json_data, object_pairs_hook=OrderedDict)
	add_ebuild(hub, json_dict, **pkginfo)

# vim: ts=4 sw=4 noet
