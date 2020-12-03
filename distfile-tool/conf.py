#!/usr/bin/env python3

CONFIG = {}

CLI_CONFIG = {
	"release": {"positional": True},
	"out": {"default": None, "help": "Write out JSON data of missing files to this file. (default off)"},
}

DYNE = {"distfile-tool": ["distfile-tool"]}
