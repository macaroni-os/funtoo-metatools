#!/usr/bin/env python3

from datetime import datetime
import dyne.org.funtoo.metatools.merge as merge


def get_kit_pre_post_steps(ctx):
	kit_steps = {
		"core-kit": {
			"pre": [
				merge.steps.GenerateRepoMetadata("core-kit", aliases=["gentoo"], priority=1000),
				# core-kit has special logic for eclasses -- we want all of them, so that third-party overlays can reference the full set.
				# All other kits use alternate logic (not in kit_steps) to only grab the eclasses they actually use.
				merge.steps.SyncDir(merge.model.source_repos["gentoo-staging"].root, "eclass"),
			],
			"post": [
				merge.steps.ThirdPartyMirrors(),
				merge.steps.RunSed(["profiles/base/make.defaults"], ["/^PYTHON_TARGETS=/d", "/^PYTHON_SINGLE_TARGET=/d"]),
			],
		},
		# masters of core-kit for regular kits and nokit ensure that masking settings set in core-kit for catpkgs in other kits are applied
		# to the other kits. Without this, mask settings in core-kit apply to core-kit only.
		"regular-kits": {
			"pre": [
				merge.steps.GenerateRepoMetadata(ctx.kit.name, masters=["core-kit"], priority=500),
			]
		},
		"all-kits": {
			"pre": [
				merge.steps.SyncFiles(
					merge.model.kit_fixups.root,
					{
						"LICENSE.txt": "LICENSE.txt",
					},
				),
			]
		},
		"nokit": {
			"pre": [
				merge.steps.GenerateRepoMetadata("nokit", masters=["core-kit"], priority=-2000),
			]
		},
	}

	out_pre_steps = []
	out_post_steps = []

	kd = ctx.kit.name
	if kd in kit_steps:
		if "pre" in kit_steps[kd]:
			out_pre_steps += kit_steps[kd]["pre"]
		if "post" in kit_steps[kd]:
			out_post_steps += kit_steps[kd]["post"]

	# a 'regular kit' is not core-kit or nokit -- if we have pre or post steps for them, append these steps:
	if kd not in ["core-kit", "nokit"] and "regular-kits" in kit_steps:
		if "pre" in kit_steps["regular-kits"]:
			out_pre_steps += kit_steps["regular-kits"]["pre"]
		if "post" in kit_steps["regular-kits"]:
			out_post_steps += kit_steps["regular-kits"]["post"]

	if "all-kits" in kit_steps:
		if "pre" in kit_steps["all-kits"]:
			out_pre_steps += kit_steps["all-kits"]["pre"]
		if "post" in kit_steps["all-kits"]:
			out_post_steps += kit_steps["all-kits"]["post"]

	return out_pre_steps, out_post_steps


def get_copyright_rst(active_repo_names):
	cur_year = str(datetime.now().year)
	out = merge.model.foundation_data["copyright"]["default"].replace("{{cur_year}}", cur_year)
	for overlay in sorted(active_repo_names):
		if overlay in merge.model.foundation_data["copyright"]:
			out += merge.model.foundation_data["copyright"][overlay].replace("{{cur_year}}", cur_year)
	return out




