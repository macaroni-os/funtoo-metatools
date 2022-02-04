import hashlib
import os
from collections import OrderedDict

from bson import UuidRepresentation
from bson.codec_options import TypeRegistry
from bson.json_util import dumps, JSONOptions, loads
from pymongo import MongoClient

from metatools.config.base import MinimalConfig


class StorageNotFoundError(Exception):
	pass


class StorageBackend:

	store = None

	def __init__(self, model: MinimalConfig, collection, prefix=None):
		self.model = model
		self.collection = collection
		self.prefix = prefix

	def create(self, store):
		self.store = store


class FileStorageBackend(StorageBackend):

	"""
	This is a file storage backend which uses a sha512 digest of the atom to index elements on disk. It
	will also recognize when the atom type is set to 'hash', and understand this to mean that the atom
	is already a stringified cryptographic hash of some kind and will avoid creating a digest of it and
	just use it as-is.
	"""

	root = None
	# This is equivalent to CANONICAL_JSON_OPTIONS, but we use OrderedDicts for representing objects (good for loading)
	json_options = JSONOptions(strict_number_long=True, datetime_representation=1, strict_uuid=True, json_mode=2,
	                           document_class=OrderedDict, tz_aware=False, uuid_representation=UuidRepresentation.UNSPECIFIED,
	                           unicode_decode_error_handler='strict', tzinfo=None, type_registry=TypeRegistry(type_codecs=[], fallback_encoder=None))

	def create(self, store):
		self.store = store
		self.root = os.path.join(self.model.work_path, self.store.collection, self.store.prefix)
		os.makedirs(self.root, exist_ok=True)

	def fixup_atom(self, atom):
		"""
		This method takes an atom and turns it into an index we will use on disk. If we see the special atom
		type of "sha512", this tells us that the atom is already a sha512 string so we can avoid doing a
		sha512 of a sha512. Otherwise, we attempt to create a sha512 of a deterministic representation of
		the underlying atom.

		Returns: two items -- the "representation" of the atom which will be recorded in auxiliary
		data for verification/audit purposes, and the actual sha512 index to use on disk.

		"""
		if self.store.atom_type == "hash":
			return f"hash:{str}", str
		elif self.store.atom_type != str:
			# We need to convert the dict to a string in a deterministic way to avoid randomization of atom, thus sort_keys=True.
			return atom, hashlib.sha512(dumps(atom, json_options=self.json_options, sort_keys=True)).hexdigest()
		else:
			return atom, hashlib.sha512(atom).hexdigest()

	def create_auxdata(self, atom_repr, metadata):
		"""
		This creates the 'auxdata', which is a combination of the "atom representation" and the metadata associated
		with the atom, as UTF-8 encoded data:
		"""
		return dumps({
			"atom": atom_repr,
			"metadata": metadata
		}, json_options=self.json_options, sort_keys=True).encode('utf-8')

	def read_auxdata(self, path):
		with open(path, "rb") as f:
			in_string = f.read().decode("utf-8")
			return loads(in_string, json_options=self.json_options)

	def write(self, atom, metadata: dict = None):
		atom_repr, sha = self.fixup_atom(atom)
		dir_index = f"{sha[0:2]}/{sha[2:4]}/{sha[4:6]}"
		out_path = f"{self.root}/{dir_index}/{sha}"
		with open(out_path, 'wb') as f:
			f.write(self.create_auxdata(atom_repr, metadata))

	def update(self, atom, metadata):
		atom_repr, sha = self.fixup_atom(atom)
		dir_index = f"{sha[0:2]}/{sha[2:4]}/{sha[4:6]}"
		out_path = f"{self.root}/{dir_index}/{sha}"
		if not os.path.exists(out_path):
			raise StorageNotFoundError(f"atom {atom} not found to update.")
		with open(out_path, 'wb') as f:
			f.write(self.create_auxdata(atom_repr, metadata))

	def read(self, atom, match: dict = None):
		atom_repr, sha = self.fixup_atom(atom)
		dir_index = f"{sha[0:2]}/{sha[2:4]}/{sha[4:6]}"
		in_path = f"{self.root}/{dir_index}/{sha}"
		if not os.path.exists(in_path):
			return None
		auxdata = self.read_auxdata(in_path)
		if match is not None:
			for key in match:
				if key not in match['metadata']:
					return None
				elif match[key] != auxdata['metadata'][key]:
					return None
		return auxdata['metadata']


class MongoStorageBackend(StorageBackend):

	client = None
	db = None
	mongo_collection = None

	def create(self, store):
		self.store = store
		self.client = MongoClient()
		self.db = getattr(self.client, self.model.db_name)
		return getattr(self.db, self.collection)


class Store:

	"""
	This class implements a general-purpose storage API, for things that are stored using a unique string-representable atom. The
	class abstracts the storage backend so that we can store using files, using MongoDB, etc.
	
	Here are the various terms used in this storage API, and their meanings:
	
	1. ``atom`` -- This can be any string that uniquely identifies a record that is being stored or retrieved and is used as a key.
	2. ``collection`` -- This is a logical name for the entire collection of atoms that we are storing.
	3. ``prefix`` -- This is an optional sub-grouping, between ``collection`` and ``atom``. Think of it as a folder name.
	4. ``metadata`` -- This is data that is associated with the ``atom`` that is stored.

	Here is an overview of the API:

	1. ``write()`` writes an atom with and associated metadata.
	2. ``update()`` updates an existing atom and replaces any existing (if any) metadata.
	3. ``read()`` accepts an atom, and will return associated metadata. An optional ``match`` dictionary can be specified
	              which will only return a result if items in ``match`` exist and match what is in the atom's ``metadata``.
    4. ``delete()`` as you might guess, this deletes the atom from the store.
	"""

	backend: StorageBackend = None

	def __init__(self, collection, prefix=None, backend=None, atom_type=str):
		self.atom_type = atom_type
		self.collection = collection
		self.prefix = prefix
		self.backend = backend
		self.backend.create(self)

	# TODO: the idea of specifying a separate 'atom' as an index isn't totally compatible with how we use mongo, where the index
	#       can consist of various elements of the record itself. (see fastpull, blos.)
	#       .
	#       It would be better for the Store constructor to accept an index= kwarg, which specifies mongo-style indexes. When using
	#       mongo as a backend, we would actually create these indexes. But we would also use them for file storage backends as well,
	#       as we would 'extract' these specified indexes from the document to determine the disk-index of something we're writing, and
	#       also expect any read/update method to have 'atom' set to a dict that contains these elements in a dict, like so:
	#       .
	#       foo.read({"hashes.sha512" : "blah"})
	#       .
	#       This preserves mongodb-style usage in the code while still allowing our FileStorageBackend to work properly.

	def write(self, atom, metadata: dict = None):
		"""
		This method will use "atom" as a path to store metadata.
		"""

	def update(self, atom, metadata):
		"""
		This method will update the metadata associated with an entry.
		"""

	def read(self, atom, match: dict):
		"""
		This method will use "atom" as a path to read from the store. "match" is a dictionary that will be used to
		match against metadata. If any specified keys do not exactly match, the stored value will be treated as it it
		does not exist.
		"""

	def delete(self, atom):
		"""
		This method will delete an atom and associated metadata from the filestore.
		"""






