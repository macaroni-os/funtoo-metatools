#!/usr/bin/env python3


async def generate(hub, **pkginfo):
	url = await hub.pkgtools.fetch.get_url_from_redirect("https://discordapp.com/aaaapi/download?platform=linux&format=deb")
	hub.pkgtools.ebuild.BreezyBuild(hub,
		**pkginfo,
		url=url,
		version=url.split("/")[-1].lstrip("discord-bin-").rstrip(".deb"),
		artifacts=[
			dict(url=url)
		]
	).push()

# vim: ts=4 sw=4 noet
