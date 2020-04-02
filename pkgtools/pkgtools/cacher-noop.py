#!/usr/bin/env python3

__virtualname__ = "FETCH_CACHE"


def __virtual__(hub):
    return hub.OPT.pkgtools['cacher'] == "noop"


def __init__(hub):
    pass


async def fetch_cache_write(hub, method_name, fetchable, body=None, metadata_only=False):
    pass


async def fetch_cache_read(hub, method_name, url, max_age=None, refresh_interval=None):
    raise hub.pkgtools.fetch.CacheMiss()


async def record_fetch_failure(hub, method_name, url):
    pass
