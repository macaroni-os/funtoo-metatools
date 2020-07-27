#!/usr/bin/python3

# This generator is designed to generate two ebuilds, one a foo-compat ebuild that provides python2.7 compatibility,
# and the other a foo ebuild that provides python3 compatibility. But the foo ebuild will 'advertise' python2.7
# compatibility as well, and if enabled, it will RDEPEND on foo-compat.
#
# This will allow packages that still expect foo to work with python2.7 to continue to be able to depend upon foo.
# Everything should still work.
#
# When upgrading from an older 'classic' ebuild that has python2.7 compatibility, first the foo ebuild will be
# merged, which will jettison 2.7 support, but immediately afterwards, foo-compat will be merged if needed and
# 2.7 compatibility will be back.

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

def add_ebuild(hub, json_dict=None, compat_ebuild=False, **pkginfo):
	local_pkginfo = pkginfo.copy()
	assert 'python_compat' in local_pkginfo, f'python_compat is not defined in {local_pkginfo}'
	local_pkginfo['compat_ebuild'] = compat_ebuild
	artifact_url = None

	if compat_ebuild:
		local_pkginfo['python_compat'] = 'python2_7'
		local_pkginfo['version'] = local_pkginfo['compat']
		local_pkginfo['name'] = local_pkginfo['name'] + '-compat'
		artifact_url = sdist_artifact_url(json_dict['releases'], local_pkginfo['version'])
	else:
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
		template='pypi-compat-1.tmpl'
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
	add_ebuild(hub, json_dict, compat_ebuild=False, **pkginfo)
	if 'compat' in pkginfo and pkginfo['compat']:
		add_ebuild(hub, json_dict, compat_ebuild=True, **pkginfo)


# vim: ts=4 sw=4 noet
