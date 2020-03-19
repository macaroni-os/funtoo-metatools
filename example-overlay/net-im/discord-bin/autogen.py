#!/usr/bin/env python3

import asyncio

async def update_metadata(hub):

	url = await hub.pkgtools.fetch.get_url_from_redirect("https://discordapp.com/api/download?platform=linux&format=deb")

	return {
		"name": "discord-bin",
		"cat": "net-im",
		"url": url,
		"version": url.split("/")[-1].lstrip("discord-bin-").rstrip(".deb"),
		"artifacts": [
			dict(url=url)
		]
	}

async def generate(hub, metadata):
	ebuild = await hub.pkgtools.ebuild.BreezyBuild(hub, **metadata)
	await ebuild.generate()

# vim: ts=4 sw=4 noet
