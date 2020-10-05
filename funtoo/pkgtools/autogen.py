#!/usr/bin/env python3
import asyncio
import subprocess
import os
import traceback
import sys

import yaml
from yaml import safe_load
import logging

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

ERRORS = []
PENDING_QUE = []
RUNNING_QUE = []


async def parallelize_pending_tasks(hub):
	"""
	This waits for all asyncio tasks that are in the running QUE. The `BreezyBuild.push` method will actually call the async
	`generate()` method to start processing but will then add the future. This is where we wait for
	completion and also catch exceptions.
	"""
	for future in asyncio.as_completed(RUNNING_QUE):
		try:
			await future
		except (hub.pkgtools.fetch.FetchError, hub.pkgtools.ebuild.BreezyError) as e:
			_, _, tb = sys.exc_info()
			ERRORS.append((e, traceback.extract_tb(tb)))
		except AssertionError as e:
			_, _, tb = sys.exc_info()
			ERRORS.append((e, traceback.extract_tb(tb)))


def generate_manifests(hub):
	"""
	Once auto-generation is complete, this function will write all stored Manifest data to disk. We do this after
	autogen completes so we can ensure that all necessary ebuilds have been created and we can ensure that these
	are written once for each catpkg, rather than written as each individual ebuild is autogenned (which would
	create a race condition writing to each Manifest file.)
	"""
	for manifest_file, manifest_lines in hub.MANIFEST_LINES.items():
		manifest_lines = sorted(list(manifest_lines))
		with open(manifest_file, "w") as myf:
			pos = 0
			while pos < len(manifest_lines):
				if pos != 0:
					myf.write("\n")
				myf.write(manifest_lines[pos])
				pos += 1
		log.debug(f"Manifest {manifest_file} generated.")


def _map_filepath_as_sub(hub, subpath):
	# This method does a special pop trick to temporarily map a path into a sub so we
	# can access autogen.py or generator.py in that directory.
	hub.pop.sub.add(static=subpath, subname="my_catpkg")


def _unmap_sub(hub):
	hub.pop.sub.remove("my_catpkg")


async def queue_indy_autogens(hub):
	"""
	This will find all independent autogens and queue them up in the pending queue.
	"""
	s, o = subprocess.getstatusoutput("find %s -iname autogen.py 2>&1" % hub.CONTEXT.start)
	files = o.split("\n")
	for file in files:
		file = file.strip()
		if not len(file):
			continue

		subpath = os.path.dirname(file)
		if subpath.endswith("metatools"):
			continue

		pkg_name = file.split("/")[-2]
		pkg_cat = file.split("/")[-3]

		PENDING_QUE.append(
			{"generator_sub_path": subpath, "template_path": subpath, "pkginfo_list": [{"name": pkg_name, "cat": pkg_cat}]}
		)


async def run_autogen(hub, generator_sub, pkginfo):
	"""
	This function wraps the call to generate() and will catch any exceptions recorded during the generate() call
	and log them properly.
	"""
	if "version" in pkginfo and pkginfo["version"] != "latest":
		print(f"autogen: {pkginfo['cat']}/{pkginfo['name']}-{pkginfo['version']}")
	else:
		print(f"autogen: {pkginfo['cat']}/{pkginfo['name']} (latest)")
	try:
		await generator_sub.generate(**pkginfo)
	except (hub.pkgtools.fetch.FetchError, hub.pkgtools.ebuild.BreezyError) as e:
		_, _, tb = sys.exc_info()
		ERRORS.append((e, traceback.extract_tb(tb)))
	except AssertionError as e:
		_, _, tb = sys.exc_info()
		ERRORS.append((e, traceback.extract_tb(tb)))


async def execute_generator(
	hub, generator_sub_path=None, generator_sub_name="autogen", template_path=None, defaults=None, pkginfo_list=None
):

	"""
	This function is designed to execute all catpkgs for a specified generator. In the case of an `autogen.py`, then
	the `autogen.py` is its own generator and only one catpkg will be specified in `pkginfo_list`. But if we are
	processing a YAML-based autogen defined in `autogen.yaml`, then there will likely be multiple catpkgs listed in
	`pkginfo_list`.
	"""

	pending_tasks = []
	sub_requires_unmapping = False

	if generator_sub_path:
		# This is an individual autogen.py:
		_map_filepath_as_sub(hub, generator_sub_path)
		generator_sub = getattr(hub.my_catpkg, generator_sub_name)
		sub_requires_unmapping = True
	else:
		# This is an official generator that is built-in to pkgtools:
		generator_sub = getattr(hub.generators, generator_sub_name)

	for base_pkginfo in pkginfo_list:

		# Generate each specified package. First we create the pkginfo data that gets passed to generate. You can see
		# that it can come from multiple places:
		#
		# 1. A generator sub can define a `GLOBAL_DEFAULTS` dictionary that contains global settings. These are
		#    set first.
		#
		# 2. Then, any defaults that are provided to us, which have come from the `defaults:` section of the
		#    autogen.yaml are supplied. (`defaults`, below.)
		#
		# 3. Next, `cat` and `name` settings calculated based on the path of the `autogen.py`, or the settings that
		#    come from the package-specific part of the `autogen.yaml` are added on top. (`base_pkginfo`, below.)

		glob_defs = getattr(generator_sub, "GLOBAL_DEFAULTS", {})
		pkginfo = glob_defs.copy()
		if defaults is not None:
			pkginfo.update(defaults)
		pkginfo.update(base_pkginfo)
		if template_path:
			pkginfo["template_path"] = template_path

		future = hub._.run_autogen(generator_sub, pkginfo)
		pending_tasks.append(future)

	# Wait for all pending autogens to finish:
	await asyncio.gather(*pending_tasks)

	if sub_requires_unmapping:
		_unmap_sub(hub)


