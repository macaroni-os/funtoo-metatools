#!/usr/bin/env python3
import asyncio
import json
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

	def __init__(self, fetchable, msg, retry=False):
		self.fetchable = fetchable
		self.msg = msg
		self.retry = retry

	def __repr__(self):
		return f'FetchError for {self.fetchable}: {self.msg}'


class CacheMiss(Exception):
	pass


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
				try:
					result = await hub.cache.fetch.fetch_cache_read(fetch_method.__name__, fetchable, refresh_interval=refresh_interval)
					logging.info(f"Retrieved cached result for {url}")
					return result['body']
				except CacheMiss:
					# We'll continue and attempt a live fetch of the resource...
					pass
			result = await fetch_method(fetchable)
			await hub.cache.fetch.fetch_cache_write(fetch_method.__name__, fetchable, body=result)
			return result
		except FetchError as e:
			if e.retry and attempts + 1 < hub.FETCH_ATTEMPTS:
				fail_reason = e.msg
				logging.error(f"Fetch method {fetch_method.__name__} failed with URL {url}; retrying...")
				continue
			# if we got here, we are on our LAST retry attempt or retry is False:
			logging.warning(f"Unable to retrieve {url}... trying to used cached version instead...")
			try:
				got = await hub.pkgtools.FETCH_CACHE.fetch_cache_read(fetch_method.__name__, fetchable)
				logging.warning(repr(got))
				return got['body']
			except CacheMiss as ce:
				# raise original exception
				raise e
		except asyncio.CancelledError as e:
			raise FetchError(fetchable, f"Fetch of {url} cancelled.")


	# If we've gotten here, we've performed all of our attempts to do live fetching.
	try:
		result = await hub.cache.fetch.fetch_cache_read(fetch_method.__name__, fetchable, max_age=max_age)
		return result['body']
	except CacheMiss:
		await hub.cache.fetch.record_fetch_failure(fetch_method.__name__, fetchable, fail_reason=fail_reason)
		raise FetchError(fetchable, f"Unable to retrieve {url} using method {fetch_method.__name__} either live or from cache as fallback.")


async def get_page(hub, fetchable, max_age=None, refresh_interval=None, is_json=False):
	method = getattr(hub.pkgtools.http, "get_page", None)
	if method is None:
		raise FetchError(fetchable, "Method get_page not implemented for fetcher.")
	result = await fetch_harness(hub, method, fetchable, max_age=max_age, refresh_interval=refresh_interval)
	if not is_json:
		return result
	try:
		json_data = json.loads(result)
		return json_data
	except json.JSONDecodeError as e:
		logging.warning(repr(e))
		logging.warning("JSON appears corrupt -- trying to get cached version of resource...")
		try:
			result = await hub.cache.fetch.fetch_cache_read("get_page", fetchable, max_age=max_age)
			return json.loads(result)
		except CacheMiss:
			# bumm3r.
			raise FetchError(fetchable, "Couldn't find cached version of resource (live version was corrupt JSON.)")
		except json.JSONDecodeError as e:
			raise FetchError(fetchable, f"Tried using cached version of resource but it doesn't appear to be in JSON format: {repr(e)}")

async def get_url_from_redirect(hub, fetchable, max_age=None, refresh_interval=None):
	method = getattr(hub.pkgtools.http, "get_url_from_redirect", None)
	if method is None:
		raise FetchError(fetchable, "Method get_url_from_redirect not implemented for fetcher.")
	return await fetch_harness(hub, method, fetchable, max_age=max_age, refresh_interval=refresh_interval)



# vim: ts=4 sw=4 noet