#!/usr/bin/env python3

def get_metadata(hub, path):
	metadata = {}
	with open(path, 'r') as f:
		lines = f.read().split('\n')
		for line in lines:
			eq_pos = line.find('=')
			if eq_pos == -1:
				continue
			key = line[:eq_pos]
			value = line[eq_pos+1:]
			metadata[key] = value
	return metadata
