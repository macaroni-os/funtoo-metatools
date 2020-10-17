Autogeneration Primer
=====================

The framework is designed to run in one of two modes -- either a 'stand-alone'
or 'integrated' fashion.

'Stand-alone' mode is designed to be easy-to-use for contributors to the
upstream distribution such as Funtoo Linux. In this mode, contributors can write
their own autogen scripts and test them locally before contributing a pull
request, only needing to install a few python modules.

'Integrated' mode allows the funtoo-metatools technology to be used as part of a
distribution such as Funtoo Linux's 'tree update' scripts, to fire off
auto-generation en masse, and supports advanced features like resilient caching
of HTTP requests in MongoDB and other distribution-class features.

In whatever mode the tools are used, funtoo-metatools is designed to provide an
elegant next-generation API for package creation and maintenance. *That* is the
focus. It's time for a modern paradigm for automated maintenance of packages.
That is what funtoo-metatools provides.

Why not just use Ebuilds and Portage?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Ebuilds are great, and they have served Gentoo and Funtoo well, but they have
limitations.

For one, they are written in bash shell, which isn't the most modern language.
Bash is slow and is unable to leverage advanced technologies easily. Also, with
ebuilds, you are not really using pure bash -- you have to hook into Portage's
bash-based framework, which is limited in functionality and has limited
mechanisms for adding new functionality. Eclasses are one of those mechanisms to
extend Portage functionality, by allowing OOP-like capabilities within bash.
While respectable, they don't really compare to 'real' OOP. In addition, missing
are modern programming constructs such as asynchronous programming, threads,
etc. Portage's python code uses these behind-the-scenes, but they are not
available to 'regular' ebuild writers. Wouldn't it be nice if the full power of
a modern programming language were available to ebuild writers? That's what
funtoo-metatools is all about -- extending all these technologies to you, so you
can tap into the goodness of modern programming.

Funtoo-metatools provides a framework for creating ebuilds which leverages the
ubiquitous jinja2 templating engine, asynchronous code, and other advances. But
what sets funtoo-metatools apart is the amount of thought and careful
consideration that has gone into its architecture to ensure that it provides a
very high-performance and maintainable code base for the future. A big part of
this is the use of the ``pop`` framework.


Performing Auto-Generation
~~~~~~~~~~~~~~~~~~~~~~~~~~

To actually use these tools to auto-generate ebuilds, you can simply change
directories into the ``example-overlay`` directory and run the ``doit``
command::

  $ doit

When ``doit`` runs, it will attempt to auto-detect the root of the overlay you are
currently in (a lot like how git will attempt to determine what git repo it is in.)
Then, it will look for all ``autogen.py`` scripts and ``autogen.yaml`` files from
from the current directory and deeper and execute these auto-generation scripts
to generate ebuilds.

After running the command, you should be able to type ``git status`` to see all the
files that were generated.

Using in Overlays
~~~~~~~~~~~~~~~~~

The ``example-overlay`` directory is included only as an example, and the
``doit`` command is capable of applying its magic to any overlay or kit. The
tool will attempt to determine what directory it is in by looking for a
``profiles/repo_name`` file in the current or parent directory, so if your
overlay or kit is missing this file then ``doit`` won't be able to detect the
overlay root. Simply create this file and add a single line containing the name
of the repo, such as ``my-overlay``, for example.

Metatools is used extensively by Funtoo's `kit-fixups repository
<https://code.funtoo.org/bitbucket/projects/CORE/repos/kit-fixups/browse>`_.


Quick Usage
~~~~~~~~~~~

To use the tool, go into an autogen-enabled tree like Funtoo's kit-fixups
repository and run ``doit``. This will auto-generate all ebuilds in the current
directory and below.

For production usage, install and start ``mongodb``, and run ``doit
--cacher=mongodb``. This will tell the framework to cache all HTTP requests in
MongoDB so that if an autogen script fails it will still be able to successfully
generate ebuilds using cached data.

Examples
~~~~~~~~

Next, take a look at the contents of the ``example-overlay`` directory. This is
a Funtoo overlay or kit which contains a couple of catpkgs that perform
auto-generation.

The ``net-im/discord-bin/autogen.py`` script will auto-create a new version of a
Discord package by grabbing the contents of an HTTP redirect which contains the
name of the current version of Discord. The Discord artifact (aka SRC_URI) will
then be downloaded, and new Discord ebuild generated with the proper version.
The 'master' ebuild is stored in ``net-im/discord-bin/templates/discord.tmpl``
and while jinja2 templating is supported, no templating features are used so the
template is simply written out to the proper ebuild filename as-is.

The ``x11-base/xorg-proto/autogen.py`` script is more complex, and actually
generates around 30 ebuilds. This file is heavily commented and also takes
advantage of jinja templating.