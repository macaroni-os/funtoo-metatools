#!/usr/bin/env python3

from metatools.fastpull.spider import Download
from metatools.store import Store, FileStorageBackend, HashKeySpecification, DerivedKeySpecification


class BaseLayerObjectStore(Store):

	def __init__(self, db_base_path, hashes: set):
		self.collection = "blos"
		self.backend = FileStorageBackend(db_base_path=db_base_path)
		self.key_spec = HashKeySpecification("hashes.sha512")
		self.required_spec = DerivedKeySpecification(list(map(lambda x: f"hashes.{x}", hashes)))
		super().__init__()

	def insert_download(self, download: Download):
		return self.write({"hashes": download.final_data}, blob_path=download.temp_path)

