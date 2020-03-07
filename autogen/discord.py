#!/usr/bin/env python3

import asyncio

async def setup(hub, builder):
	url = await hub.pkgtools.fetch.get_url_from_redirect("https://discordapp.com/api/download?platform=linux&format=deb")
	builder.artifacts = [ url ]
	builder.version = url.split("/")[-1].lstrip("discord-").rstrip(".deb")

async def generate(hub, tree):
	hub.pkgtools.ebuild.push(
		name="discord",
		cat="net-im",
		setup=setup
	)

# vim: ts=4 sw=4 noet
