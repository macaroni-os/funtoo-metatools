#!/usr/bin/env python3

def __init__(hub):
#    hub.pop.sub.add(pypath='pkgtools.rpc')
#    hub.pop.sub.add(pypath='pkgtools.plugins')
    hub.pop.sub.load_subdirs(hub.pkgtools, recurse=True)
