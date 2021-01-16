#!/usr/bin/env python3

hub = None


def sdist_artifact_url(releases, version):
	# Sometimes a version does not have a source tarball. This function lets us know if our version is legit.
	# Returns artifact_url for version, or None if no sdist release was available.
	for artifact in releases[version]:
		if artifact["packagetype"] == "sdist":
			return artifact["url"]
	return None


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


def expand_pydeps(pkginfo):
	expanded_pydeps = []
	if "pydeps" in pkginfo:
		pytype = type(pkginfo["pydeps"])
		if pytype == list:
			for dep in pkginfo["pydeps"]:
				expanded_pydeps.append(expand_pydep(dep))
		elif pytype == dict:
			for label, deps in pkginfo["pydeps"].items():
				expanded_pydeps += create_ebuild_cond_dep(label, deps)
	if "rdepend" not in pkginfo:
		pkginfo["rdepend"] = "\n".join(expanded_pydeps)
	else:
		pkginfo["rdepend"] += "\n" + "\n".join(expanded_pydeps)
	return None
