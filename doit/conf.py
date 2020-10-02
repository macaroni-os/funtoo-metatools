import os

CONFIG = {}
CLI_CONFIG = {
	"start_path": {"default": os.getcwd(), "os": "AUTOGEN_START_PATH", "help": "Where to start processing"},
	"out_path": {"default": None, "os": "AUTOGEN_OUTPUT_PATH", "help": "Destination repository path"},
	"name": {"default": None, "os": "AUTOGEN_REPONAME", "help": "Repository name (to override)"},
	"fetcher": {"default": "default", "os": "AUTOGEN_FETCHER", "help": "What fetching plugin to use."},
	"job" : {"default": None, "help": "Specify a unique ID for the job that is running to segregate tempfiles and prevent conflicts."}
}

DYNE = {"doit": ["doit"]}
