#!/usr/bin/env python3

import sys
import asyncio

async def start(hub):

	"""
	This method will start the auto-generation of packages in an ebuild repository.
	"""

	for mod in hub.autogen:
		if not hasattr(mod, 'generate'):
			continue
		generate = getattr(mod, 'generate')
		hub.pkgtools.repository.set_context(hub.OPTS['repo'])
		await generate()

# vim: ts=4 sw=4 noet
