from collections import OrderedDict

from metatools.yaml_util import YAMLReader


"""
class SourceCollection:
	# TODO: complete this and fix constructor
	def __init__(self, source):
		repos = list(merge.model.get_repos(source))
		repo_futures = []
		with ThreadPoolExecutor(max_workers=1) as executor:
			for repo_dict in repos:
				# TODO: this should create a new SourceRepository object:
				fut = executor.submit(initialize_repo, repo_dict)
				repo_futures.append(fut)
			for repo_fut in as_completed(repo_futures):
				# Getting .result() will also cause any exception to be thrown:
				repo_dict = repo_fut.result()
				continue
		merge.model.current_source_def = source
"""


class Kit:
	# TODO: convert source kwarg to a SourceCollection reference.
	def __init__(self, name=None, source=None, stability=None, branch=None, eclasses=None, priority=None, aliases=None, sync_url=None, settings=None):
		self.name = name
		self.source = source
		self.stability = stability
		self.branch = branch
		self.eclasses = eclasses if eclasses is not None else {}
		self.priority = priority
		self.aliases = aliases
		self.sync_url = sync_url.format(kit_name=name)
		self.settings = settings if settings is not None else {}


class SourceRepository:

	def __init__(self, name=None, copyright=None, url=None, eclasses=None, src_sha1=None, notes=None):
		self.name = name
		self.copyright = copyright
		# TODO: handle variable URLs like for kit-fixups.
		self.url = url
		self.eclasses = eclasses
		self.src_sha1 = src_sha1
		self.notes = notes


class SourceCollection:

	def __init__(self, name, repositories=None):
		self.name = name
		self.repositories = repositories if repositories is not None else []

"""
class SourceRepository:

	def __init__(self, name=None, url=None, branch="master", src_sha1=None):
		logging.warning(f"Going to initialize/git fetch for {name}")
		self.name = name
		self.url = url
		self.branch = branch
		self.src_sha1 = src_sha1
		#if repo_key in merge.model.source_repos:
		#	repo_obj = merge.model.source_repos[repo_key]
		#	if repo_sha1:
		#		repo_obj.gitCheckout(sha1=repo_sha1)
		#	elif repo_branch:
		#		repo_obj.gitCheckout(branch=repo_branch)
		#else:

		repo_obj = GitTree(
			name,
			url=url,
			root="%s/%s" % (merge.model.source_trees, name),
			branch=branch,
			commit_sha1=src_sha1,
			origin_check=False,
			reclone=False,
			model=merge.model
		)
		repo_obj.initialize()

"""


class ReleaseYAML(YAMLReader):

	def _repositories(self):
		"""
		This is an internal helper method to return the master list of repositories. It should not be used by other parts
		outside this code because this master list can be tweaked by the data that appears in self.source_collections().
		Thus, self.source_collections() should be used as the authoritative definition of repositories, not this particular
		data.
		"""
		repos = OrderedDict()
		for yaml_dat in self.iter_list("release/repositories"):
			name = list(yaml_dat.keys())[0]
			kwargs = yaml_dat[name]
			repos[name] = kwargs
		return repos

	def source_collections(self):
		"""
		A kit's packages.yaml file can be used to reference catpkgs in external overlays, as well as eclasses,
		that should be copied into the kit when it is generated. This group of source repositories is called a
		'source collection', and is  represented by a SourceCollection object.

		One source collection is mapped to each kit in a release, in the release.yaml file 'source' YAML element.
		A source collection has one or more repositories defined. Each source repository is represented by a
		SourceRepository object.

		This method returns an OrderedDict() of all SourceCollections defined in the YAML, which is indexed by
		the YAML name of the source collection. Each kit defined in the YAML can reference one of these source
		collections by name.

		When kits are parsed by the self.kits() method, the source collection referenced by each kit will be
		passed to the kit's constructor.
		"""
		source_collections = OrderedDict()
		repositories = self._repositories()
		for collection_name, collection_items in self.iter_groups("release/source-collections"):
			collection_objs = []
			for repo_def in collection_items:
				if isinstance(repo_def, str):
					# str -> actual pre-defined repository dict
					repo_name = repo_def
					repo_def = repositories[repo_def]
				elif isinstance(repo_def, dict):
					# use pre-defined repository as base and augment with any local tweaks
					repo_name = list(repo_def.keys())[0]
					repo_dict = repo_def[repo_name]
					repo_def = repositories[repo_name].copy()
					repo_def.update(repo_dict)
				repo_obj = SourceRepository(name=repo_name, **repo_def)
				collection_objs.append(repo_obj)
			source_collections[collection_name] = SourceCollection(name=collection_name, repositories=collection_objs)
		return source_collections

	def kits(self):
		collections = self.source_collections()
		kits = OrderedDict()
		kit_defaults = self.get_elem("release/kit-definitions/defaults")
		if kit_defaults is None:
			kit_defaults = {}
		for kit_el in self.iter_list("release/kit-definitions/kits"):
			kit_insides = kit_defaults.copy()
			if isinstance(kit_el, str):
				kit_name = kit_el
			elif isinstance(kit_el, dict):
				kit_name = list(kit_el.keys())[0]
				kit_insides.update(kit_el[kit_name])
			if 'source' in kit_insides:
				sdef_name = kit_insides['source']
				# convert from string to actual SourceCollection Object
				try:
					kit_insides['source'] = collections[sdef_name]
				except KeyError:
					raise KeyError(f"Source definition '{sdef_name}' not found in source-definitions section of release.yaml.")
			kits[kit_name] = Kit(name=kit_name, **kit_insides)
		return kits


if __name__ == "__main__":
	with open('release.yaml', 'r') as f:
		ryaml = ReleaseYAML(f)
		for kit_name, kit_insides in ryaml.kits().items():
			print(kit_name, kit_insides)
		for overlay in ryaml._repositories():
			print(overlay)
		col = ryaml.source_collections()
		for col_name, collection in col.items():
			print(col_name, collection.repositories)
		print(col)
