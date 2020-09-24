#!/usr/bin/python3
import pymongo
from pymongo import MongoClient


def __init__(hub):
	dd = hub.DEEPDIVE = MongoClient().metatools.deepdive
	dd.create_index("atom")
	dd.create_index([("kit", pymongo.ASCENDING), ("category", pymongo.ASCENDING), ("package", pymongo.ASCENDING)])
	dd.create_index("catpkg")
	dd.create_index("relations")
	dd.create_index("md5")


async def populate_deepdive_database(hub):
	hub.DEEPDIVE.delete_many({})
