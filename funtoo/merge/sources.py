#!/usr/bin/env python3
from concurrent.futures import as_completed
from concurrent.futures.thread import ThreadPoolExecutor

from merge_utils.tree import GitTree


def __init__(hub):
	hub.CURRENT_SOURCE_DEF = None
	hub.SOURCE_REPOS = {}


def initialize_repo(hub, repo_dict):
	print("Going to initialize", repo_dict)
	repo_name = repo_dict["name"]
	repo_url = repo_dict["url"]
	repo_key = repo_name
	repo_branch = repo_dict["branch"] if "branch" in repo_dict else "master"
	repo_sha1 = repo_dict["src_sha1"] if "src_sha1" in repo_dict else None
	if repo_key in hub.SOURCE_REPOS:
		repo_obj = hub.SOURCE_REPOS[repo_key]
		if repo_sha1:
			repo_obj.gitCheckout(sha1=repo_sha1)
		elif repo_branch:
			repo_obj.gitCheckout(branch=repo_branch)
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
		repo_obj.initialize()
		hub.SOURCE_REPOS[repo_key] = repo_obj


async def initialize_sources(hub, source):
	if hub.CURRENT_SOURCE_DEF == source:
		return
	repos = list(hub.merge.foundations.get_repos(source))
	repo_futures = []
	with ThreadPoolExecutor(max_workers=8) as executor:
		for repo_dict in repos:
			fut = executor.submit(initialize_repo, hub, repo_dict)
			repo_futures.append(fut)
	for repo_fut in as_completed(repo_futures):
		continue
	hub.CURRENT_SOURCE_DEF = source
