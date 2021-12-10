#!/usr/bin/env python3

from datetime import datetime
import dyne.org.funtoo.metatools.merge as merge



def get_copyright_rst(active_repo_names):
	cur_year = str(datetime.now().year)
	out = merge.model.foundation_data["copyright"]["default"].replace("{{cur_year}}", cur_year)
	for overlay in sorted(active_repo_names):
		if overlay in merge.model.foundation_data["copyright"]:
			out += merge.model.foundation_data["copyright"][overlay].replace("{{cur_year}}", cur_year)
	return out




