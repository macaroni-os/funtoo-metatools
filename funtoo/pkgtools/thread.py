#!/usr/bin/env python3

import asyncio
from concurrent.futures.thread import ThreadPoolExecutor
from multiprocessing import cpu_count


def __init__(hub):
	hub.LOOP = asyncio.get_event_loop()
	hub.CPU_BOUND_EXECUTOR = ThreadPoolExecutor(max_workers=cpu_count())


def get_threadpool(hub):
	return ThreadPoolExecutor(max_workers=cpu_count())


def run_async_adapter(corofn, *args, **kwargs):
	"""
	Use this method to run an asynchronous worker within a ThreadPoolExecutor.
	Without this special wrapper, this normally doesn't work, and the
	ThreadPoolExecutor will not allow async calls.  But with this wrapper, our
	worker and its subsequent calls can be async.

	"""
	loop = asyncio.new_event_loop()
	try:
		future = corofn(*args, **kwargs)
		asyncio.set_event_loop(loop)
		return loop.run_until_complete(future)
	finally:
		loop.close()


# vim: ts=4 sw=4 noet
