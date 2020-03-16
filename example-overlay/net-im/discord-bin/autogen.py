#!/usr/bin/env python3

import asyncio

async def create_metadata(hub):

	url = await hub.pkgtools.fetch.get_url_from_redirect("https://discordapp.com/api/download?platform=linux&format=deb")

	return {
		"name" : "discord-bin",
		"cat" : "net-im",
		"url" : url,
		"version" : url.split("/")[-1].lstrip("discord-bin-").rstrip(".deb"),
		"artifacts" : [hub.pkgtools.ebuild.Artifact(url=url)]
	}

async def generate(hub, metadata):
	ebuild = hub.pkgtools.ebuild.BreezyBuild(**metadata)
	ebuild.generate()

# vim: ts=4 sw=4 noet
