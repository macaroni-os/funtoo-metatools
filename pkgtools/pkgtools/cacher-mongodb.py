#!/usr/bin/env python3

from datetime import datetime

try:
    import pymongo
    import pymongo.errors
    from pymongo import MongoClient
except ImportError:
    pass


"""

We use MongoDB to cache HTTP requests for standard REST and other live data. We also use it to record stats for
artifacts (SRC_URI files) we have downloaded. This is handy for identifying downloads that have failed for some
reason. However, Artifacts don't get cached in MongoDB but are instead written to disk. But we do cache metadata
of the downloaded artifact -- its message digests and size at the time the download was done. This allows us to

1) detect when one of the archives was modified on disk; and
2) regenerate ebuilds even if we don't have archives available (feature not yet implemented, but possible)

"""

__virtualname__ = "FETCH_CACHE"

def __virtual__(hub):
    return hub.OPT.pkgtools['cacher'] == "mongodb"

def __init__(hub):
    mc = MongoClient()
    db_name = "metatools"
    hub.MONGO_DB = getattr(mc, db_name)
    hub.MONGO_FC = hub.MONGO_DB.fetch_cache
    hub.MONGO_FC.create_index([('method_name', pymongo.ASCENDING), ('url', pymongo.ASCENDING)])


async def record_fetch_success(hub, method_name, fetchable):
    # Fetchable can be a simple string (URL) or an Artifact. They are a bit different:
    if type(fetchable) == str:
        url = fetchable
        metadata = None
    else:
        url = fetchable.url
        metadata = fetchable.as_metadata()
    hub.MONGO_FC.update_one({'method_name': method_name, 'url': url},
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
    hub.MONGO_FC.update_one({'method_name': method_name, 'url': url},
                  {'$set': {
                      'last_attempt': datetime.utcnow(),
                      'fetched_on': datetime.utcnow(),
                      'failures': 0,
                      'metadata': metadata,
                      'result': result}
                  },
                  upsert=True)


async def fetch_cache_read(hub, method_name, fetchable, max_age=None, refresh_interval=None):
    # Fetchable can be a simple string (URL) or an Artifact. They are a bit different:
    if type(fetchable) == str:
        url = fetchable
    else:
        url = fetchable.url
    result = hub.MONGO_FC.find_one({'method_name': method_name, 'url': url})
    if result is None or 'fetched_on' not in result:
        return None
    elif refresh_interval is not None:
        if datetime.utcnow() - result['fetched_on'] <= refresh_interval:
            return result
        else:
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
    hub.MONGO_FC.update_one({'method_name': method_name, 'url': fetchable},
                  {'$set': {'last_attempt': datetime.utcnow()},
                   '$inc': {'failures': 1}}, upsert=True)
