#!/usr/bin/env python3

import asyncio

async def generate(hub):

	url = await hub.pkgtools.fetch.get_url_from_redirect("https://discordapp.com/api/download?platform=linux&format=deb")

	ebuild = hub.pkgtools.ebuild.BreezyBuild(
		hub,
		name="discord",
		cat="net-im",
		version=url.split("/")[-1].lstrip("discord-").rstrip(".deb"),
		artifacts=[ { 'url' : url }]
	)

	ebuild.push()

# vim: ts=4 sw=4 noet
