import hashlib

HASHES = ["sha256", "sha512", "blake2b"]


def calc_hashes(fn):
	hashes = {}
	for h in HASHES:
		hashes[h] = getattr(hashlib, h)()
	filesize = 0
	with open(fn, "rb") as myf:
		while True:
			data = myf.read(1280000)
			if not data:
				break
			for h in hashes:
				hashes[h].update(data)
			filesize += len(data)
	final_data = {"size": filesize, "hashes": {}, "path": fn}
	for h in HASHES:
		final_data["hashes"][h] = hashes[h].hexdigest()
	return final_data


async def check_hashes(old_hashes, new_hashes):
	"""
	This method compares two sets of hashes passed to it and throws an exception if they don't match.
	"""
	failures = []
	for h in HASHES:
		old = old_hashes[h]
		new = new_hashes[h]
		if old != new:
			failures.append((h, old, new))
	return failures