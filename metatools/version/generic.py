#!/usr/bin/python3

from packaging import version


def parse(v_str):
    """
    This method was added to be used in autogens instead of the commonly-used packaging.version.parse method.
    This was done due to the issue described in FL-10934 -- the behavior of this function changed on the 22
    release of the packaging Python module.

    Ideally, we would want to use our own more sophisticated version-parsing code, but to make it simpler to
    transition the ~100 or so autogen.py files that use version.parse, this function was created.

    It is designed to deliver consistent-enough behavior across packaging versions. It should not return
    an exception but instead parse a string into a Version object that is sortable.
    """
    try:
        v_obj = version.parse(v_str)
        if v_obj.__class__.__name__ == "LegacyVersion":
            return v_obj
    except version.InvalidVersion:
        return version.LegacyVersion(v_str)
    return v_obj
