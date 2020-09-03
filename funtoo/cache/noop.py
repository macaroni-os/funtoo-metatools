#!/usr/bin/env python3

__virtualname__ = "fetch"


def __virtual__(hub):
    cacher = getattr(hub, "CACHER", None)
    return cacher in ["noop", None]


def __init__(hub):
    pass


async def fetch_cache_write(hub, method_name, fetchable, body=None, metadata_only=False):
    pass


async def fetch_cache_read(hub, method_name, url, max_age=None, refresh_interval=None):
    raise hub.pkgtools.fetch.CacheMiss()


async def record_fetch_failure(hub, method_name, url):
    pass
