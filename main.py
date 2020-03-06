#!/usr/bin/env python3

import asyncio
import pop.hub

hub = pop.hub.Hub()
hub.pop.sub.add(pypath='pkgtools', omit_class=False)
hub.pop.sub.add(pypath='autogen')

if __name__ == "__main__":
	hub.CALLER_PATH = __file__
	hub.TEMP_PATH = "/var/tmp"
	asyncio.run(hub.pkgtools.autogen.start())

# vim: ts=4 sw=4 noet
