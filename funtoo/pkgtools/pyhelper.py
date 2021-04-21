#!/usr/bin/env python3
from collections import defaultdict


def sdist_artifact_url(releases, version):
	# Sometimes a version does not have a source tarball. This function lets us know if our version is legit.
	# Returns artifact_url for version, or None if no sdist release was available.
	for artifact in releases[version]:
		if artifact["packagetype"] == "sdist":
			return artifact["url"]
	return None


def pypi_normalize_name(pkginfo):
	if "pypi_name" not in pkginfo:
		pkginfo["pypi_name"] = pkginfo["name"]
	return pkginfo["pypi_name"]


def pypi_normalize_version(pkginfo):
	version_parts = pkginfo["version"].split(".")
	if version_parts[-1].startswith("post"):
		ebuild_version = ".".join(version_parts[:-1]) + "_p" + version_parts[-1][4:]
	else:
		ebuild_version = pkginfo["version"]
	pkginfo["pypi_version"] = pkginfo["version"]
	pkginfo["version"] = ebuild_version


def pypi_get_artifact_url(pkginfo, json_dict, strict=True):
	"""
	A more robust version of ``sdist_artifact_url``.

	Look in JSON data ``json_dict`` retrieved from pypi for the proper sdist artifact for the package specified in
	pkginfo. If ``strict`` is True, will insist on the ``version`` defined in ``pkginfo``, otherwise, will be flexible
	and fall back to most recent sdist.
	"""
	artifact_url = sdist_artifact_url(json_dict["releases"], pkginfo["version"])
	if artifact_url is None:
		if not strict:
			# dang, the latest official release doesn't have a source tarball. Let's scan for the most recent release with a source tarball:
			for version in reversed(json_dict["releases"].keys()):
				artifact_url = sdist_artifact_url(json_dict["releases"], version)
				if artifact_url is not None:
					pkginfo["version"] = version
					break
		else:
			raise AssertionError(f"Could not find a source distribution for {pkginfo['name']} version {pkginfo['version']}")
	else:
		artifact_url = sdist_artifact_url(json_dict["releases"], pkginfo["version"])
	return artifact_url


def pyspec_to_cond_dep_args(pg):
	"""
	This method takes something like "py:all" or "py:2,3_7,3_8" and converts it to a list of arguments that should
	be passed to python_gen_cond_dep (eclass function.) Protect ourselves from the weird syntax in this eclass.

	  py:all -> [] (meaning "no restriction", i.e. apply to all versions)
	  py:2,3.7,3.8 -> [ "-2", "python3_7", "python3_8"]

	"""
	pg = pg.strip()
	if pg == "py:all":
		return []
	if not pg.startswith("py:"):
		raise ValueError(f"Python specifier {pg} does not begin with py:")
	# remove leading "py:"
	pg = pg[3:]
	out = []
	for pg_item in pg.split(","):
		if pg_item in ["2", "3"]:
			out += [f"-{pg_item}"]  # -2, etc.
		elif "." in pg_item:
			# 2.7 -> python2_7, etc.
			out += [f"python{pg_item.replace('.','_')}"]
		else:
			# pass thru pypy, pypy3, etc.
			out.append(pg_item)
	return out


def expand_pydep(pyatom):
	"""
	Takes something from our pydeps YAML that might be "foo", or "sys-apps/foo", or "foo >= 1.2" and convert to
	the proper Gentoo atom format.
	"""
	# TODO: support ranges?
	# TODO: pass a ctx variable here so we can have useful error messages about what pkg is triggering the error.
	psp = pyatom.split()
	if len(psp) == 3 and psp[1] in [">", ">=", "<", "<="]:
		if "/" in psp[0]:
			# already has a category
			return f"{psp[1]}{psp[0]}-{psp[2]}[${{PYTHON_USEDEP}}]"
		else:
			# inject dev-python
			return f"{psp[1]}dev-python/{psp[0]}-{psp[2]}[${{PYTHON_USEDEP}}]"
	elif len(psp) == 1:
		if "/" in pyatom:
			return f"{pyatom}[${{PYTHON_USEDEP}}]"
		else:
			# inject dev-python
			return f"dev-python/{pyatom}[${{PYTHON_USEDEP}}]"
	else:
		raise ValueError(f"What the hell is this: {pyatom}")


def create_ebuild_cond_dep(pyspec_str, atoms):
	"""
	This function takes a specifier like "py:all" and a list of simplified pythony package atoms and creates a
	conditional dependency for inclusion in an ebuild. It returns a list of lines (without newline termination,
	each string in the list implies a separate line.)
	"""
	out_atoms = []
	pyspec = None
	usespec = None
	if pyspec_str.startswith("py:"):
		pyspec = pyspec_to_cond_dep_args(pyspec_str)
	elif pyspec_str.startswith("use:"):
		usespec = pyspec_str[4:]

	for atom in atoms:
		out_atoms.append(expand_pydep(atom))

	if usespec:
		out = [f"{usespec}? ( {' '.join(out_atoms)} )"]
	elif not len(pyspec):
		# no condition -- these deps are for all python versions, so not a conditional dep:
		out = out_atoms
	else:
		# stuff everything into a python_gen_cond_dep:
		out = [r"$(python_gen_cond_dep '"] + out_atoms + [r"' " + " ".join(pyspec), ")"]
	return out


def expand_pydeps(pkginfo, compat_mode=False, compat_ebuild=False):
	expanded_pydeps = defaultdict(list)
	if "pydeps" in pkginfo:
		pytype = type(pkginfo["pydeps"])
		if pytype == list:
			for dep in pkginfo["pydeps"]:
				# super-simple pydeps are just considered runtime deps
				expanded_pydeps["rdepend"].append(expand_pydep(dep))
		elif pytype == dict:
			for label, deps in pkginfo["pydeps"].items():
				# 'compat mode' means we are actually generating 2 ebuilds, one for py3+ and one for py2
				lsplit = label.split(":")
				if len(lsplit) == 3:
					# modifiers -- affect how deps are understood
					mods = lsplit[-1].split(",")
					# remove mods from label so that create_ebuild_cond_dep doesn't need to understand them.
					label = ":".join(lsplit[:2])
				else:
					mods = []
				if compat_mode:
					# If we are generating a 'compat' ebuild, automatically drop py3 deps
					if compat_ebuild and label == "py:3":
						continue
					# If we are generating a 'non-compat' ebuild, automatically drop py2 deps
					elif not compat_ebuild and label == "py:2":
						continue
				if "build" in mods:
					expanded_pydeps["depend"] += create_ebuild_cond_dep(label, deps)
				else:
					expanded_pydeps["rdepend"] += create_ebuild_cond_dep(label, deps)
	for dep_type in ["depend", "rdepend"]:
		deps = expanded_pydeps[dep_type]
		if not deps:
			continue
		if dep_type not in pkginfo:
			pkginfo[dep_type] = "\n".join(deps)
		else:
			pkginfo[dep_type] += "\n" + "\n".join(deps)
	return None
