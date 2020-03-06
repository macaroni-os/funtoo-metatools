#!/usr/bin/env python3

import sys
import asyncio

async def start(hub):

	"""
	This method will start the auto-generation of packages in an ebuild repository.
	"""

	repo_context = hub.pkgtools.repository.repository_of(hub.OPTS['repo'])
	if repo_context is None:
		print("Could not determine what respository I'm in. Exiting.")
		sys.exit(1)
	futures = []
	for mod in hub.autogen:
		if not hasattr(mod, 'generate'):
			continue
		func = getattr(mod, 'generate')
		await func(repo_context=repo_context)

# vim: ts=4 sw=4 noet
