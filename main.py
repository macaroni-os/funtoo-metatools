#!/usr/bin/env python3

import asyncio
import pop.hub

hub = pop.hub.Hub()
hub.pop.sub.add(pypath='pkgtools', omit_class=False)
hub.pop.sub.add(pypath='autogen')
hub.pop.sub.extend('autogen', pypath='another-autogen')
hub.pop.sub.add('pop.mods.conf')

CONFIG = {
	"repo" : {
		'default' : __file__,
		'os': 'AUTOGEN_REPOSITORY',
		'help' : 'Destination repository path'
	},
	"temp" : {
		"default" : "/var/tmp",
		'os' : 'AUTOGEN_TEMP',
		'help' : 'Temporary download path'
	}
}

if __name__ == "__main__":
	hub.OPTS = hub.conf.reader.read(CONFIG)
	asyncio.run(hub.pkgtools.autogen.start())

# vim: ts=4 sw=4 noet
