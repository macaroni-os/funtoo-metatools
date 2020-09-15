#!/usr/bin/python3

import logging

from merge_utils.tree import run


async def get_python_use_lines(hub, catpkg, cpv_list, cur_tree, def_python, bk_python):
	ebs = {}
	for cpv in cpv_list:

		slash = cpv.find("/")
		cat = cpv[:slash]
		pvr = cpv[slash + 1 :]

		last_hyphen = pvr.rfind("-")
		pkg = pvr[:last_hyphen]

		cmd = '( eval $(grep ^PYTHON_COMPAT %s/%s/%s/%s.ebuild 2>/dev/null); echo "${PYTHON_COMPAT[@]}" )' % (
			cur_tree,
			cat,
			pkg,
			pvr,
		)
		outp = run(cmd)

		imps = outp[1].decode("ascii").split()
		new_imps = []

		# Tweak PYTHON_COMPAT just like we now do in the eclass, since we don't extract the data by pumping thru the eclass:

		for imp in imps:
			if imp in ["python3_5", "python3_6", "python3_7"]:
				new_imps.append("python3_7")
			elif imp == "python2+":
				new_imps.extend(["python2_7", "python3_7", "python3_8", "python3_9"])
			elif imp in ["python3+", "python3.7+"]:
				new_imps.extend(["python3_7", "python3_8", "python3_9"])
			elif imp == "python3_8+":
				new_imps.extend(["python3_8", "python3_9"])
			elif imp == "python3_9+":
				new_imps.append("python3_9")
			else:
				new_imps.append(imp)
		imps = new_imps
		if len(imps) != 0:
			ebs[cpv] = imps

	# ebs now is a dict containing catpkg -> PYTHON_COMPAT settings for each ebuild in the catpkg. We want to see if they are identical
	# if split == False, then we will do one global setting for the catpkg. If split == True, we will do individual settings for each version
	# of the catpkg, since there are differences. This saves space in our python-use file while keeping everything correct.

	oldval = None
	split = False
	for key, val in ebs.items():
		if oldval is None:
			oldval = val
		else:
			if oldval != val:
				split = True
				break
	lines = []
	if len(ebs.keys()):
		if not split:
			line = hub._.do_package_use_line(catpkg, def_python, bk_python, oldval)
			if line is not None:
				lines.append(line)
		else:
			for key, val in ebs.items():
				line = hub._.do_package_use_line("=%s" % key, def_python, bk_python, val)
				if line is not None:
					lines.append(line)
	return lines


def do_package_use_line(hub, pkg, def_python, bk_python, imps):
	if "/bin/sh:" in imps:
		logging.error("ERROR in get_python_use line: %s --" % imps)
		return None
	if def_python not in imps:
		if bk_python in imps:
			return "%s python_single_target_%s" % (pkg, bk_python)
		else:
			return "%s python_single_target_%s python_targets_%s" % (pkg, imps[0], imps[0])
	return None
