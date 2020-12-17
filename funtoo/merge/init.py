def __init__(hub):
	# Allow explicit setting of mongo, otherwise fallback on auto-detect.
	enable_mongo = getattr(hub, "ENABLE_MONGO", True)
	if isinstance(enable_mongo, bool):
		hub.merge.HAS_MONGO = enable_mongo
	else:
		try:
			import pymongo

			hub.merge.HAS_MONGO = True
		except ImportError:
			hub.merge.HAS_MONGO = False
