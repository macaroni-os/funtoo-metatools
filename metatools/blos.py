#!/usr/bin/env python3

from metatools.fastpull.spider import Download
from metatools.hashutils import calc_hashes
from metatools.store import Store, FileStorageBackend, HashKey, DerivedKey


class BaseLayerObjectStore(Store):

	def __init__(self, db_base_path, hashes: set):
		self.collection = "blos"
		self.backend = FileStorageBackend(db_base_path=db_base_path)
		self.key_spec = HashKey("hashes.sha512")
		self.required_spec = DerivedKey(list(map(lambda x: f"hashes.{x}", hashes)))
		self.hashes = hashes
		super().__init__()

	def insert_download(self, download: Download):
		"""
		This is the method used to insert a Download into the BLOS which already has hashes
		we can use.
		"""
		return self.write({"hashes": download.final_data}, blob_path=download.temp_path)

	def insert_blob(self, blob_path):
		"""
		This is the method used by utilities to insert an arbitrary file on disk into the
		BLOS -- we need to calculate hashes in this case.
		"""
		return self.write({"hashes": calc_hashes(self.hashes, blob_path)}, blob_path=blob_path)
