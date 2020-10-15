#!/usr/bin/python3

import asyncio
import aiohttp

"""
This sub implements DNS resolution, and is used by the http.py sub.

There is special code in get_resolver() to make sure that the Resolver is in the current ioloop.
Since we use ThreadPools, this is required to ensure that the resolver works for each thread.
"""

RESOLVERS = {}


def get_resolver(hub):
	"""
	This returns a DNS resolver local to the ioloop of the caller.
	"""
	global RESOLVERS
	loop = asyncio.get_event_loop()
	if id(loop) not in RESOLVERS:
		RESOLVERS[id(loop)] = aiohttp.AsyncResolver(nameservers=["1.1.1.1", "1.0.0.1"], timeout=5, tries=3)
	return RESOLVERS[id(loop)]
