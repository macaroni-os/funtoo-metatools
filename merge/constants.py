#!/usr/bin/python3

from enum import Enum

# These should be kept in-sync with definitions that are in foundations.py.


class KitStabilityRating(Enum):
	PRIME = 0  # Kit is enterprise-quality
	NEAR_PRIME = 1  # Kit is approaching enterprise-quality
	BETA = 2  # Kit is in beta
	ALPHA = 3  # Kit is in alpha
	DEV = 4  # Kit is newly created and in active development
	CURRENT = 10  # Kit follows Gentoo currrent
	DEPRECATED = 11  # Kit is deprecated/retired


class KitType(Enum):
	AUTOMATICALLY_GENERATED = "auto"  # auto-generated
	INDEPENDENTLY_MAINTAINED = "indy"  # independently-maintained
