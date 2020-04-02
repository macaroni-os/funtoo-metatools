#!/usr/bin/env python3

import os
import sys
import logging

class Tree:
    def __init__(self, root=None, name=None):
       self.root = root
       self.name = name


def repository_of(hub, p, name=None):
    start_path = p
    while start_path != "/" and not os.path.exists(os.path.join(start_path, "profiles/repo_name")) and not os.path.exists(os.path.join(start_path, "metadata/layout.conf")):
        start_path = os.path.dirname(start_path)
    if start_path == "/":
        return None

    repo_name = None
    repo_name_path = os.path.join(start_path, "profiles/repo_name")
    if os.path.exists(repo_name_path):
        with open(repo_name_path, "r") as repof:
            repo_name = repof.read().strip()

    if repo_name is None:
        logging.warning("Unable to find %s." % repo_name_path)

    return Tree(root=start_path, name=repo_name if name is None else name)


def set_context(hub, path, out_path=None, name=None):
    hub.CONTEXT = hub._.repository_of(path, name=name)
    if out_path is None or path == out_path:
        hub.OUTPUT_CONTEXT = hub.CONTEXT
    else:
        hub.OUTPUT_CONTEXT = hub._.repository_of(out_path, name=name)
    if hub.CONTEXT is None:
        raise hub.pkgtools.ebuild.BreezyError("Could not determine repo context: %s -- please create a profiles/repo_name file in your repository." % path)
    elif hub.OUTPUT_CONTEXT is None:
        raise hub.pkgtools.ebuild.BreezyError("Could not determine output repo context: %s -- please create a profiles/repo_name file in your repository." % out_path)
    logging.debug("Set source context to %s." % hub.CONTEXT.root)
    logging.debug("Set output context to %s." % hub.OUTPUT_CONTEXT.root)

