#!/usr/bin/env python3


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


def expand_pydep(hub, pyatom):
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


def create_ebuild_cond_dep(hub, pyspec_str, atoms):
	"""
	This function takes a specifier like "py:all" and a list of simplified pythony package atoms and creates a
	conditional dependency for inclusion in an ebuild. It returns a list of lines (without newline termination,
	each string in the list implies a separate line.)
	"""
	out_atoms = []
	pyspec = pyspec_to_cond_dep_args(pyspec_str)

	for atom in atoms:
		out_atoms.append(expand_pydep(hub, atom))

	if not len(pyspec):
		# no condition -- these deps are for all python versions, so not a conditional dep:
		out = out_atoms
	else:
		# stuff everything into a python_gen_cond_dep:
		out = [r"$(python_gen_cond_dep '"] + out_atoms + [r"' " + " ".join(pyspec), ")"]
	return out


def expand_pydeps(hub, pkginfo):
	expanded_pydeps = []
	if "pydeps" in pkginfo:
		pytype = type(pkginfo["pydeps"])
		if pytype == list:
			for dep in pkginfo["pydeps"]:
				expanded_pydeps.append(expand_pydep(hub, dep))
		elif pytype == dict:
			for label, deps in pkginfo["pydeps"].items():
				expanded_pydeps += hub.pkgtools.pyhelper.create_ebuild_cond_dep(label, deps)
	if "rdepend" not in pkginfo:
		pkginfo["rdepend"] = "\n".join(expanded_pydeps)
	else:
		pkginfo["rdepend"] += "\n" + "\n".join(expanded_pydeps)
	return None
