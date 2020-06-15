#!/usr/bin/python3

import asyncio
import aiohttp


RESOLVERS = {}

def get_resolver(hub):
	"""
	Resolvers need to be local to the current ioloop. Since we use a ThreadPool, it may not be in the caller's
	ioloop if we just instantiate a global resolver.

	This should return a resolver local to the caller.
	"""
	global RESOLVERS
	loop = asyncio.get_event_loop()
	if id(loop) not in RESOLVERS:
		RESOLVERS[id(loop)] = aiohttp.AsyncResolver(nameservers=['1.1.1.1', '1.0.0.1'], timeout=5, tries=3)
	return RESOLVERS[id(loop)]