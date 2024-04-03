#!/usr/bin/python3

from packaging import version


def parse(v_str):
    try:
        v_obj = version.parse(v_str)
        if v_obj.__class__.__name__ == "LegacyVersion":
            return None
    except version.InvalidVersion:
        return None
    return v_obj
