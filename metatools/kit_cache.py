# The kit cache has been broken out into its own class so it is not so tightly integrated into merge-kits. This
# allows utilities to be written that can easily access kit-cache data that do not depend on the entire merge-kits
# workflow, such as a tool to scan a kit and see what distfiles are missing from the BLOS, for example.

import os
import json

from metatools.model import get_model

CACHE_DATA_VERSION = "1.0.6"

model = get_model("metatools")


class KitCache:

	json_data = None

	def __init__(self, name, branch):
		self.name = name
		self.branch = branch
		self.writes = set()
		self.misses = set()
		self.retrieved_atoms = set()
		self.metadata_errors = {}
		self.processing_warnings = []

	def load(self):
		if os.path.exists(self.path):
			self.json_data = self.load_json()

	def load_json(self, validate=True):
		"""
		This is a stand-alone function for loading kit cache JSON data, in case someone like me wants to manually load
		it and look at it. It will check to make sure the CACHE_DATA_VERSION matches what this code is designed to
		inspect, by default.
		"""
		with open(self.path, "r") as f:
			try:
				kit_cache_data = json.loads(f.read())
			except json.decoder.JSONDecodeError as jde:
				model.log.error(f"Unable to parse JSON in {self.path}: {jde}")
				raise jde
			if validate:
				if "cache_data_version" not in kit_cache_data:
					model.log.error("JSON invalid or missing cache_data_version.")
					return None
				elif kit_cache_data["cache_data_version"] != CACHE_DATA_VERSION:
					model.log.error(f"Cache data version is {kit_cache_data['cache_data_version']} but needing {CACHE_DATA_VERSION}")
					return None
			return kit_cache_data

	@property
	def path(self):
		return os.path.join(model.temp_path, "kit_cache", f"{self.name}-{self.branch}")

	@property
	def __setattr__(self, atom, value):
		self.json_dict["atoms"][atom] = value
		self.writes.add(atom)

	@property
	def __getattr__(self, item):
		return self.json_dict["atoms"][item]

	def keys(self):
		return self.json_dict["atoms"].keys()

	def save(self, prune=True):
		remove_keys = set()
		if prune:
			all_keys = set(self.keys())
			remove_keys = all_keys - (self.retrieved_atoms | self.writes)
			extra_atoms = self.retrieved_atoms - all_keys
			for key in remove_keys:
				del self.kit_cache[key]
			if len(extra_atoms):
				model.log.error("THERE ARE EXTRA ATOMS THAT WERE RETRIEVED BUT NOT IN CACHE!")
				model.log.error(f"{extra_atoms}")
		outdata = {
			"cache_data_version": CACHE_DATA_VERSION,
			"atoms": self.kit_cache,
			"metadata_errors": self.metadata_errors,
		}
		model.log.warning(
			f"Flushed {self.kit.name}. {len(self.kit_cache)} atoms. Removed {len(remove_keys)} keys. {len(self.metadata_errors)} errors.")
		with open(self.path, "w") as f:
			f.write(json.dumps(outdata))
		error_outpath = os.path.join(
			model.temp_path, f"metadata-errors-{self.out_tree.name}-{self.out_tree.branch}.log"
		)
		if len(self.metadata_errors):
			model.metadata_error_stats.append(
				{"name": self.out_tree.name, "branch": self.out_tree.branch, "count": len(self.metadata_errors)}
			)
			with open(error_outpath, "w") as f:
				f.write(json.dumps(self.metadata_errors))
		else:
			if os.path.exists(error_outpath):
				os.unlink(error_outpath)

		error_outpath = os.path.join(model.temp_path, f"warnings-{self.out_tree.name}-{self.out_tree.branch}.log")
		if len(self.processing_warnings):
			model.processing_warning_stats.append(
				{"name": self.name, "branch": self.branch, "count": len(self.processing_warnings)}
			)
			with open(error_outpath, "w") as f:
				f.write(json.dumps(self.processing_warnings))
		else:
			if os.path.exists(error_outpath):
				os.unlink(error_outpath)
