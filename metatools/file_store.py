import os

# TODO: it is possible to make FileStore a totally abstract 'storage' class and then have subclasses be MongoDB-enabled.
#       This would allow all parts of the DB storage code (except for metadata storage, potentially) of being retargetable
#       to file storage while using a consistent internal API.


class FileStore:

	prefix = None

	def __init__(self, path):
		self.root = os.path.join(path, self.prefix)
		os.makedirs(self.root, exist_ok=True)

	def write(self, index, metadata: dict, body=None):
		"""
		This method will use "index" as a path to store metadata and an optional "body" binary data.
		"""

	def update(self, index, metadata):
		"""
		This method will update the metadata associated with an entry in the filestore without changing the 'body'.
		"""

	def read(self, index, match: dict):
		"""
		This method will use "index" as a path to read from the filestore. "match" is a dictionary that will be used to
		match against metadata. If any specified keys do not exactly match, the stored value will be treated as it it
		does not exist.
		"""

	def delete(self, index):
		"""
		This method will delete an item from the filestore.
		"""