async def parse_yaml_rule(hub, package=None, defaults=None, sub_path=None):
	"""
	This method takes a single YAML rule that we've extracted from an autogen.yaml file,
	loads the appropriate generator, and uses it to generate (probably) a bunch of catpkgs.

	This function is async and typically we simply grab the future returned and add it to
	a list of pending tasks which we gather afterwards.
	"""

	pkginfo_list = []

	if type(package) == str:

		# A simple '- pkgname' one-line format:
		#
		# - foobar
		#

		pkginfo_list.append({"name": package})
	elif type(package) == dict:

		# A more complex format, where the package has sub-settings.
		#
		# - foobar:
		#     val1: blah
		#
		# { 'pkgname' : { 'value1' : 'foo', 'value2' : 'bar' } }

		# Remove extra singleton outer dictionary (see format above)

		package = list(package.keys())[0]
		pkg_section = list(package.values())[0]

		# This is even a more complex format, where we have sub-sections based on versions of the package,
		# each with their own settings:
		#
		# - foobar:
		#     versions:
		#       1.2.4:
		#         val1: blah
		#       latest:
		#         val1: bleeeeh

		if type(pkg_section) == dict and "versions" in pkg_section:
			versions_section = pkg_section["versions"]
			for version, v_pkg_section in versions_section.items():
				v_pkginfo = {}
				v_pkginfo.update(v_pkg_section)
				v_pkginfo["version"] = version
				pkginfo_list.append(v_pkginfo)
		else:
			pkginfo_list.append(pkg_section)

	PENDING_QUE.append(
		{"generator_sub_path": sub_path, "template_path": sub_path, "defaults": defaults, "pkginfo_list": pkginfo_list}
	)


async def generate_yaml_autogens(hub):

	"""
	This method finds autogen.yaml files in the repository and executes them. This provides a mechanism
	to perform auto-generation en-masse without needing to have individual autogen.py files all over the
	place.

	Currently supported in the initial implementation are autogen.yaml files existing in *category*
	directories.
	"""

	s, o = subprocess.getstatusoutput("find %s -iname autogen.yaml 2>&1" % hub.CONTEXT.start)
	files = o.split("\n")

	pending_tasks = []
	generator_id = None

	for file in files:
		file = file.strip()
		if not len(file):
			continue
		subpath = os.path.dirname(file)

		# TODO: check for duplicate catpkgs defined in the YAML.

		with open(file, "r") as myf:
			for rule_name, rule in safe_load(myf.read()).items():
				if "defaults" in rule:
					defaults = rule["defaults"]
				else:
					defaults = {}

				if "generator" in rule:
					# use an 'official' generator
					new_generator_id = "official:" + rule["generator"]
				else:
					# use an ad-hoc 'generator.py' generator in the same dir as autogen.yaml:
					new_generator_id = "adhoc:" + subpath

				# We are switching generators -- we need to execute all pending tasks first.

				if generator_id != new_generator_id:
					if len(pending_tasks):
						await asyncio.gather(*pending_tasks)
						pending_tasks = []
					if generator_id is not None and generator_id.startswith("adhoc:"):
						_unmap_sub(hub)

					generator_id = new_generator_id

					# Set up new generator:

					if generator_id.startswith("adhoc:"):
						# Set up ad-hoc generator in generator.py in autogen.yaml path:
						_map_filepath_as_sub(hub, subpath)
						try:
							generator_sub = hub.my_catpkg.generator
						except AttributeError as e:
							log.error("FOOBAR")
							raise
					else:
						# Use an official generator bundled with funtoo-metatools:
						try:
							generator_sub = getattr(hub.generators, rule["generator"])
						except AttributeError as e:
							log.error(f"Could not find specified generator {generator_id}.")
							raise
				for package in rule["packages"]:
					pending_tasks.append(process_yaml_rule(hub, generator_sub, package, defaults, subpath))

	await asyncio.gather(*pending_tasks)


def load_autogen_config(hub):
	path = os.path.expanduser("~/.autogen")
	if os.path.exists(path):
		with open(path, "r") as f:
			hub.AUTOGEN_CONFIG = yaml.safe_load(f)
	else:
		hub.AUTOGEN_CONFIG = {}


async def start(hub, start_path=None, out_path=None, fetcher=None, release=None, kit=None, branch=None):

	"""
	This method will start the auto-generation of packages in an ebuild repository.
	"""
	hub._.load_autogen_config()
	hub.FETCHER = fetcher
	hub.pkgtools.repository.set_context(start_path=start_path, out_path=out_path)
	hub.pop.sub.add("funtoo.cache")
	hub.pop.sub.add("funtoo.generators")
	await generate_individual_autogens(hub)
	await generate_yaml_autogens(hub)
	generate_manifests(hub)
	return ERRORS


# vim: ts=4 sw=4 noet
