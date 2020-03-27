#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import asyncio
from pymongo import MongoClient
import logging
from json import loads

import pop.hub
hub = pop.hub.Hub()
hub.pop.sub.add(dyne_name="pkgtools", omit_class=False)

def autogen_setup():
	hub.pkgtools.ebuild.set_temp_path(hub.OPTS["temp_path"])
	asyncio.run(hub.pkgtools.autogen.start(hub.OPTS['start_path'],
		out_path=hub.OPTS['out_path'],
		name=hub.OPTS['name'],
		fetcher=hub.OPTS['fetcher'],
		cacher=hub.OPTS['cacher']))

async def autogen(root, src_offset=None):
	if src_offset is None:
		src_offset = ""
	autogen_path = os.path.join(root, src_offset)
	assert os.path.exists(autogen_path)
	await hub.pkgtools.autogen.start(autogen_path)

async def runner():
	autogen_setup()
	hub.pkgtools.ebuild.set_temp_path(os.path.join(config.work_path, "autogen"))

def test_foo():
	asyncio.get_event_loop().run_until_complete(runner())

