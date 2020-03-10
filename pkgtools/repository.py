#!/usr/bin/env python3

import os
import sys
import logging

class Tree:
    def __init__(self, root=None, name=None):
       self.root = root
       self.name = name

def repository_of(hub, p):
    start_path = p
    while start_path != "/" and not os.path.exists(os.path.join(start_path, "profiles/repo_name")):
        start_path = os.path.dirname(start_path)
    if start_path == "/":
        return None

    repo_name_path = os.path.join(start_path, "profiles/repo_name")
    if os.path.exists(repo_name_path):
        with open(repo_name_path, "r") as repof:
            repo_name = repof.read().strip()

    if repo_name is None:
        logging.warning("Unable to find %s." % repo_name_path)
        return None

    return Tree(root=start_path, name=repo_name)

def set_context(hub, path):
    hub.CONTEXT = hub._.repository_of(hub.OPTS['repo'])
    if hub.CONTEXT is None:
        print("Could not determine what repository I'm in. Exiting.")
        sys.exit(1)
