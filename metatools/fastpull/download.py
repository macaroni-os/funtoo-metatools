import asyncio
import hashlib
import logging
import os
import sys
from contextlib import asynccontextmanager
from threading import Lock, Semaphore
from metatools.hashutils import HASHES


class Download:

	def __init__(self, url):
		self.url = url
		self.waiters = []

	async def add_waiter(self):
		fut = asyncio.get_running_loop()
		self.waiters.append(fut)
		return fut

	def notify_waiters(self, result):
		for future in self.waiters:
			future.set_result(result)


class WebSpider:
	"""
	Locking Code
	============

	The locking code below deserves some explanation. DL_ACTIVE tracks all the active downloads for
	*all* threads that are running. DL_ACTIVE_LOCK is a lock we use to access this dictionary, when
	we want to read or modify it.

	DOWNLOAD_SLOT is the mechanism we used to ensure we only have a certain number (specified by the
	value= parameter) of downloads active at once. Each active download will acquire a slot. When all
	slots are exhausted, any pending downloads will wait for an active slot before they can begin.
	"""

	DL_ACTIVE_LOCK = Lock()
	DL_ACTIVE = dict()
	DOWNLOAD_SLOT = Semaphore(value=200)

	def __init__(self, temp_path):
		self.temp_path = temp_path

	def _get_temp_path(self, authoritative_url):
		# TODO: this is not really written
		os.makedirs(os.path.dirname(self.temp_path), exist_ok=True)
		return ""

	async def download(self, url) -> (str, str):
		"""
		This method attempts to start a download. It hooks into ``download_slot`` which is used to limit the number
		of simultaneous downloads.

		TODO: implement exceptions.
		"""

		download_future = self.get_existing_download(url)
		if download_future:
			temp_path, final_data = await download_future
		else:
			download = Download(url)
			async with self.acquire_download_slot(self):
				async with self.start_download(self, download):
					temp_path, final_data = await self._download(url, retry=not throw)
				download.notify_waiters((temp_path, final_data))
		return temp_path, final_data

	async def _download(self, authoritative_url, retry=True):
		# TODO: implement exceptions

		logging.info(f"Fetching {authoritative_url}...")
		temp_path = self._get_temp_path(authoritative_url)

		try:
			fd = open(temp_path, "wb")
			hashes = {}

			for h in HASHES:
				hashes[h] = getattr(hashlib, h)()
			filesize = 0

			def on_chunk(chunk):
				# See https://stackoverflow.com/questions/5218895/python-nested-functions-variable-scoping
				nonlocal filesize
				fd.write(chunk)
				for hash in HASHES:
					hashes[hash].update(chunk)
				filesize += len(chunk)
				sys.stdout.write("")
				sys.stdout.flush()

			# TODO: how to pass extra HTTP headers all the way in to the fetch request. I think we should use an obj instead of a
			#       'url' string.
			await pkgtools.http.http_fetch_stream(authoritative_url, on_chunk, retry=retry, extra_headers=artifact.extra_http_headers)

			sys.stdout.write("x")
			sys.stdout.flush()
			fd.close()

			final_data = {"size": filesize, "hashes": {}}
			for h in HASHES:
				final_data["hashes"][h] = hashes[h].hexdigest()

			return temp_path, final_data

	@asynccontextmanager
	async def acquire_download_slot(self):
		"""
		This code originally tried to do this, but it would deadlock::

		  with DOWNLOAD_SLOT:
			yield

		This code ^^ will deadlock as hit the max semaphore value. The reason? When we hit the max value, it will block
		for a download slot in the current thread will FREEZE our thread's ioloop, which will prevent another asyncio
		task from executing which needs to *release* the download slot -- thus the deadlock.

		So instead of using this approach, we will attempt to acquire a download slot in a non-blocking fashion. If we
		succeed -- great. If not, we will asyncio loop to repeatedly attempt to acquire the slot with a slight delay
		between each attempt. This ensures that the ioloop can continue to function and release any download slots while
		we wait.
		"""
		try:
			while True:
				success = self.DOWNLOAD_SLOT.acquire(blocking=False)
				if not success:
					await asyncio.sleep(0.1)
					continue
				yield
				break
		finally:
				self.DOWNLOAD_SLOT.release()

	@asynccontextmanager
	async def start_download(self, download):
		"""
		Automatically record the download as being active, and remove from our list when complete.

		While waiting for DL_ACTIVE_LOCK will FREEZE the current thread's ioloop, this is OK because we immediately release
		the lock after inspecting/modifying the protected resource (DL_ACTIVE in this case.)
		"""
		try:
			with self.DL_ACTIVE_LOCK:
				self.DL_ACTIVE[download.url] = download
			yield
		finally:
			with self.DL_ACTIVE_LOCK:
				if download.url in self.DL_ACTIVE:
					del self.DL_ACTIVE[download.url]

	def get_existing_download(self, url):
		"""
		Get a download object for the file we're interested in if one is already being downloaded.
		"""
		with self.DL_ACTIVE_LOCK:
			if url in self.DL_ACTIVE:
				return self.DL_ACTIVE[url]
			else:
				return None
