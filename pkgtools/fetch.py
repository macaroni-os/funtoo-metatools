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
	hub.FETCH_CACHE = None
	hub.FETCH_POLICY = FetchPolicy.BEST_EFFORT

class FetchError(Exception):
	pass

def set_fetcher(hub, fetcher):
	new_fetch = getattr(hub.pkgtools.fetchers, fetcher, None)
	if new_fetch is None:
		logging.error(f"Could not find specified fetcher: {fetcher}")
		sys.exit(1)
	else:
		hub.FETCHER = new_fetch


def set_fetch_policy(hub, policy):
	hub.FETCH_POLICY = policy


def set_cacher(hub, cacher):
	if cacher is None:
		hub.FETCH_CACHE = None
		return
	new_fetch = getattr(hub.pkgtools.cachers, cacher, None)
	if new_fetch is None:
		logging.error(f"Could not find specified cacher: {cacher}")
		sys.exit(1)
	else:
		hub.FETCH_CACHE = new_fetch


async def fetch_harness(hub, fetch_method, url, max_age=None):

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
	if hub.FETCH_POLICY in (FetchPolicy.CACHE_ONLY, FetchPolicy.LAZY):
		try:
			return await hub.FETCH_CACHE.fetch_cache_read(fetch_method.name, url, max_age=max_age)
		except FetchError:
			pass
	if hub.FETCH_POLICY == FetchPolicy.CACHE_ONLY:
		raise FetchError("Requested data not in fetch cache.")

	# At this point, we aren't using a fetch policy of 'cache only.' That's done.

	try:
		result = await fetch_method(url)
		if hub.FETCH_POLICY == FetchPolicy.FETCH_ONLY:
			await hub.FETCH_CACHE.record_fetch_success(fetch_method.name, url)
		else:
			await hub.FETCH_CACHE.fetch_cache_write(fetch_method.name, url, result)
		return result
	except FetchError as e:
		await hub.FETCH_CACHE.record_fetch_failure(fetch_method.name, url)
		if hub.FETCH_POLICY != FetchPolicy.BEST_EFFORT:
			raise FetchError(f"Unable to perform live fetch of {url} using method {fetch_method.name}.")
		else:
			try:
				return await hub.FETCH_CACHE.fetch_cache_read(fetch_method.name, url, max_age=max_age)
			except FetchError:
				raise FetchError(f"Unable to retrieve {url} using method {fetch_method.name} either live or from cache as fallback.")


async def get_page(hub, url, max_age=None):
	method = getattr(hub.FETCHER, "get_page", None)
	if method is None:
		raise FetchError("Method get_page not implemented for fetcher.")
	return await fetch_harness(hub, method, url, max_age=max_age)


async def get_url_from_redirect(hub, url, max_age=None):
	method = getattr(hub.FETCHER, "get_url_from_redirect", None)
	if method is None:
		raise FetchError("Method get_url_from_redirect not implemented for fetcher.")
	return await fetch_harness(hub, method, url, max_age=max_age)

# vim: ts=4 sw=4 noet
