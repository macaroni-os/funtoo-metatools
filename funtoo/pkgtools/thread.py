#!/usr/bin/env python3

import asyncio
from concurrent.futures.thread import ThreadPoolExecutor
from multiprocessing import cpu_count

hub = None


def __init__():
	hub.LOOP = asyncio.get_event_loop()
	hub.CPU_BOUND_EXECUTOR = ThreadPoolExecutor(max_workers=cpu_count())


def get_threadpool():
	return ThreadPoolExecutor(max_workers=cpu_count())


def run_async_adapter(corofn, *args, **kwargs):
	"""
	Use this method to run an asynchronous worker within a ThreadPoolExecutor.
	Without this special wrapper, this normally doesn't work, and the
	ThreadPoolExecutor will not allow async calls.  But with this wrapper, our
	worker and its subsequent calls can be async.
	"""
	hub.THREAD_CTX.loop = asyncio.new_event_loop()
	return hub.THREAD_CTX.loop.run_until_complete(corofn(*args, **kwargs))


# vim: ts=4 sw=4 noet
