#!/usr/bin/env python3

from datetime import datetime
import pymongo
import pymongo.errors
from pymongo import MongoClient

DB = MongoClient().funtoo_metatools.fetch_cache

"""

We use MongoDB to cache HTTP requests for standard REST and other live data. We also use it to record stats for
artifacts (SRC_URI files) we have downloaded. This is handy for identifying downloads that have failed for some
reason. However, Artifacts don't get cached in MongoDB but are instead written to disk. But we do cache metadata
of the downloaded artifact -- its message digests and size at the time the download was done. This allows us to

1) detect when one of the archives was modified on disk; and
2) regenerate ebuilds even if we don't have archives available (feature not yet implemented, but possible)

"""

def __init__(hub):
    DB.create_index([('method_name', pymongo.ASCENDING), ('url', pymongo.ASCENDING)])


async def record_fetch_success(hub, method_name, fetchable):
    # Fetchable can be a simple string (URL) or an Artifact. They are a bit different:
    if type(fetchable) == str:
        url = fetchable
        metadata = None
    else:
        url = fetchable.url
        metadata = fetchable.as_metadata()
    DB.update_one({'method_name': method_name, 'url': url},
                  {'$set': {'last_attempt': datetime.utcnow(), 'failures': 0, 'metadata': metadata}},
                  upsert=True)


async def fetch_cache_write(hub, method_name, fetchable, result):
    # Fetchable can be a simple string (URL) or an Artifact. They are a bit different:
    if type(fetchable) == str:
        url = fetchable
        metadata = None
    else:
        url = fetchable.url
        metadata = fetchable.as_metadata()
    DB.update_one({'method_name': method_name, 'url': url},
                  {'$set': {
                      'last_attempt': datetime.utcnow(),
                      'fetched_on': datetime.utcnow(),
                      'failures': 0,
                      'metadata': metadata,
                      'result': result}
                  },
                  upsert=True)


async def fetch_cache_read(hub, method_name, fetchable, max_age=None):
    # Fetchable can be a simple string (URL) or an Artifact. They are a bit different:
    if type(fetchable) == str:
        url = fetchable
    else:
        url = fetchable.url
    result = DB.find_one({'method_name': method_name, 'url': url})
    if result is None or 'fetched_on' not in result:
        return None
    elif max_age is not None and datetime.utcnow() - result['fetched_on'] > max_age:
        return None
    else:
        return result


async def record_fetch_failure(hub, method_name, fetchable):
    # Fetchable can be a simple string (URL) or an Artifact. They are a bit different:
    if type(fetchable) == str:
        url = fetchable
    else:
        url = fetchable.url
    DB.update_one({'method_name': method_name, 'url': fetchable},
                  {'$set': {'last_attempt': datetime.utcnow()},
                   '$inc': {'failures': 1}}, upsert=True)
