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
SUB_FP_MAP_LOCK = asyncio.Lock()
SUB_FP_MAP = {}

# Allow maximum of 8 generators to run at the same time:
ACTIVE_GENERATORS = asyncio.Semaphore(value=8, loop=asyncio.get_event_loop())


def generate_manifests(hub):
	"""
	Once auto-generation is complete, this function will write all stored Manifest data to disk. We do this after
	autogen completes so we can ensure that all necessary ebuilds have been created and we can ensure that these are
	written once for each catpkg, rather than written as each individual ebuild is autogenned (which would create a
	race condition writing to each Manifest file.)
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


async def acquire_sub(hub, subpath):
	async with SUB_FP_MAP_LOCK:
		if subpath in SUB_FP_MAP:
			subname = SUB_FP_MAP[subpath]
		else:
			subname = f"my_sub{len(SUB_FP_MAP)+1}"
			hub.pop.sub.add(static=subpath, subname=subname)
			SUB_FP_MAP[subpath] = subname
	return getattr(hub, subname)


def queue_all_indy_autogens(hub):
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
			{
				"generator_sub_path": subpath,
				"template_path": os.path.join(subpath, "templates"),
				"pkginfo_list": [{"name": pkg_name, "cat": pkg_cat}],
			}
		)


async def gather_pending_tasks(hub, future_list):
	"""
	This function collects completed asyncio coroutines, catches any exceptions recorded during their execution
	and logs them properly.
	"""
	for future in asyncio.as_completed(future_list):
		try:
			result = await future
		except (hub.pkgtools.fetch.FetchError, hub.pkgtools.ebuild.BreezyError) as e:
			_, _, tb = sys.exc_info()
			ERRORS.append((e, traceback.extract_tb(tb)))
		except AssertionError as e:
			_, _, tb = sys.exc_info()
			ERRORS.append((e, traceback.extract_tb(tb)))
		print(f"Task completed - {result}")


async def execute_generator(
	hub, generator_sub_path=None, generator_sub_name="autogen", template_path=None, defaults=None, pkginfo_list=None
):

	await ACTIVE_GENERATORS.acquire()
	RUNNING_QUE = []

	if generator_sub_path:
		# This is an individual autogen.py. First grab the "base sub" (map the path), and then grab the actual sub-
		# module we want by name.
		generator_sub_base = await hub._.acquire_sub(generator_sub_path)
		generator_sub = getattr(generator_sub_base, generator_sub_name)
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

		# Generate some output to let the user know what we're doing:

		if "version" in pkginfo and pkginfo["version"] != "latest":
			print(f"autogen: {pkginfo['cat']}/{pkginfo['name']}-{pkginfo['version']}")
		else:
			print(f"autogen: {pkginfo['cat']}/{pkginfo['name']} (latest)")

		# Start execution of the generator and add it to our list of pending tasks:

		async def lil_coroutine():
			await generator_sub.generate(**pkginfo)
			return pkginfo

		future = lil_coroutine()
		RUNNING_QUE.append(future)

	# Wait for all pending autogens to finish:
	await hub._.gather_pending_tasks(RUNNING_QUE)
	ACTIVE_GENERATORS.release()


def parse_yaml_rule(hub, package_section=None):

	pkginfo_list = []

	if type(package_section) == str:

		# A simple '- pkgname' one-line format:
		#
		# - foobar
		#
		pkginfo_list.append({"name": package_section})

	elif type(package_section) == dict:

		# A more complex format, where the package has sub-settings.
		#
		# - foobar:
		#     val1: blah
		#
		# { 'pkgname' : { 'value1' : 'foo', 'value2' : 'bar' } }

		# Remove extra singleton outer dictionary (see format above)

		package_name = list(package_section.keys())[0]
		pkg_section = list(package_section.values())[0]
		pkg_section["name"] = package_name

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
				v_pkginfo = {"name": package_name}
				v_pkginfo.update(v_pkg_section)
				v_pkginfo["version"] = version
				pkginfo_list.append(v_pkginfo)
		else:
			pkginfo_list.append(pkg_section)

	return pkginfo_list


def queue_all_yaml_autogens(hub):

	"""
	This function finds all autogen.yaml files in the repository and adds work to the `PENDING_QUE` (via calls
	to `parse_yaml_rule`.) This queues up all generators to execute.
	"""

	s, o = subprocess.getstatusoutput("find %s -iname autogen.yaml 2>&1" % hub.CONTEXT.start)
	files = o.split("\n")

	for file in files:
		file = file.strip()
		if not len(file):
			continue
		yaml_base_path = os.path.dirname(file)

		with open(file, "r") as myf:
			for rule_name, rule in safe_load(myf.read()).items():

				if "defaults" in rule:
					defaults = rule["defaults"]
				else:
					defaults = {}

				if "generator" in rule:
					# A built-in generator name has been specified. Goody.
					sub_name = rule["generator"]
					sub_path = None
				else:
					# Use an ad-hoc 'generator.py' generator in the same dir as autogen.yaml:
					sub_name = "generator"
					sub_path = yaml_base_path

				pkginfo_list = []
				for package in rule["packages"]:
					pkginfo_list += hub._.parse_yaml_rule(package_section=package)
				PENDING_QUE.append(
					{
						"generator_sub_name": sub_name,
						"generator_sub_path": sub_path,
						"template_path": os.path.join(yaml_base_path, "templates"),
						"defaults": defaults,
						"pkginfo_list": pkginfo_list,
					}
				)


def load_autogen_config(hub):
	path = os.path.expanduser("~/.autogen")
	if os.path.exists(path):
		with open(path, "r") as f:
			hub.AUTOGEN_CONFIG = yaml.safe_load(f)
	else:
		hub.AUTOGEN_CONFIG = {}


async def execute_all_queued_generators(hub):
	GENERATOR_TASKS = []
	print("PENDING", len(PENDING_QUE))
	print(PENDING_QUE)
	while len(PENDING_QUE):
		task_args = PENDING_QUE.pop(0)
		print("STARTING TASK", task_args)
		gen_task = asyncio.Task(hub._.execute_generator(**task_args))
		GENERATOR_TASKS.append(gen_task)
		print("APPPPPPPPPPPPPPPPPPPPPPPPPPPEND")
	print("GATHERING")
	for task in await asyncio.gather(*GENERATOR_TASKS):
		print("TASK GATHERED DAWG")


async def start(hub, start_path=None, out_path=None, fetcher=None, release=None, kit=None, branch=None):

	"""
	This method will start the auto-generation of packages in an ebuild repository.
	"""
	hub._.load_autogen_config()
	hub.FETCHER = fetcher
	hub.pkgtools.repository.set_context(start_path=start_path, out_path=out_path)
	hub.pop.sub.add("funtoo.cache")
	hub.pop.sub.add("funtoo.generators")
	hub._.queue_all_indy_autogens()
	hub._.queue_all_yaml_autogens()
	await hub._.execute_all_queued_generators()
	print("ALL GENS COMPLETED")
	hub._.generate_manifests()
	return ERRORS


# vim: ts=4 sw=4 noet
