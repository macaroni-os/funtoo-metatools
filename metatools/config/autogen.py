import logging
import os
from collections import defaultdict
from datetime import timedelta

import pymongo
import yaml

from metatools.config.base import MinimalConfig
from metatools.config.mongodb import get_collection
from metatools.context import Locator
from metatools.fastpull.blos import BaseLayerObjectStore
from metatools.fastpull.core import IntegrityDatabase
from metatools.fastpull.spider import WebSpider
from metatools.pretty_logging import TornadoPrettyLogFormatter


def fetch_cache():
	fc = get_collection('fetch_cache')
	fc.create_index([("method_name", pymongo.ASCENDING), ("url", pymongo.ASCENDING)])
	fc.create_index("last_failure_on", partialFilterExpression={"last_failure_on": {"$exists": True}})
	return fc


class AutogenConfig(MinimalConfig):
	"""
	This class is used for the autogen workflow -- i.e. the 'doit' command.
	"""
	locator = None
	fetch_cache = fetch_cache()
	fetch_cache_interval = timedelta(minutes=15)
	check_disk_hashes = False
	manifest_lines = defaultdict(set)
	fetch_attempts = 3
	config = None
	kit_spy = None
	spider = None
	fpos = None
	fastpull_scope = None
	fastpull_session = None
	hashes = None

	config_files = {
		"autogen": "~/.autogen"
	}

	async def initialize(self, start_path=None, out_path=None, fetch_cache_interval=None, fastpull_scope=None):
		self.fastpull_scope = fastpull_scope
		if fetch_cache_interval:
			# use our default unless another timedelta specified:
			self.fetch_cache_interval = fetch_cache_interval
		self.start_path = start_path
		self.out_path = out_path
		# kit_spy is used for creating an autogen ID:
		# 			task_args["autogen_id"] = f"{pkgtools.model.kit_spy}:{task_args['gen_path'][len(base)+1:]}"
		# The autogen_id is intended to be used in the distfile integrity database, to tell use which autogen
		# referenced the artifact, in the situation where we don't have a specific BreezyBuild. This was a recent
		# add and may not be fully implemented or make sense based on our current architecture -- needs review
		# so TODO
		#self.kit_spy = None
		self.config = yaml.safe_load(self.get_file("autogen"))
		self.hashes = {'sha512', 'size', 'blake2b', 'sha256'}
		self.blos = BaseLayerObjectStore(self.fastpull_path, hashes=self.hashes)
		self.spider = WebSpider(os.path.join(self.temp_path, "spider"), hashes=self.hashes)
		# This turns on periodic logging of active downloads (to get rid of 'dots')
		await self.spider.start_asyncio_tasks()
		self.fpos = IntegrityDatabase(
			blos=self.blos,
			spider=self.spider,
			hashes=self.hashes
		)
		self.log = logging.getLogger('metatools.autogen')
		self.log.propagate = False
		self.log.setLevel(logging.INFO)
		channel = logging.StreamHandler()
		channel.setFormatter(TornadoPrettyLogFormatter())
		self.log.addHandler(channel)
		self.fastpull_session = self.fpos.get_scope(self.fastpull_scope)
		self.log.debug(f"Fetch cache interval set to {self.fetch_cache_interval}")
		self.locator = Locator(start_path, out_path=out_path)

		repo_name = None
		repo_name_path = os.path.join(self.locator.context, "profiles/repo_name")
		if os.path.exists(repo_name_path):
			with open(repo_name_path, "r") as repof:
				repo_name = repof.read().strip()

		if repo_name is None:
			logging.warning("Unable to find %s." % repo_name_path)

