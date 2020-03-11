#!/usr/bin/env python3

import asyncio
from concurrent.futures.thread import ThreadPoolExecutor
from multiprocessing import cpu_count

def __init__(hub):
	hub.LOOP = asyncio.get_event_loop()
	hub.CPU_BOUND_EXECUTOR = ThreadPoolExecutor(max_workers=cpu_count())

def get_threadpool(hub):
	return ThreadPoolExecutor(max_workers=cpu_count())

def run_async_adapter(corofn, *args):
	"""
	Use this method to run an asynchronous worker within a ThreadPoolExecutor.
	Without this special wrapper, this normally doesn't work, and the
	ThreadPoolExecutor will not allow async calls.  But with this wrapper, our
	worker and its subsequent calls can be async.

	Use as follows::

		futures =[
			hub.LOOP.run_in_executor(hub.CPU_BOUND_EXECUTOR, run_async_adapter, self.worker_async, worker_async_arg1, ...)
			for meta_pkg_ebuild_path in all_meta_pkg_ebuilds
		]
		for future in asyncio.as_completed(futures):
			...

	"""
	loop = asyncio.new_event_loop()
	try:
		future = corofn(*args)
		asyncio.set_event_loop(loop)
		return loop.run_until_complete(future)
	finally:
		loop.close()

def run_async_tasks(hub, tasks_with_args, threadpool=None):

	"""
	This method will take a list, with each item in the list being in the following format::
	  [ async_task, arg1, arg2, arg3, arg4 ]
	
	For all the elements in the list, the following will be run (based on the above example element)::

	  async_task(arg1, arg2, arg3, arg4)
	
	As you can see, the extra elements in the list are passed as non-keyword arguments to the
	async_task. These tasks will be executed in a CPU-bound ThreadPoolExecutor, using a number of
	threads equal to the number of cores on the system.

	A list of futures will be returned which can be awaited upon to retrieve results.
	"""
	if threadpool is None:
		threadpool = hub.CPU_BOUND_EXECUTOR

	futures = []
	for ta in tasks_with_args:
		async_task = ta[0]
		task_args = ta[1:]
		future = hub.LOOP.run_in_executor(threadpool, run_async_adapter, async_task, *task_args)
		futures.append(future)
	return futures

# vim: ts=4 sw=4 noet
