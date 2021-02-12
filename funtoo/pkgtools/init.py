#!/usr/bin/env python3

import os
from collections import defaultdict

import pymongo
import yaml
from pymongo import MongoClient


def load_autogen_config():
	path = os.path.expanduser("~/.autogen")
	if os.path.exists(path):
		with open(path, "r") as f:
			return yaml.safe_load(f)
	else:
		return {}


def __init__(model):
	mc = MongoClient()
	db_name = "metatools"
	model.MONGO_DB = getattr(mc, db_name)
	model.MONGO_FC = model.MONGO_DB.fetch_cache
	model.MONGO_FC.create_index([("method_name", pymongo.ASCENDING), ("url", pymongo.ASCENDING)])
	model.MONGO_FC.create_index("last_failure_on", partialFilterExpression={"last_failure_on": {"$exists": True}})
	model.CHECK_DISK_HASHES = False
	model.AUTOGEN_CONFIG = load_autogen_config()
	model.MANIFEST_LINES = defaultdict(set)
	# This is used to limit simultaneous connections to a particular hostname to a reasonable value.
	model.FETCH_ATTEMPTS = 3
