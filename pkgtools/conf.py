import os

CONFIG = {
    "start_path": {
        'default': os.getcwd(),
        'os': 'AUTOGEN_START_PATH',
        'help': 'Where to start processing'
    },
    "out_path": {
        'default': None,
        'os': 'AUTOGEN_OUTPUT_PATH',
        'help': 'Destination repository path'
    },
    "name": {
        'default': None,
        'os': 'AUTOGEN_REPONAME',
        'help': 'Repository name (to override)'
    },
    "temp_path": {
        'default': '/var/tmp/autogen',
        'os': 'AUTOGEN_TEMP',
        'help': 'Temporary path for downloading and extracting.'
    },
    "fetcher": {
        'default': 'default',
        'os': 'AUTOGEN_FETCHER',
        'help': 'What fetching plugin to use.'
    },
    "cacher": {
        'default': 'noop',
        'os': 'AUTOGEN_CACHER',
        'help': 'What caching plugin to use.'
    }
}

CLI_CONFIG = {
    "start_path": {},
    "out_path": {},
    "temp_path": {},
    "fetcher": {},
    "cacher": {}
}

DYNE = {'pkgtools': ['pkgtools']}

