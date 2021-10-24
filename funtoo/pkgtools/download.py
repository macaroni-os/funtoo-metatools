#!/usr/bin/env python3

import asyncio
import logging
from contextlib import asynccontextmanager
from threading import Semaphore, Lock



class Download:

	def __init__(self, artifact):
		self.final_name = artifact.final_name
		self.url = artifact.url
		self.artifacts = [artifact]
		self.final_data = None
		self.futures = []

	def add_artifact(self, artifact):
		self.artifacts.append(artifact)

	def wait_for_completion(self, artifact):
		self.artifacts.append(artifact)
		fut = hub.LOOP.create_future()
		self.futures.append(fut)
		return fut


# vim: ts=4 sw=4 noet tw=120
