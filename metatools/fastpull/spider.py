import asyncio
import hashlib
import logging
import os
import sys
import socket
import threading
from collections import defaultdict
from contextlib import asynccontextmanager

from asyncio import Semaphore
from urllib.parse import urlparse

import aiohttp

class FetchRequest:

	def __init__(self, url, retry=True, extra_headers=None, mirror_urls=None, username=None, password=None, expected_hashes=None):
		self.url = url
		self.retry = retry
		self.extra_headers = extra_headers if extra_headers else {}
		self.mirror_urls = mirror_urls if mirror_urls else []
		# for basic auth
		self.username = username
		self.password = password
		# TODO: this was a last-minute add to FetchRequest and we could possibly leverage this in the BLOS.
		self.expected_hashes = expected_hashes if expected_hashes is not None else {}

	@property
	def hostname(self):
		parsed_url = urlparse(self.url)
		return parsed_url.hostname

	def set_auth(self, username=None, password=None):
		self.username = username
		self.password = password


class FetchResponse:

	temp_path = None
	final_data = None

	def __init__(self, request: FetchRequest, success=True, failure_reason=None):
		self.request = request
		self.success = success
		self.failure_reason = failure_reason


class Download:
	
	"""
	``Download`` represents an in-progress download, and has a mechanism for recording and notifying those waiting
	for this particular download to complete.
	"""

	def __init__(self, request: FetchRequest):
		self.request = request
		self.waiters = []

	async def add_waiter(self):
		fut = asyncio.get_running_loop()
		self.waiters.append(fut)
		return fut

	def notify_waiters(self, result):
		for future in self.waiters:
			future.set_result(result)


class FetchError(Exception):

	"""
	When this exception is raised, we can set retry to True if the failure is something that could conceivably be
	retried, such as a network failure. However, if we are reading from a cache, then it's just going to fail again,
	and thus retry should have the default value of False.
	"""

	def __init__(self, request: FetchRequest, msg, retry=False):
		self.request = request
		self.msg = msg
		self.retry = retry

	def __repr__(self):
		return f"{self.request.url}: {self.msg}"


