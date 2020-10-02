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
QUE = []


async def parallelize_pending_tasks(hub):
	for future in asyncio.as_completed(QUE):
		try:
			await future
		except (hub.pkgtools.fetch.FetchError, hub.pkgtools.ebuild.BreezyError) as e:
			_, _, tb = sys.exc_info()
			ERRORS.append((e, traceback.extract_tb(tb)))
		except AssertionError as e:
			_, _, tb = sys.exc_info()
			ERRORS.append((e, traceback.extract_tb(tb)))


def generate_manifests(hub):
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


async def generate_individual_autogens(hub):
	"""
	This method finds individual autogen.py files in the current repository path and runs them all.
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
		# TODO: pass repo_name as well as branch to the generate method below:

		_map_filepath_as_sub(hub, subpath)

		pkg_name = file.split("/")[-2]
		pkg_cat = file.split("/")[-3]
		try:
			await hub.my_catpkg.autogen.generate(name=pkg_name, cat=pkg_cat, path=subpath)
		except hub.pkgtools.fetch.FetchError as fe:
			log.error(repr(fe))
			continue
		except hub.pkgtools.ebuild.BreezyError as be:
			log.error(be.msg)
			continue
		except Exception as e:
			log.error("Encountered problem in autogen script: \n\n" + traceback.format_exc())
			continue
		# we need to wait for all our pending futures before removing the sub:
		await parallelize_pending_tasks(hub)
		_unmap_sub(hub)


async def run_autogen(hub, sub, pkginfo):
	try:
		await sub.generate(**pkginfo)
	except (hub.pkgtools.fetch.FetchError, hub.pkgtools.ebuild.BreezyError) as e:
		_, _, tb = sys.exc_info()
		ERRORS.append((e, traceback.extract_tb(tb)))
	except AssertionError as e:
		_, _, tb = sys.exc_info()
		ERRORS.append((e, traceback.extract_tb(tb)))


async def process_yaml_rule(hub, generator_sub, package=None, defaults=None, subpath=None):
	"""
	This method takes a single YAML rule that we've extracted from an autogen.yaml file,
	loads the appropriate generator, and uses it to generate (probably) a bunch of catpkgs.
	"""
	glob_defs = getattr(generator_sub, "GLOBAL_DEFAULTS", {})
	pkginfo = glob_defs.copy()
	pkginfo.update(defaults)
	pkginfo["template_path"] = os.path.join(subpath, "templates")
	pkginfo["path"] = subpath

	if type(package) == str:
		# simple '- pkgname' format.
		pkginfo["name"] = package
		await run_autogen(hub, generator_sub, pkginfo)
	elif type(package) == dict:

		# more complex format.
		# if any sub-arguments are specified with the package, we get it in this format:
		# { 'pkgname' : { 'value1' : 'foo', 'value2' : 'bar' } }

		pkginfo["name"] = list(package.keys())[0]
		pkg_section = list(package.values())[0]
		versions_section = None

		if type(pkg_section) == dict and "versions" in pkg_section:
			versions_section = pkg_section["versions"]

		if versions_section:

			for version, v_pkg_section in versions_section.items():
				v_pkginfo = pkginfo.copy()
				v_pkginfo["version"] = version
				v_pkginfo.update(v_pkg_section)
				await run_autogen(hub, generator_sub, v_pkginfo)
		else:
			pkginfo.update(pkg_section)
			print(f"autogen: {pkginfo['cat']}/{pkginfo['name']}")
			await run_autogen(hub, generator_sub, pkginfo)

	await parallelize_pending_tasks(hub)


async def generate_yaml_autogens(hub):
	"""
	This method finds autogen.yaml files in the repository and executes them. This provides a mechanism
	to perform autogeneration en-masse without needing to have individual autogen.py files all over the
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


async def start(hub, start_path=None, out_path=None, temp_path=None, cacher=None, fetcher=None):

	"""
	This method will start the auto-generation of packages in an ebuild repository.
	"""
	hub._.load_autogen_config()
	hub.CACHER = cacher
	hub.FETCHER = fetcher
	hub.TEMP_PATH = temp_path
	hub.pkgtools.repository.set_context(start_path=start_path, out_path=out_path)
	hub.pop.sub.add("funtoo.cache")
	hub.pop.sub.add("funtoo.generators")
	await generate_individual_autogens(hub)
	await generate_yaml_autogens(hub)
	generate_manifests(hub)
	return ERRORS


# vim: ts=4 sw=4 noet
