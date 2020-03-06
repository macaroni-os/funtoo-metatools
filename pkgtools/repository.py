#!/usr/bin/env python3

import os

def repository_of(hub, fn):
    start_path = os.path.dirname(os.path.realpath(fn))
    while start_path != "/" and not os.path.exists(os.path.join(start_path, "profiles/repo_name")):
        start_path = os.path.dirname(start_path)
        print(start_path)
    if start_path == "/":
        return None
    else:
        return start_path
