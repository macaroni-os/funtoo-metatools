****************
Funtoo Metatools
****************

Copyright 2020 Daniel Robbins, Funtoo Solutions, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Installation
*************

To test out Funtoo Metatools, perform the following steps::

  $ emerge pip
  $ pip3 install --user pop
  $ emerge www-servers/tornado aiohttp
  $ emerge jinja

Now, set PYTHONPATH to point to the directory of the tools. Assuming that
``funtoo-metatools`` is in ``~development/``, perform the following::

  $ export PYTHONPATH=~/development/funtoo-metatools

It is also highly recommended to add ``~/development/funtoo-metatools/bin`` to your
path so that ``autogen`` is found.

Examples
********

Next, take a look at the contents of the ``example-overlay`` directory. This is a
Funtoo overlay or kit which contains a couple of catpkgs that perform auto-generation.

The ``net-im/discord/autogen.py`` script
will auto-create a new version of a Discord package by grabbing the contents of an HTTP
redirect which contains the name of the current version of Discord. The Discord artifact
(aka SRC_URI) will then be downloaded, and new Discord ebuild generated with the proper
version. The 'master' ebuild is stored in ``net-im/discord/templates/discord.tmpl`` and
while jinja2 templating is supported, no templating features are used so the template
is simply written out to the proper ebuild filename as-is.

The ``x11-base/xorg-proto/autogen.py`` script is more complex, and actually generates
around 30 ebuilds. This file is heavily commented and also takes advantage of jinja
templating.

Performing Auto-Generation
**************************

To actually use these tools to auto-generate ebuilds, you can simply change directories
into the ``example-overlay`` directory and run the ``autogen`` command::

  $ autogen

When ``autogen`` runs, it will attempt to auto-detect the root of the overlay you are
currently in (a lot like how git will attempt to determine what git repo it is in.)
Then, it will look for all ``autogen.py`` scripts from the current directory and
deeper and execute these auto-generation scripts to generate ebuilds.

After running the command, you should be able to type ``git status`` to see all the
files that were generated.

Using Meta-Tools
****************

The ``example-overlay`` directory is included only as an example, and the ``autogen``
command is capable of applying its magic to any overlay or kit. The tool will attempt
to determine what directory it is in by looking for a ``profiles/repo_name`` file in
the current or parent directory, so if your overlay or kit is missing this file then
``autogen`` won't be able to detect the overlay root. Simply create this file and add
a single line containing the name of the repo, such as ``my-overlay``, for example.