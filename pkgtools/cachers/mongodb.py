#!/usr/bin/env python3

from datetime import datetime
import pymongo
import pymongo.errors
from pymongo import MongoClient

DB = MongoClient().funtoo_metatools


def __init__(hub):
    DB.fetch_cache.create_index([('method_name', pymongo.ASCENDING), ('url', pymongo.ASCENDING)])


async def record_fetch_success(hub, method_name, url):
    DB.update_one({'method_name': method_name, 'url': url},
                  {'$set': {'last_attempt': datetime.utcnow(), 'failures': 0}}, upsert=True)


async def fetch_cache_write(hub, method_name, url, result):
    DB.update_one({'method_name': method_name, 'url': url},
                  {'$set': {
                      'last_attempt': datetime.utcnow(),
                      'fetched_on': datetime.utcnow(),
                      'failures': 0,
                      'result': result}
                  },
                  upsert=True)


async def fetch_cache_read(hub, method_name, url, max_age=None):
    result = DB.find_one({'method_name': method_name, 'url': url})
    if 'fetched_on' not in result:
        return None
    elif max_age is not None and datetime.utcnow() - result['fetched_on'] > max_age:
        return None
    else:
        return result


async def record_fetch_failure(hub, method_name, url):
    DB.update_one({'method_name': method_name, 'url': url},
                  {'$set': {'last_attempt': datetime.utcnow()},
                   '$inc': {'failures': 1}})


async def metadata_cache_write(hub, repo_name, branch, catpkg, metadata):
    # TODO: for writing out metadata into an easy-to-query format.
    pass

async def metadata_cache_read(hub, repo_name, branch, catpkg)
    # TODO: see above.
    pass