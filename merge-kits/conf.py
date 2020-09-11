#!/usr/bin/env python3

CONFIG = {}

CLI_CONFIG = {
	"force": {"options": ["--force"], "action": "store_true", "default": False},
	"nopush": {"options": ["--nopush"], "action": "store_true", "default": False},
	"prod": {"options": ["--prod"], "action": "store_true", "default": False},
	"db": {"options": ["--db"], "action": "store_true", "default": False},
	"release": {"positional": True},
}

DYNE = {"merge-kits": ["merge-kits"]}
