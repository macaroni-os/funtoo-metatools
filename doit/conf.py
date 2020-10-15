import os

CONFIG = {}
CLI_CONFIG = {
	"start_path": {"default": os.getcwd(), "os": "AUTOGEN_START_PATH", "help": "Where to start processing"},
	"out_path": {"default": None, "os": "AUTOGEN_OUTPUT_PATH", "help": "Destination repository path"},
	"name": {"default": None, "os": "AUTOGEN_REPONAME", "help": "Repository name (to override)"},
	"fetcher": {"default": "default", "os": "AUTOGEN_FETCHER", "help": "What fetching plugin to use."},
	"release": {"default": None, "help": "Specify a release (used for production distfile integrity/fastpull.)"},
	"kit": {"default": None, "help": "Specify a kit (used for production distfile integrity/fastpull.)"},
	"branch": {"default": None, "help": "Specify a branch (used for production distfile integrity/fastpull.)"},
	"fastpull": {"default": None, "action": "store_true", "help": "Enable fastpull reads and writes."},
}

DYNE = {"doit": ["doit"]}
