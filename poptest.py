import pop.hub

hub = pop.hub.Hub()
hub.pop.sub.add('pkgtools')
print("Hub.pkgtools is", hub.pkgtools)

# If I manually add subs, they get added directly to the hub:
print(hub.rpc.math.oni)
print(hub.pkgtools.fetch.get_url_from_redirect)
print(hub.plugins)
print(hub.plugins.misc.miscfunc)

# If I call load_subdirs() it seems to do what I expect and create a complex heirarchy for me.
print(hub.pkgtools.rpc.math.oni)
print(hub.pkgtools.fardman.super.zoink)
print(hub.pkgtools.fardman.plugins.zupe.boink)
