#!/usr/bin/env python3

import logging
import sys
from enum import Enum


def __init__(hub):
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


async def fetch_harness(hub, fetch_method, fetchable, max_age=None, refresh_interval=None):

	"""
	This method is used to execute any fetch-related method, and will handle all the logic of reading from and
	writing to the fetch cache, as needed, based on the current fetch policy. Arguments include ``fetch_method``
	which is the actual method used to fetch -- the function itself -- which should be a function or method that
	accepts a single non-keyword argument of the URL to fetch, and it should return the result of the fetch
	if successful, or raise FetchError on failure.

	The parameter ``url`` is of course the URL to fetch, and ``max_age`` is a timedelta which is passed to the
	``cache_read()`` method to specify a maximum age of the cached resource, used when using a CACHE_ONLY or
	LAZY fetch policy. ``refresh_interval`` is a timedelta which specifies the minimum interval before updating
	the cached resource and is only active if using BEST_EFFORT. This is useful for packages (like the infamous vim)
	that may get updated too frequently otherwise. Pass ``refresh_interval=timedelta(days=7)`` to only allow for
	updates to the cached metadata every 7 days. Default is None which means to refresh at will (no restrictions
	to frequency.)

	This function will raise FetchError if the result is unable to be retrieved, either from the cache or from
	the live network call -- except in the case of FetchPolicy.BEST_EFFORT, which will 'fall back' to the cache
	if the live fetch fails (and is thus more resilient).
	"""

	url = fetchable if type(fetchable) == str else fetchable.url
	attempts = 0
	fail_reason = None
	while attempts < hub.FETCH_ATTEMPTS:
		attempts += 1

		try:
			if refresh_interval is not None:
				# Let's see if we should use an 'older' resource that we don't want to refresh as often.

				# This call will return our cached resource if it's available and refresh_interval hasn't yet expired, i.e.
				# it is not yet 'stale'.
				result = await hub.pkgtools.FETCH_CACHE.fetch_cache_read(fetch_method.__name__, fetchable, refresh_interval=refresh_interval)
				if result is not None:
					logging.info(f"Retrieved cached result for {url}")
					return result
			logging.info(f"Fetching {url}, attempt {attempts}...")
			result = await fetch_method(fetchable)
			await hub.pkgtools.FETCH_CACHE.fetch_cache_write(fetch_method.__name__, fetchable, result)
			return result
		except FetchError as e:
			if e.retry:
				fail_reason = e.msg
				logging.error(f"Fetch method {fetch_method.__name__} failed with URL {url}; retrying...")
				continue
			else:
				raise e

	# If we've gotten here, we've performed all of our attempts to do live fetching.

	result = await hub.pkgtools.FETCH_CACHE.fetch_cache_read(fetch_method.__name__, fetchable, max_age=max_age)
	if result is not None:
		return result
	else:
		await hub.pkgtools.FETCH_CACHE.record_fetch_failure(fetch_method.__name__, fetchable, fail_reason=fail_reason)
		raise FetchError(f"Unable to retrieve {url} using method {fetch_method.__name__} either live or from cache as fallback.")


async def get_page(hub, fetchable, max_age=None, refresh_interval=None):
	method = getattr(hub.pkgtools.FETCHER, "get_page", None)
	if method is None:
		raise FetchError("Method get_page not implemented for fetcher.")
	return await fetch_harness(hub, method, fetchable, max_age=max_age, refresh_interval=refresh_interval)


async def get_url_from_redirect(hub, fetchable, max_age=None, refresh_interval=None):
	method = getattr(hub.pkgtools.FETCHER, "get_url_from_redirect", None)
	if method is None:
		raise FetchError("Method get_url_from_redirect not implemented for fetcher.")
	return await fetch_harness(hub, method, fetchable, max_age=max_age, refresh_interval=refresh_interval)


async def exists(hub, artifact):
	return hub.pkgtools.FETCHER.exists(artifact)


async def download(hub, artifact):
	method = getattr(hub.pkgtools.FETCHER, "artifact", None)
	if method is None:
		raise FetchError("Method download not implemented for fetcher.")
	return await fetch_harness(hub, method, artifact)


async def update_digests(hub, artifact, check=True):
	db_result = hub.pkgtools.FETCH_CACHE.fetch_cache_read("artifact", artifact)
	if db_result is None:
		raise FetchError(f"We couldn't find {artifact.url} in the fetch cache when verify digests. This shouldn't happen.")
	# This will attempt to update artifact.hashes to contain the actual digests of the file on disk:
	hub.pkgtools.FETCHER.update_digests(artifact)
	if check:
		# We will now check to see if the digests/size of the file on disk matches those when the file was originally downloaded by us:
		if db_result['metadata']['sha512'] != artifact.hashes['sha512']:
			raise FetchError(f"Digests of {artifact.final_name} do not match digest when it was originally downloaded. Current digest: {artifact.hashes['sha512']} Original digest: {db_result['metadata']['sha512']}")
		if db_result['metadata']['blake2b'] != artifact.hashes['blake2b']:
			raise FetchError(f"Digests of {artifact.final_name} do not match digest when it was originally downloaded. Current digest: {artifact.hashes['blake2b']} Original digest: {db_result['metadata']['blake2b']}")
		if db_result['metadata']['size'] != artifact.hashes['size']:
			raise FetchError(f"Filesize of {artifact.final_name} do not match filesize when it was originally downloaded. Current size: {artifact.hashes['size']} Original size: {db_result['metadata']['size']}")

# vim: ts=4 sw=4 noet
