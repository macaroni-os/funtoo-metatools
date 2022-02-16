import hashlib
import os
from collections import OrderedDict
from enum import Enum
from typing import Mapping

import pymongo
from bson import UuidRepresentation
from bson.codec_options import TypeRegistry
from bson.json_util import dumps, JSONOptions, loads
from pymongo import MongoClient

from metatools.config.base import MinimalConfig


class NotFoundError(Exception):
	pass


class KeyKind(Enum):
	DICT = "dict"
	HASH = "hash"


class Key:
	kind: KeyKind = None
	value = None

	def __init__(self, kind, value):
		self.kind = kind
		self.value = value


class StorageBackend:
	store = None

	def __init__(self, model: MinimalConfig, collection, prefix=None):
		self.model = model
		self.collection = collection
		self.prefix = prefix

	def create(self, store):
		self.store = store

	def write(self, metadata):
		pass

	def update(self, metadata):
		pass

	def read(self, metadata):
		pass

	def delete(self, metadata):
		pass


class FileStorageBackend(StorageBackend):
	root = None
	# This is equivalent to CANONICAL_JSON_OPTIONS, but we use OrderedDicts for representing objects (good for loading)
	json_options = JSONOptions(strict_number_long=True, datetime_representation=1, strict_uuid=True, json_mode=2,
	                           document_class=OrderedDict, tz_aware=False, uuid_representation=UuidRepresentation.UNSPECIFIED,
	                           unicode_decode_error_handler='strict', tzinfo=None,
	                           type_registry=TypeRegistry(type_codecs=[], fallback_encoder=None))

	def create(self, store):
		self.store = store
		self.root = os.path.join(self.model.work_path, self.store.collection, self.store.prefix)
		os.makedirs(self.root, exist_ok=True)

	def create_disk_index(self, key: Key):
		"""
		This method takes a key and turns it into an index we will use on disk.
		"""
		if key.kind == KeyKind.HASH:
			return str
		else:
			# KeyKind.DICT:
			return hashlib.sha512(dumps(key, json_options=self.json_options)).hexdigest()

	def create_metadata(self, metadata):
		return dumps(metadata, json_options=self.json_options, sort_keys=True).encode('utf-8')

	def read_metadata(self, path):
		with open(path, "rb") as f:
			in_string = f.read().decode("utf-8")
			return loads(in_string, json_options=self.json_options)

	def write(self, metadata):
		key = self.store.extract_key_from_metadata(metadata)
		sha = self.create_disk_index(key)
		dir_index = f"{sha[0:2]}/{sha[2:4]}/{sha[4:6]}"
		out_path = f"{self.root}/{dir_index}/{sha}"
		with open(out_path, 'wb') as f:
			f.write(self.create_metadata(metadata))

	def update(self, metadata):
		key = self.store.extract_key_from_metadata(metadata)
		sha = self.create_disk_index(key)
		dir_index = f"{sha[0:2]}/{sha[2:4]}/{sha[4:6]}"
		out_path = f"{self.root}/{dir_index}/{sha}"
		if not os.path.exists(out_path):
			raise NotFoundError(f"key {key} not found to update.")
		with open(out_path, 'wb') as f:
			f.write(self.create_metadata(metadata))

	def read(self, metadata):
		key = self.store.extract_key_from_metadata(metadata)
		sha = self.create_disk_index(key)
		dir_index = f"{sha[0:2]}/{sha[2:4]}/{sha[4:6]}"
		in_path = f"{self.root}/{dir_index}/{sha}"
		if not os.path.exists(in_path):
			raise NotFoundError(f"key {key} not found.")
		return self.read_metadata(in_path)

	def delete(self, metadata):
		key = self.store.extract_key_from_metadata(metadata)
		sha = self.create_disk_index(key)
		dir_index = f"{sha[0:2]}/{sha[2:4]}/{sha[4:6]}"
		in_path = f"{self.root}/{dir_index}/{sha}"
		if os.path.exists(in_path):
			os.unlink(in_path)


