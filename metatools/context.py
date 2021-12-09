#!/usr/bin/env python3

from portage import os
from subpop.config import ConfigurationError


class Locator:

	start_path = None
	out_path = None
	context = None
	output_context = None
	kit_spy = None

	"""
	This method will look, from the current directory, and find the 'context' of where
	we are in a kit-fixups repository, so we know where the main kit-fixups repository
	is and what is our current working set for autogeneration.
	"""

	def repository_of(self, start_path):
		"""
		This method starts from ``start_path`` and looks backwards in the path structure until it
		gets to the point where it finds a 'profiles/repo_name' and/or 'metadata/layout.conf' file,
		which indicates that it is at the root of an overlay, and then it returns this value.

		If it gets to / without finding these files, it returns None as a failure indicator that
		it couldn't find the overlay that we are currently inside of via the current working
		directory.
		"""
		root_path = start_path
		while (
				root_path != "/"
				and not os.path.exists(os.path.join(root_path, "profiles/repo_name"))
				and not os.path.exists(os.path.join(root_path, "metadata/layout.conf"))
		):
			root_path = os.path.dirname(root_path)
		if root_path == "/":
			root_path = None
		return root_path

	def set_context(self, start_path, out_path=None):
		"""
		The purpose of this method is to set 'context' and 'output context'.

		'self.context' is, based on current working directory, the overlay we are in.
		'self.output_context' is where we are going to write out autogens and Manifests.

		"""
		self.start_path = start_path
		self.out_path = out_path
		self.context = self.repository_of(start_path)
		if out_path is None or start_path == out_path:
			self.output_context = self.context
		else:
			self.output_context = self.repository_of(out_path)
		if self.context is None:
			raise ConfigurationError(
				f"Could not determine repo context: {start_path} -- please create a profiles/repo_name file in your repository."
			)
		elif self.output_context is None:
			raise ConfigurationError(
				f"Could not determine output repo context: {out_path} -- please create a profiles/repo_name file in your repository."
			)

		#self.kit_spy = "/".join(self.context.root.split("/")[-2:])
		#logging.debug("Set source context to %s." % self.context.root)
		#logging.debug("Set output context to %s." % self.output_context.root)

	def __init__(self, start_path, out_path=None):
		self.set_context(start_path, out_path=out_path)
