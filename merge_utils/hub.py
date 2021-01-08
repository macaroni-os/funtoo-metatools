#!/usr/bin/env python3

import os
import importlib.util
import types


class PluginDirectory:
	def __init__(self, hub, path):
		self.path = path
		self.hub = hub
		self.loaded = False
		self.plugins = {}

	def load(self):
		for item in os.listdir(self.path):
			if item == "__init__.py":
				continue
			if item.endswith(".py"):
				plugin_name = item[:-3]
				self.plugins[plugin_name] = self.hub.load_plugin(os.path.join(self.path, item), plugin_name)
		self.loaded = True

	def __getattr__(self, item):
		if not self.loaded:
			self.load()
		if item not in self.plugins:
			raise AttributeError(f"{item} not found.")
		return self.plugins[item]


class Hub:
	def __init__(self, lazy=True):
		self.root_dir = os.path.normpath(os.path.join(os.path.realpath(__file__), "../../"))
		self.paths = {}
		self.lazy = lazy

	def add(self, path, name=None):
		if name is None:
			name = os.path.basename(path)
		self.paths[name] = PluginDirectory(self, os.path.join(self.root_dir, path))
		if not self.lazy:
			self.paths[name].load()

	def load_plugin(self, path, name):
		print(f"Loading {path}")
		spec = importlib.util.spec_from_file_location(name, path)
		if spec is None:
			raise FileNotFoundError(f"Could not find plugin: {path}")
		mod = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(mod)
		# inject hub into plugin so it's available:
		mod.hub = self
		init_func = getattr(mod, "__init__", None)
		if init_func is not None and isinstance(init_func, types.FunctionType):
			init_func()
		return mod

	def __getattr__(self, name):
		if name not in self.paths:
			raise AttributeError(f"{name} not found on hub.")
		return self.paths[name]


if __name__ == "__main__":
	hub = Hub()
	hub.add("modules/funtoo/pkgtools", name="pkgtools")
	hb = hub.pkgtools.foobar.HubbaBubba()