class MongoStorageBackend(StorageBackend):
	client = None
	db = None
	mongo_collection = None

	def gen_indexes(self):
		ix_spec = []
		for key in self.store.key_fields:
			ix_spec.append((key, pymongo.ASCENDING))
		self.mongo_collection.create_index(ix_spec)

	def create(self, store):
		self.store = store
		self.client = MongoClient()
		self.db = getattr(self.client, self.model.db_name)
		self.mongo_collection = getattr(self.db, self.collection)
		self.gen_indexes()

	def write(self, metadata):
		# We don't use the key -- we just verify we have all required components:
		self.store.extract_key_from_metadata(metadata)
		self.mongo_collection.insert_one(metadata, upsert=True)

	def update(self, metadata):
		# We don't use the key -- we just verify we have all required components:
		self.store.extract_key_from_metadata(metadata)
		self.mongo_collection.update_one(metadata, upsert=True)

	def read(self, metadata):
		key = self.store.extract_key_from_metadata(metadata)
		found = self.mongo_collection.find_one(key)
		if found is None:
			raise NotFoundError(f"key {key} not found.")

	def delete(self, metadata):
		key = self.store.extract_key_from_metadata(metadata)
		self.mongo_collection.delete_one(key)


def get_metadata_index(index_field, metadata):
	"""
	This method accepts a string like "foo.bar", and will traverse dict hierarchy ``metadata`` to retrieve the specified
	element. Each '.' represents a depth in the dictionary hierarchy.
	"""
	index_split = index_field.split(".")
	cur_data = metadata
	for index_part in index_split:
		if index_part not in cur_data:
			raise KeyError(f"Attempting to retrieve field {index_field}, but does not exist ({index_part})")
		elif not isinstance(cur_data, Mapping):
			raise KeyError(f"Attempting to retrieve field {index_field}, but did not find it in supplied metadata.")
		cur_data = cur_data[index_part]
	return cur_data


class Store:
	"""
	This class implements a general-purpose storage API. The class abstracts the storage backend so that we can store
	using files, using MongoDB, etc.
	
	Here are the various terms used in this storage API, and their meanings:
	
	1. ``key`` -- One or more values in the metadata (see below) used as 'atom' to reference the underlying element.
	     In this implementation, we treat indices as unique.
	2. ``collection`` -- This is a logical name for the entire collection of data indexes (and associated metadata)
	     that we are storing.
	3. ``prefix`` -- This is an optional sub-grouping, between ``collection`` and the data. Think of it as a folder name.
	4. ``metadata`` -- This is the full hierarchical data that is associated with the key that is stored. It is BSON.

	Here is an overview of the API:

	1. ``write()`` writes metadata to a key.
	2. ``update()`` updates an existing key and replaces any existing (if any) metadata.
	3. ``read()`` accepts a key, and will return associated metadata.
    4. ``delete()`` as you might guess, this deletes the key and associated metadata from the store.
	"""

	backend: StorageBackend = None
	index = None
	collection = None
	prefix = None
	key_kind = KeyKind.DICT
	key_fields = []

	def __init__(self, backend=None):
		self.backend = backend
		self.backend.create(self)

	def extract_key_from_metadata(self, metadata: dict):
		"""
		Given some metadata, this will extract the index fields and create a key used for retrieving or storing the
		metadata. Two kinds are supported -- KeyKind.DICT (typical use) which means one or more literal data keys can be
		used and will be represented in an OrderedDict which will be used to generate a hash, and KeyKind.HASH, which is
		optimized for when we are indexing on a piece of data that is already an ASCIIfied hash. File-based backends can
		simply use the hash itself as a disk index.
		"""
		key = None
		if self.key_kind == KeyKind.DICT:
			key = OrderedDict()
			for index_name in self.key_fields:
				index_data = get_metadata_index(index_name, metadata)
				key[index_name] = index_data
		elif self.key_kind == KeyKind.HASH:
			# For now, if we want to index by hash, just specify one item in self.key_fields indicating where this hash
			# is in the metadata.
			key = get_metadata_index(self.key_fields[0], metadata)
		return Key(kind=self.key_kind, value=key)

	def write(self, metadata: dict):
		"""
		This method will extract index fields from metadata to use as a key, and then store the metadata.
		"""
		return self.backend.write(metadata)

	def update(self, metadata: dict):
		"""
		This method will update the metadata associated with an entry.
		"""
		return self.backend.update(metadata)

	def read(self, metadata: dict):
		"""
		This method will look for index fields in ``metadata`` and use this as a key to retrieve from the store.
		TODO: provide a way to specify additional criteria.
		"""
		return self.backend.read(metadata)

	def delete(self, metadata: dict):
		"""
		This method will extract an index from metadata to create a key and use this to delete any associated data
		from the store.
		"""
		return self.backend.delete(metadata)
