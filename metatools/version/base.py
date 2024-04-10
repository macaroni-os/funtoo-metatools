#!/usr/bin/python3

"""
This code is intended to support a retargetable versioning API that can support basic versions, Gentoo
versions and potentially other versions.
"""
from collections import OrderedDict

from enum import Enum


class VersionFeature(Enum):
    VERSION = 0
    ALPHA = 1
    BETA = 2
    PRE = 3
    RC = 4
    PATCH_LEVEL = 5
    LETTER_RELEASE_LEVEL = 6
    REVISION = 7


class VersionSpecifier:
    weight = 0
    feature = None
    pattern = None

    def __init__(self, weight=None, feature: VersionFeature = None, pattern: str = None):
        if weight is not None:
            self.weight = weight
        self.feature = feature
        self.pattern = pattern


class Version:
    weights: OrderedDict = None


class GentooVersion(Version):
    """
    This class enumerates the different kinds of version components that can appear -- we can use this
    to define what version components are actually supported -- and use them as toggles -- and use the
    integer values to define their relative weights. Negative values should be used to set the relative
    weight for a "prerelease" (less than official x.y release) version, while positive values should be
    used to set relative weights for "post-release". For example, an alpha would be considered the
    earliest release of a specific version, so it would have a higher negative number, but a beta, while
    still a prerelease, would have a negative number closer to zero.
    """

    suffixes = [
        OrderedDict(
            LETTER_RELEASE_LEVEL=VersionSpecifier(weight=-200, feature=VersionFeature.REVISION, pattern="[a-z]"),
        ),
        OrderedDict(
        ALPHA=VersionSpecifier(weight=-1000, feature=VersionFeature.ALPHA, pattern="_alpha([0-9]+)?"),
        BETA=VersionSpecifier(weight=-900, feature=VersionFeature.BETA, pattern="_beta([0-9]+)?"),
        PRE=VersionSpecifier(weight=-800, feature=VersionFeature.PRE, pattern="_pre([0-9]+)?"),
        RC=VersionSpecifier(weight=-200, feature=VersionFeature.RC, pattern="_rc[0-9]+"),
        PATCH_LEVEL=VersionSpecifier(weight=100, feature=VersionFeature.PATCH_LEVEL, pattern="_p[0-9]+"),
        )
    ]


class GentooVersionAndRevision(GentooVersion):

    """
    TODO: default revision is zero.
    TODO: make sure 
    """

    def __init__(self):
        self.suffixes += OrderedDict(REVISION=VersionSpecifier(weight=-100, feature=VersionFeature.REVISION, pattern="-r[1-9][0-9]*"))
