import hashlib

def calc_hashes(fn, hashes: set):
	hashes = hashes - {"size"}
	hash_objs = {}
	for h in hashes:
		hash_objs[h] = getattr(hashlib, h)()
	filesize = 0
	with open(fn, "rb") as myf:
		while True:
			data = myf.read(1280000)
			if not data:
				break
			for h in hash_objs:
				hash_objs[h].update(data)
			filesize += len(data)
	final_data = {}
	for h in hashes:
		final_data[h] = hash_objs[h].hexdigest()
	final_data['size'] = filesize
	return final_data

