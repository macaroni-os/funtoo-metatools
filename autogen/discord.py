#!/usr/bin/env python3

import asyncio

async def generate(hub, repo_context):

	class DiscordBuild(hub.pkgtools.ebuild.BreezyBuild):

		cat = "net-im"
		name = "discord"

		async def setup(self):
			url = await hub.pkgtools.fetch.get_url_from_redirect("https://discordapp.com/api/download?platform=linux&format=deb")
			self.artifacts = [ url ]
			self.version = url.split("/")[-1].lstrip("discord-").rstrip(".deb")

	await DiscordBuild(dest=repo_context).generate()

# vim: ts=4 sw=4 noet
