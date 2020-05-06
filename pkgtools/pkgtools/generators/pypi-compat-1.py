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

GLOBAL_DEFAULTS = {
	'cat': 'dev-python',
	'refresh_interval': None,
	'python_compat': 'python3+'
}

def add_ebuild(hub, json_dict=None, compat_ebuild=False, **pkginfo):
	local_pkginfo = pkginfo.copy()
	assert 'python_compat' in local_pkginfo, f'python_compat is not defined in {local_pkginfo}'
	local_pkginfo['compat_ebuild'] = compat_ebuild
	if compat_ebuild:
		local_pkginfo['python_compat'] = 'python2_7'
		local_pkginfo['version'] = local_pkginfo['compat']
		local_pkginfo['name'] = local_pkginfo['name'] + '-compat'
	else:
		#local_pkginfo['python_compat'] += ' python2_7'
		if 'version' not in local_pkginfo or local_pkginfo['version'] == 'latest':
			local_pkginfo['version'] = json_dict['info']['version']
	artifact_url = None
	for artifact in json_dict['releases'][local_pkginfo['version']]:
		if artifact['packagetype'] == 'sdist':
			artifact_url = artifact['url']
			break
	assert artifact_url is not None, f"Artifact URL could not be found in {pkginfo['name']}. This can indicate a PyPi package without a 'source' distribution."
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
	json_dict = json.loads(json_data)
	add_ebuild(hub, json_dict, compat_ebuild=False, **pkginfo)
	add_ebuild(hub, json_dict, compat_ebuild=True, **pkginfo)


# vim: ts=4 sw=4 noet
