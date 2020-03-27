#!/usr/bin/env python3

import logging
import sys
from enum import Enum


class FetchPolicy(Enum):
	CACHE_ONLY = "cache"		# ONLY attempt to use the fetch cache to retrieve results. Don't do any network.
	FETCH_ONLY = "fetch"		# ONLY do live network requests, and DO NOT use the fetch cache.
	BEST_EFFORT = "best"		# Attempt to update cache with live fetch, fall back to cache on failure.
	LAZY = "lazy"				# Use cached data if available and not stale, and only do live fetch if cached data is not available or stale.

# TODO: in LAZY mode, max_age should cause live refreshing of data if it is stale.
# TODO: in BEST_EFFORT mode, do we want max_age to be respected so we don't keep refetching?


def __init__(hub):
	hub.FETCHER = hub.pkgtools.fetchers.default
	hub.FETCH_CACHE = hub.pkgtools.cachers.noop
	hub.FETCH_POLICY = FetchPolicy.BEST_EFFORT
	hub.FETCH_ATTEMPTS = 3


class FetchError(Exception):
	"""
	When this exception is raised, we can set retry to True if the failure is something that could conceivably be
	retried, such as a network failure. However, if we are reading from a cache, then it's just going to fail again,
	and thus retry should have the default value of False.
	"""

	def __init__(self, msg, retry=False):
		self.msg = msg
		self.retry = retry


def set_fetcher(hub, fetcher):
	new_fetch = getattr(hub.pkgtools.fetchers, fetcher, None)
	if new_fetch is None:
		logging.error(f"Could not find specified fetcher: {fetcher}")
		sys.exit(1)
	else:
		hub.FETCHER = new_fetch


def set_fetch_policy(hub, policy):
	hub.FETCH_POLICY = policy


def set_cacher(hub, cacher, **attrs):
	if cacher is None:
		hub.FETCH_CACHE = None
		return
	new_fetch = getattr(hub.pkgtools.cachers, cacher, None)
	if new_fetch is None:
		logging.error(f"Could not find specified cacher: {cacher}")
		sys.exit(1)
	else:
		hub.FETCH_CACHE = new_fetch


async def fetch_harness(hub, fetch_method, fetchable, max_age=None):

	"""
	This method is used to execute any fetch-related method, and will handle all the logic of reading from and
	writing to the fetch cache, as needed, based on the current fetch policy. Arguments include ``fetch_method``
	which is the actual method used to fetch -- the function itself -- which should be a function or method that
	accepts a single non-keyword argument of the URL to fetch, and it should return the result of the fetch
	if successful, or raise FetchError on failure.

	The parameter ``url`` is of course the URL to fetch, and ``max_age`` is a timedelta which is passed to the
	``cache_read()`` method to specify a maximum age of the cached resource.

	This function will raise FetchError if the result is unable to be retrieved, either from the cache or from
	the live network call -- except in the case of FetchPolicy.BEST_EFFORT, which will 'fall back' to the cache
	if the live fetch fails (and is thus more resilient).
	"""
	url = fetchable if type(fetchable) == str else fetchable.url
	attempts = 0
	while attempts < hub.FETCH_ATTEMPTS:
		attempts += 1
		logging.info(f"Fetching {url}, attempt {attempts}...")
		try:
			if hub.FETCH_POLICY in (FetchPolicy.CACHE_ONLY, FetchPolicy.LAZY):
				try:
					return await hub.FETCH_CACHE.fetch_cache_read(fetch_method.name, fetchable, max_age=max_age)
				except FetchError:
					pass
			if hub.FETCH_POLICY == FetchPolicy.CACHE_ONLY:
				raise FetchError("Requested data not in fetch cache.")

			# At this point, we aren't using a fetch policy of 'cache only.' That's done.
			try:
				result = await fetch_method(fetchable)
				if hub.FETCH_POLICY == FetchPolicy.FETCH_ONLY:
					await hub.FETCH_CACHE.record_fetch_success(fetch_method.name, fetchable)
				else:
					await hub.FETCH_CACHE.fetch_cache_write(fetch_method.name, fetchable, result)
				return result
			except FetchError as e:
				logging.error(f"Fetch failure: {e.msg}")
		except FetchError as e:
			if e.retry:
				logging.error(f"Fetch method {fetch_method.name} failed with URL {url}; retrying...")
				continue
			else:
				raise e

	# If we've gotten here, we've performed all of our attempts to do live fetching.

	if hub.FETCH_POLICY != FetchPolicy.BEST_EFFORT:
		raise FetchError(f"Unable to perform live fetch of {url} using method {fetch_method.name}.")
	else:
		result = await hub.FETCH_CACHE.fetch_cache_read(fetch_method.name, fetchable, max_age=max_age)
		if result is not None:
			return result
		else:
			await hub.FETCH_CACHE.record_fetch_failure(fetch_method.name, fetchable)
			raise FetchError(f"Unable to retrieve {url} using method {fetch_method.name} either live or from cache as fallback.")


async def get_page(hub, fetchable, max_age=None):
	method = getattr(hub.FETCHER, "get_page", None)
	if method is None:
		raise FetchError("Method get_page not implemented for fetcher.")
	return await fetch_harness(hub, method, fetchable, max_age=max_age)


async def get_url_from_redirect(hub, fetchable, max_age=None):
	method = getattr(hub.FETCHER, "get_url_from_redirect", None)
	if method is None:
		raise FetchError("Method get_url_from_redirect not implemented for fetcher.")
	return await fetch_harness(hub, method, fetchable, max_age=max_age)


async def exists(self, artifact):
	return self.FETCHER.exists(artifact)


async def download(hub, artifact):
	method = getattr(hub.FETCHER, "artifact", None)
	if method is None:
		raise FetchError("Method download not implemented for fetcher.")
	return await fetch_harness(hub, method, artifact)


async def update_digests(hub, artifact, check=True):
	db_result = hub.FETCH_CACHE.fetch_cache_read("artifact", artifact)
	if db_result is None:
		raise FetchError(f"We couldn't find {artifact.url} in the fetch cache when verify digests. This shouldn't happen.")
	# This will attempt to update artifact.hashes to contain the actual digests of the file on disk:
	hub.FETCHER.update_digests(artifact)
	if check:
		# We will now check to see if the digests/size of the file on disk matches those when the file was originally downloaded by us:
		if db_result['metadata']['sha512'] != artifact.hashes['sha512']:
			raise FetchError(f"Digests of {artifact.final_name} do not match digest when it was originally downloaded. Current digest: {artifact.hashes['sha512']} Original digest: {db_result['metadata']['sha512']}")
		if db_result['metadata']['blake2b'] != artifact.hashes['blake2b']:
			raise FetchError(f"Digests of {artifact.final_name} do not match digest when it was originally downloaded. Current digest: {artifact.hashes['blake2b']} Original digest: {db_result['metadata']['blake2b']}")
		if db_result['metadata']['size'] != artifact.hashes['size']:
			raise FetchError(f"Filesize of {artifact.final_name} do not match filesize when it was originally downloaded. Current size: {artifact.hashes['size']} Original size: {db_result['metadata']['size']}")

# vim: ts=4 sw=4 noet
