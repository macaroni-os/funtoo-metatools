#!/usr/bin/env python3

from merge_utils.tree import GitTree


def __init__(hub):
	hub.CURRENT_SOURCE_DEF = None
	hub.SOURCE_REPOS = {}


async def initialize_sources(hub, kit_dict=None):
	source = kit_dict["source"]
	if hub.CURRENT_SOURCE_DEF == source:
		return
	repos = list(hub.merge.foundations.get_repos(source))
	for repo_dict in repos:
		print("Going to initialize", repo_dict)
		repo_name = repo_dict["name"]
		repo_url = repo_dict["url"]
		repo_key = repo_name
		repo_branch = repo_dict["branch"] if "branch" in repo_dict else "master"
		repo_sha1 = repo_dict["src_sha1"] if "src_sha1" in repo_dict else None
		if repo_key in hub.SOURCE_REPOS:
			repo_obj = hub.SOURCE_REPOS[repo_key]
			if repo_sha1:
				await repo_obj.gitCheckout(sha1=repo_sha1)
			elif repo_branch:
				await repo_obj.gitCheckout(branch=repo_branch)
		else:
			path = repo_name
			repo_obj = GitTree(
				hub,
				repo_name,
				url=repo_url,
				root="%s/%s" % (hub.MERGE_CONFIG.source_trees, path),
				branch=repo_branch,
				commit_sha1=repo_sha1,
				origin_check=False,
				reclone=False,
			)
			await repo_obj.initialize()
			hub.SOURCE_REPOS[repo_key] = repo_obj
	hub.CURRENT_SOURCE_DEF = source
