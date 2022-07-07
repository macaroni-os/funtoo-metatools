import re
import packaging.version

# tag_gen and release_gen are higher-level functions that return a dict of items, suitable for
# augmenting the pkginfo dict, and thus easy to integrate into yaml-based autogens.

from enum import Enum


class SortMethod(Enum):
	DATE = "DATE"
	VERSION = "VERSION"


class Matcher:

	"""
	Big picture: This class abstracts versioning handling, so we can have pluggable version handlers that
	have differing abilities to handle different types of versions.

	Details: This class lets us extract versions from strings, as well as sort them. It can be used to add more
	Functions in this generator accept a matcher= argument which is designed to allow customization of
	version-related functionality by passing a non-default matcher instance to the methods if desired.
	"""

	def match(self, input: str):
		"""
		This method should extract something from the input that resembles a version, and return the
		matching part, or None if no match was found.
		"""
		pass

	def sortable(self, version):
		"""
		This method should return a **sortable** representation of the version grabbed by the match()
		method, above.
		"""
		pass


class RegexMatcher(Matcher):

	"""
	This is the default matcher used by these functions.
	"""

	def __init__(self, regex='([0-9.]+)'):
		self.regex = regex

	def match(self, input: str):
		match = re.search(self.regex, input)
		if match:
			return match.groups()[0]

	def sortable(self, version):
		return packaging.version.parse(version)


def factor_filters(include):
	"""
	By default, the ``release_gen`` method below filters prereleases and drafts. It's now possible
	to disable this by specifying an 'include=' keyword argument to either function, which can be a
	set or a list containing one or more of the following strings:

	* "prerelease"
	* "draft"

	Given this include list/set as an argument, this method will return the set of values that should
	be checked and skipped if found to be True in the JSON (the inverse set, which is easier to use
	in the ``release_gen`` loop when we check.)
	"""

	valid_filters = {"prerelease", "draft"}

	if include is not None:
		for item in include:
			if item not in valid_filters:
				raise ValueError(f"release_gen include= option of '{item}' is not recognized")
		include = set(include)
	else:
		include = set()

	return valid_filters - include


async def release_gen(hub, github_user, github_repo, release_data=None, tarball=None, select=None, filter=None, matcher=None, version=None, include=None, sort: SortMethod = SortMethod.VERSION, **kwargs):
	"""
	This method will query the GitHub API for releases for a specific project, find the most recent
	release, and then return a dictionary containing the keys "version", "artifacts" and "sha", which
	map to the latest non-prerelease version of the release, a list of an artifact associated with
	this release, and the SHA1 for the commit for this tagged release. This info can easily be added
	to the pkginfo dict.

	If 'tarball' (string) is specified, this method will look for a tarball in the release that matches
	the string. A literal '{version}' in the string will be replaced with the version of the release,
	so you will probably want to use that in your tarball string. If no tarball string is specified,
	we grab the source code by looking at the tag associated with the release, and grab a tarball for
	this particular tag.

	``release_data`` may contain the full decoded JSON of a query to the /releases endpoint, as returned
	by ``hub.pkgtools.fetch.get_page(url, is_json=True).`` Otherwise, this information will be queried
	directly from GitHub.

	``select`` may contain a regex string which specifies a pattern that must match the tag_name for
	it to be considered.

	``filter`` can be either a regex string or a list of regex strings. Anything that matches
	this string or strings will be excluded.

	``version`` may contain a version string we are looking for specifically. We currently look in the
	tag_name of the release.

	``include`` may contain a list or set of strings (currently supporting "prerelease" and "draft") which
	if defined will be considered as a match. By default, prereleases and drafts are skipped.
	"""

	skip_filters = factor_filters(include)

	if not release_data:
		release_data = await hub.pkgtools.fetch.get_page(f"https://api.github.com/repos/{github_user}/{github_repo}/releases?per_page=100", is_json=True)

	versions_and_release_elements = []

	if matcher is None:
		matcher = RegexMatcher()

	for release in release_data:
		if any(release[skip] for skip in skip_filters):
			continue
		the_thing = release['tag_name']
		if select and not re.match(select, the_thing):
			continue
		if filter:
			if isinstance(filter, str):
				if re.match(filter, the_thing):
					continue
			elif isinstance(filter, list):
				for each_filter in filter:
					if re.match(each_filter, the_thing):
						continue
		match = matcher.match(the_thing)
		if match:
			if version is not None and match != version:
				continue
			else:
				found_version = match
		else:
			continue
		versions_and_release_elements.append((found_version, release))

	if not len(versions_and_release_elements):
		raise ValueError(f"Could not find a suitable release.")

	# By default, we should sort our releases by version, and start with the most recent version. This is important for some GitHub
	# repos that have multiple 'channels' so the releases may vary and most recent by date may not be what we want.

	if sort == SortMethod.VERSION:
		# Have most recent by version at the beginning:
		versions_and_release_elements = sorted(versions_and_release_elements, key=lambda v: matcher.sortable(v[0]), reverse=True)

	if tarball:
		for version, release in versions_and_release_elements:
			# We are looking for a specific tarball:
			archive_name = tarball.format(version=version)
			for asset in release['assets']:
				if asset['name'] == archive_name:
					return {
						"version": version,
						"artifacts": [hub.pkgtools.ebuild.Artifact(url=asset['browser_download_url'], final_name=archive_name)]
					}
	else:
		version, release = versions_and_release_elements[0]
		# We want to grab the default tarball for the associated tag:
		desired_tag = release['tag_name']
		tag_data = await hub.pkgtools.fetch.get_page(f"https://api.github.com/repos/{github_user}/{github_repo}/tags?per_page=100", is_json=True)
		sha = None
		for tag_ent in tag_data:
			if tag_ent["name"] != desired_tag:
				continue
			else:
				sha = tag_ent['commit']['sha']
		if sha is None:
			raise ValueError(f"Could not retrieve SHA1 for tag {desired_tag}.")

		########################################################################################################
		# GitHub does not list this URL in the release's assets list, but it is always available if there is an
		# associated tag for the release. Rather than use the tag name (which would give us a non-distinct file
		# name), we use the sha1 to grab a specific URL and use a specific final name on disk for the artifact.
		########################################################################################################

		url = f"https://github.com/{github_user}/{github_repo}/tarball/{sha}"
		return {
			"version": version,
			"artifacts": [hub.pkgtools.ebuild.Artifact(url=url, final_name=f'{github_repo}-{version}-{sha[:7]}.tar.gz')],
			"sha": sha
		}


