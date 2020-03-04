#!/usr/bin/env python3

import pop.hub
hub = pop.hub.Hub()
hub.pop.sub.add('pkgtools', omit_class=False)

class DiscordBuild(hub.pkgtools.ebuild.BreezyBuild):

	cat = "net-im"
	name = "discord"

	def setup(self):
		url = hub.pkgtools.fetch.get_url_from_redirect("https://discordapp.com/api/download?platform=linux&format=deb")
		self.artifacts = [ url ]
		self.version = url.split("/")[-1].lstrip("discord-").rstrip(".deb")


hub.pkgtools.ebuild.say_hello("hi")

if __name__ == "__main__":
	DiscordBuild().generate()

# vim: ts=4 sw=4 noet