class WebSpider:

	"""
	This class implements a Web Spider, which is used to quickly download a lot of things. This spider takes care
	of downloading the files, and will also calculate cryptographic hashes for what it downloads. This is because
	it's more efficient to calculate hashes while the download is being streamed rather than doing it after the
	file has been completely downloaded.

	Locking Code
	============

	The locking code below deserves some explanation. DL_ACTIVE tracks all the active downloads for
	*all* threads that are running. DL_ACTIVE_LOCK is a lock we use to access this dictionary, when
	we want to read or modify it.

	DOWNLOAD_SLOT is the mechanism we used to ensure we only have a certain number (specified by the
	value= parameter) of downloads active at once. Each active download will acquire a slot. When all
	slots are exhausted, any pending downloads will wait for an active slot before they can begin.
	"""

	DL_ACTIVE_LOCK = threading.Lock()
	DL_ACTIVE = dict()
	DOWNLOAD_SLOT = threading.Semaphore(value=200)
	http_timeout = aiohttp.ClientTimeout(connect=10.0, sock_connect=12.0, total=None, sock_read=8.0)
	thread_ctx = threading.local()
	fetch_headers = {"User-Agent": "funtoo-metatools (support@funtoo.org)"}

	def __init__(self, temp_path, hashes):
		self.temp_path = temp_path
		self.hashes = hashes - {'size'}

	def _get_temp_path(self, request: FetchRequest):
		# Use MD5 to create the path for the temporary file to avoid collisions.
		temp_name = hashlib.md5(request.url.encode('utf-8')).hexdigest()
		temp_path = os.path.join(self.temp_path, temp_name)
		os.makedirs(os.path.dirname(temp_path), exist_ok=True)
		return temp_path

	def cleanup(self, response: FetchResponse):
		"""
		This is a utility function to clean up a temporary file provided by the spider, once the caller is done
		with it.
		"""

		if os.path.exists(response.temp_path):
			try:
				os.unlink(response.temp_path)
			except FileNotFoundError:
				# FL-8301: address possible race condition
				pass

	async def download(self, request: FetchRequest) -> FetchResponse:
		"""
		This method attempts to start a download. It is what users of the spider should call, and will take into
		account any in-flight downloads for the same resource, which is most efficient and safe and will prevent
		multiple requests for the same file.

		A FetchResponse will be returned containing information about the downloaded file or error information if
		the fetch failed.
		"""

		download_future = self.get_existing_download(request)
		if download_future:
			return await download_future
		else:
			download = Download(request)
			async with self.acquire_download_slot():
				async with self.start_download(download):
					response = await self._download(request)
					download.notify_waiters(response)
					return response

	async def _download(self, request) -> FetchResponse:
		"""
		This is the lower-level download method that wraps the http_fetch_stream() call, and ensures hashes are generated.
		It returns a FetchResponse regardless of success or failure, and you can inspect the FetchResponse.success boolean
		to see if it succeeded or not. If success, then FetchResponse.temp_path will contain a path to the file downloaded,
		and FetchResponse.final_data will contain the final_data (hashes and size) of the downloaded file.

		We want this method to never throw an exception and just gracefully handle any underlying errors.
		"""

		logging.info(f"Fetching {request.url}...")
		temp_path = self._get_temp_path(request)

		fd = open(temp_path, "wb")
		hashes = {}

		for h in self.hashes:
			hashes[h] = getattr(hashlib, h)()
		filesize = 0

		def on_chunk(chunk):
			# See https://stackoverflow.com/questions/5218895/python-nested-functions-variable-scoping
			nonlocal filesize
			fd.write(chunk)
			for hash in self.hashes:
				hashes[hash].update(chunk)
			filesize += len(chunk)
			sys.stdout.write("")
			sys.stdout.flush()
		response = await self.http_fetch_stream(request, on_chunk)
		if not response.success:
			sys.stdout.write(":-(")
			sys.stdout.flush()
			fd.close()
			return response

		sys.stdout.write("x")
		sys.stdout.flush()
		fd.close()

		final_data = {}
		for h in self.hashes:
			final_data[h] = hashes[h].hexdigest()
		final_data['size'] = filesize
		response.temp_path = temp_path
		response.final_data = final_data
		return response

	async def acquire_host_semaphore(self, hostname):
		semaphores = getattr(self.thread_ctx, "http_semaphores", None)
		if semaphores is None:
			semaphores = self.thread_ctx.http_semaphores = defaultdict(lambda: Semaphore(value=8))
		return semaphores[hostname]

	async def get_resolver(self):
		"""
		This returns a DNS resolver local to the ioloop of the caller.
		"""
		resolver = getattr(self.thread_ctx, "http_resolver", None)
		if resolver is None:
			resolver = self.thread_ctx.http_resolver = aiohttp.AsyncResolver(
				nameservers=["1.1.1.1", "1.0.0.1"], timeout=3, tries=2
			)
		return resolver

	def get_headers_and_auth(self, request):
		headers = self.fetch_headers.copy()
		if request.extra_headers:
			headers.update(request.extra_headers)
		else:
			headers = self.fetch_headers
		if request.username and request.password:
			auth = aiohttp.BasicAuth(request.username, request.password)
		else:
			auth = None
		return headers, auth

	async def http_fetch(self, request: FetchRequest, encoding=None) -> str:
		"""
		This is a non-streaming HTTP fetcher that will properly convert the request to a Python string and return the entire
		content as a string.

		Use ``encoding`` if the HTTP resource does not have proper encoding and you have to set a specific encoding for string
		conversion. Normally, the encoding will be auto-detected and decoded for you.

		This method *will* return a FetchError if there was some kind of fetch failure, and this is used by the 'fetch cache'
		so this is important.
		"""
		semi = await self.acquire_host_semaphore(request.hostname)

		try:
			async with semi:
				sys.stdout.write('-')
				sys.stdout.flush()
				connector = aiohttp.TCPConnector(family=socket.AF_INET, resolver=await self.get_resolver(), ttl_dns_cache=300)
				http_session = aiohttp.ClientSession(connector=connector, timeout=self.http_timeout)
				try:
					# This mess below is me being paranoid about acquiring the session possibly timing out. This could potentially
					# happen due to low-level SSL problems. But you would typically just use an:
					#
					#   async with aiohttp.ClientSession(...) as http_session:
					#
					# Instead I, in a paranoid fashion, get the session with a timeout of 3 seconds. This may be extreme paranoia
					# but I *think* it was locking up here when GitHub had some HTTP issues so I want to keep it looking this nasty.
					sess_fut = http_session.__aenter__()
					await asyncio.wait_for(sess_fut, timeout=3.0)
					sys.stdout.write(f'={request.url}\n')
					headers, auth = self.get_headers_and_auth(request)
					async with http_session.get(request.url, headers=headers, auth=auth) as response:
						if response.status != 200:
							reason = (await response.text()).strip()
							if response.status in [400, 404, 410]:
								# No need to retry as the server has just told us that the resource does not exist.
								retry = False
							else:
								retry = True
							sys.stdout.write(f"!!!{request.url} {response.status} {reason[:40]}")
							raise FetchError(request, f"HTTP fetch Error: {request.url}: {response.status}: {reason[:40]}", retry=retry)
						result = await response.text(encoding=encoding)
						sys.stdout.write(f'>{request.url} {len(result)} bytes\n')
						return result
				except asyncio.TimeoutError:
					raise FetchError(request, f"aiohttp clientsession timeout: {request.url}")
				finally:
					await http_session.__aexit__(None, None, None)
		except aiohttp.ClientConnectorError as ce:
			raise FetchError(request, f"Could not connect to {request.url}: {repr(ce)}", retry=False)

	async def http_fetch_stream(self, request: FetchRequest, on_chunk, chunk_size=262144) -> FetchResponse:
		"""
		This is a low-level streaming HTTP fetcher that will call on_chunk(bytes) for each chunk. On_chunk is called with literal bytes from the response
		body so no decoding is performed. Inspect the FetchResponse.success boolean to determine success or failure. Note that if successful,
		the temp_path and final_data fields in the FetchResponse still need to be filled out (this is done by self._download(), which calls this.)

		While FetchErrors are used internally, we want this method to never throw an exception and just gracefully handle any underlying errors.
		"""
		hostname = request.hostname
		semi = await self.acquire_host_semaphore(hostname)
		prev_rec_bytes = 0
		rec_bytes = 0
		attempts = 0
		if request.retry:
			max_attempts = 3
		else:
			max_attempts = 1
		completed = False
		try:

			async with semi:
				while not completed and attempts < max_attempts:
					connector = aiohttp.TCPConnector(family=socket.AF_INET, resolver=await self.get_resolver(), ttl_dns_cache=300)
					try:
						async with aiohttp.ClientSession(connector=connector, timeout=self.http_timeout) as http_session:
							headers, auth = self.get_headers_and_auth(request)
							if rec_bytes:
								headers["Range"] = f"bytes={rec_bytes}-"
								logging.warning(f"Resuming at {rec_bytes}")
							async with http_session.get(request.url, headers=headers, auth=auth) as response:
								if response.status not in [200, 206]:
									reason = (await response.text()).strip()
									if response.status in [400, 404, 410]:
										# These are legitimate responses that indicate that the file does not exist. Therefore, we
										# should not retry, as we should expect to get the same result.
										retry = False
									else:
										retry = True
									raise FetchError(request, f"HTTP fetch_stream Error {response.status}: {reason[:40]}", retry=retry)
								while not completed:
									chunk = await response.content.read(chunk_size)
									rec_bytes += len(chunk)
									if not chunk:
										completed = True
										break
									else:
										on_chunk(chunk)
					except Exception as e:
						# If we are "making progress on the download", then continue indefinitely --
						if prev_rec_bytes < rec_bytes:
							prev_rec_bytes = rec_bytes
							print("Attempting to resume download...")
							continue

						if isinstance(e, FetchError):
							if e.retry is False:
								raise e

						if attempts + 1 < max_attempts:
							attempts += 1
							print(f"Retrying after download failure... {e}")
							continue
						else:
							raise FetchError(request, f"{e.__class__.__name__}: {str(e)}")
				# Note: This FetchResponse still needs to be augmented by the caller, to add: temp_path and final_data.
				return FetchResponse(request, success=True)
		except FetchError as fe:
			return FetchResponse(request, success=False, failure_reason=fe.msg)

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
				self.DL_ACTIVE[download.request.url] = download
			yield
		finally:
			with self.DL_ACTIVE_LOCK:
				if download.request.url in self.DL_ACTIVE:
					del self.DL_ACTIVE[download.request.url]

	def get_existing_download(self, request: FetchRequest):
		"""
		Get a download object for the file we're interested in if one is already being downloaded.
		"""
		with self.DL_ACTIVE_LOCK:
			if request.url in self.DL_ACTIVE:
				return self.DL_ACTIVE[request.url]
			
			# One man's authoritative URL is another man's mirror URL, so also see if a mirror URL is in progress...
			
			if request.mirror_urls:
				for mirror_url in request.mirror_urls:
					if mirror_url in self.DL_ACTIVE:
						return self.DL_ACTIVE[mirror_url]
			else:
				return None
