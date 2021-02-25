import glob
import os
import re
import subprocess


async def get_gosum_artifacts(gosum_path):
	"""
	This method will extract package data from ``go.sum`` and generate Artifacts for all packages it finds.
	"""
	with open(gosum_path, "r") as f:
		gosum_lines = f.readlines()
	gosum = ""
	gosum_artifacts = []
	for line in gosum_lines:
		module = line.split()
		if not len(module):
			continue
		gosum = gosum + '\t"' + module[0] + " " + module[1] + '"\n'
		module_path = re.sub("([A-Z]{1})", r"!\1", module[0]).lower()
		module_ver = module[1].split("/")
		module_ext = "zip"
		if "go.mod" in module[1]:
			module_ext = "mod"
		module_uri = module_path + "/@v/" + module_ver[0] + "." + module_ext
		module_file = re.sub("/", "%2F", module_uri)
		gosum_artifacts.append(
			hub.pkgtools.ebuild.Artifact(url="https://proxy.golang.org/" + module_uri, final_name=module_file)
		)
	return dict(gosum=gosum, gosum_artifacts=gosum_artifacts)


async def generate_gosum_from_artifact(src_artifact, src_dir_glob="*"):
	"""
	This method, when passed an Artifact, will fetch the artifact, extract it, look in the directory
	``src_dir_glob`` (a glob specifying the name of the source directory within the extracted files
	which contains ``go.sum`` -- you can also specify sub-directories as part of this glob), and
	will then parse ``go.sum`` for package names, and then generate a list of artifacts for each
	module discovered. This list of new artifacts will be returned as a list. In the case there is no
	``go.sum`` present in the artifact, ``go mod download`` will be run to generate one.
	"""
	await src_artifact.fetch()
	src_artifact.extract()
	src_dir = glob.glob(os.path.join(src_artifact.extract_path, src_dir_glob))[0]
	gosum_path = os.path.join(src_dir, "go.sum")
	if not os.path.exists(gosum_path):
		subprocess.Popen(["go", "mod", "download"], cwd=src_dir).wait()
	artifacts = await get_gosum_artifacts(gosum_path)
	src_artifact.cleanup()
	return artifacts
