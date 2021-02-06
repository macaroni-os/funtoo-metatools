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


def __init__(hub):
	mc = MongoClient()
	db_name = "metatools"
	hub.MONGO_DB = getattr(mc, db_name)
	hub.MONGO_FC = hub.MONGO_DB.fetch_cache
	hub.MONGO_FC.create_index([("method_name", pymongo.ASCENDING), ("url", pymongo.ASCENDING)])
	hub.MONGO_FC.create_index("last_failure_on", partialFilterExpression={"last_failure_on": {"$exists": True}})

	hub.AUTOGEN_CONFIG = load_autogen_config()
	hub.MANIFEST_LINES = defaultdict(set)
	# This is used to limit simultaneous connections to a particular hostname to a reasonable value.
	hub.FETCH_ATTEMPTS = 3
