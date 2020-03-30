#!/usr/bin/env python3


def __init__(hub):
    hub.pop.config.load(['pkgtools'], None)
    hub.pop.sub.load_subdirs(hub.pkgtools, recurse=True)