def iter_tag_versions(tags_list, select=None, filter=None, matcher=None, transform=None, version=None):
	"""
	This method iterates over each tag in tags_list, extracts the version information, and
	yields a tuple of that version as well as the entire GitHub tag data for that tag.

	``select`` specifies a regex string that must match for the tag version to be considered.

	``filter`` can be either a regex string or a list of regex strings. Anything that matches
	this string or strings will be excluded.

	``version``, if specified, is a specific version we want. If not specified, all versions
	will be returned.

	``transform`` is a lambda/single-argument function that if specified will be used to
	arbitrarily modify the tag before it is searched for versions, or for the ``select``
	regex.

	``matcher`` is an optional function that accepts a single argument of the tag we are
	processing. By default we will use the ``regex_matcher`` to search for a basic version
	pattern somewhere within the tag.
	"""
	if matcher is None:
		matcher = RegexMatcher()
	for tag_data in tags_list:
		tag = tag_data['name']
		if transform:
			tag = transform(tag)
		if select and not re.match(select, tag):
			continue
		if filter:
			if isinstance(filter, str):
				if re.match(filter, tag):
					continue
			elif isinstance(filter, list):
				for each_filter in filter:
					if re.match(each_filter, tag):
						continue
		match = matcher.match(tag)
		if match:
			if version:
				if match != version:
					continue
			yield match, tag_data


async def latest_tag_version(hub, github_user, github_repo, tag_data=None, transform=None, select=None, filter=None, matcher=None, version=None):
	"""
	This method will look at all the tags in a repository, look for a version string in each tag,
	find the most recent version, and return the version and entire tag data as a tuple.

	``select`` specifies a regex string that must match for the tag version to be considered.

	``version``, if specified, is a version we want. Since we only want this version, we will
	ignore all versions unless we find this specific version.

	If no matching versions, None is returned.
	"""
	if matcher is None:
		matcher = RegexMatcher()
	if tag_data is None:
		tag_data = await hub.pkgtools.fetch.get_page(f"https://api.github.com/repos/{github_user}/{github_repo}/tags?per_page=100", is_json=True)
	versions_and_tag_elements = list(iter_tag_versions(tag_data, select=select, filter=filter, matcher=matcher, transform=transform, version=version))
	if not len(versions_and_tag_elements):
		return
	else:
		return max(versions_and_tag_elements, key=lambda v: matcher.sortable(v[0]))


async def tag_gen(hub, github_user, github_repo, tag_data=None, select=None, filter=None, matcher=None, transform=None, version=None, **kwargs):
	"""
	Similar to ``release_gen``, this will query the GitHub API for the latest tagged version of a project,
	and return a dictionary that can be added to pkginfo containing the version, artifacts and commit sha.

	This method may return None if no suitable tags are found.
	"""
	if matcher is None:
		matcher = RegexMatcher()
	result = await latest_tag_version(hub, github_user, github_repo, tag_data=tag_data, transform=transform, select=select, filter=filter, matcher=matcher, version=version)
	if result is None:
		return None
	version, tag_data = result
	sha = tag_data['commit']['sha']
	url = f"https://github.com/{github_user}/{github_repo}/tarball/{sha}"
	return {
		"version": version,
		"artifacts": [hub.pkgtools.ebuild.Artifact(url=url, final_name=f'{github_repo}-{version}-{sha[:7]}.tar.gz')],
		"sha": sha
	}
