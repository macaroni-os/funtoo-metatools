#!/usr/bin/env python3

import os
import logging
import dyne.org.funtoo.metatools.pkgtools as pkgtools


class Tree:
	def __init__(self, root=None, start=None, name=None):
		self.root = root
		self.name = name
		self.start = start


def repository_of(start_path, name=None):
	root_path = start_path
	while (
		root_path != "/"
		and not os.path.exists(os.path.join(root_path, "profiles/repo_name"))
		and not os.path.exists(os.path.join(root_path, "metadata/layout.conf"))
	):
		root_path = os.path.dirname(root_path)
	if root_path == "/":
		return None

	repo_name = None
	repo_name_path = os.path.join(root_path, "profiles/repo_name")
	if os.path.exists(repo_name_path):
		with open(repo_name_path, "r") as repof:
			repo_name = repof.read().strip()

	if repo_name is None:
		logging.warning("Unable to find %s." % repo_name_path)

	return Tree(root=root_path, start=start_path, name=repo_name if name is None else name)


def set_context(start_path=None, out_path=None, name=None):
	hub.CONTEXT = repository_of(start_path, name=name)
	if out_path is None or start_path == out_path:
		hub.OUTPUT_CONTEXT = hub.CONTEXT
	else:
		hub.OUTPUT_CONTEXT = repository_of(out_path, name=name)
	if hub.CONTEXT is None:
		raise pkgtools.ebuild.BreezyError(
			"Could not determine repo context: %s -- please create a profiles/repo_name file in your repository." % start_path
		)
	elif hub.OUTPUT_CONTEXT is None:
		raise pkgtools.ebuild.BreezyError(
			"Could not determine output repo context: %s -- please create a profiles/repo_name file in your repository."
			% out_path
		)
	logging.debug("Set source context to %s." % hub.CONTEXT.root)
	logging.debug("Set output context to %s." % hub.OUTPUT_CONTEXT.root)
