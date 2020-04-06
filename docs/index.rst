.. funtoo-metatools documentation master file, created by
   sphinx-quickstart on Sat Mar 21 11:42:15 2020.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to funtoo-metatools (aka 'autogen')!
============================================

.. toctree::
   :maxdepth: 2
   :caption: Contents:

Funtoo metatools (also known as funtoo 'autogen') is a technology created by
Daniel Robbins for the Funtoo Linux and other Gentoo-based distributions to
automate the creation of ebuilds. The framework is designed to run in one of
two modes -- either a 'stand-alone' or 'integrated' fashion.

'Stand-alone' mode is designed to be easy-to-use for contributors to the
upstream distribution such as Funtoo Linux. In this mode, contributors can
write their own autogen scripts and test them locally before contributing a
pull request, only needing to install a few python modules.

'Integrated' mode allows the funtoo-metatools technology to be used as part of
a distribution such as Funtoo Linux's 'tree update' scripts, to fire off
auto-generation en masse, and supports advanced features like resilient caching
of HTTP requests in MongoDB and other distribution-class features.

In whatever mode the tools are used, funtoo-metatools is designed to provide
an elegant next-generation API for package creation and maintenance. *That*
is the focus. It's time for a modern paradigm for automated maintenance
of packages. That is what funtoo-metatools provides.

Why not just use Ebuilds and Portage?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Ebuilds are great, and they have served Gentoo and Funtoo well, but they 
have limitations.

For one, they are written in bash shell, which isn't the most modern language.
Bash is slow and is unable to leverage advanced technologies easily. Also, with
ebuilds, you are not really using pure bash -- you have to hook into Portage's
bash-based framework, which is limited in functionality and has limited
mechanisms for adding new functionality. Eclasses are one of those mechanisms
to extend Portage functionality, by allowing OOP-like capabilities within bash.
While respectable, they don't really compare to 'real' OOP. In addition, missing are
modern programming constructs such as asynchronous programming, threads, etc.
Portage's python code uses these behind-the-scenes, but they are not available
to 'regular' ebuild writers. Wouldn't it be nice if the full power of a modern
programming language were available to ebuild writers? That's what
funtoo-metatools is all about -- extending all these technologies to you,
so you can tap into the goodness of modern programming.

Funtoo-metatools provides a framework for creating ebuilds which leverages the
ubiquitous jinja2 templating engine, asynchronous code, and other advances.
But what sets funtoo-metatools apart is the amount of thought and careful
consideration that has gone into its architecture to ensure that it provides a
very high-performance and maintainable code base for the future. A big part
of this is the use of the ``pop`` framework.

Technology Philosophy
~~~~~~~~~~~~~~~~~~~~~

Funtoo-metatools uses Thomas Hatch's ``pop`` (Plugin-Oriented Programming)
framework as its foundational paradigm for code organization. Pop is a next-
generation framework that encourages code maintainability and extensibility,
and successfully solves code bloat problems inherent in application of OOP
paradigms at scale -- many of which the current Portage code base suffers from.
Portage is not unique in this regard -- it's been around for a while, and has
had a ton of functionality bolted on -- and this has resulted in a large,
monolithic code base with a lot of functionality. And yet, as a code base,
it is hard to improve and adapt.

In fact, many people who have tried to hook into Portage APIs get frustrated
and create their own code to try to do what they want -- because Portage's code
is set up almost exclusively for the purpose of implementing the functionality
of the ``ebuild`` and ``emerge`` commands -- and not really to be leveraged by
others. This isn't really the "fault" of Portage as much as it is a modern
failing of OOP at scale which creates complex heirarchies of inter-dependent
classes that don't really function in a stand-alone fashion. Plugin-oriented
programming turns the often insular OOP paradigm upside-down and provides the
technology to not only extend funtoo-metatools easily, but also allow *your*
tools and utilities to leverage funtoo-metatools' internal code easily. So
we're not just building a tool -- we're building a modern community framework
that you can both contribute to and leverage.

I am excited to have this technology available for funtoo-metatools and it
dramatically enhances the interal code architecture.  Due to our use of
``pop``, much of funtoo-metatools functionality is extensible via plugins.
Plugins can be used to enhance the core functionality of the tool in a modular
'plug-n-play' way, reducing code bloat. ``pop`` also encourages a simple,
microservices-style archictecture within the code itself. All this is very
good for a complex problem like the automation of updates of packages for
the world's source code.

So, remember -- plugin-oriented programming allows you to do two things. First,
it allows you to easily *extend* funtoo-metatools. Second, through the magic of
dynamic plugin registration, it allows you to easily *leverage* the power of
funtoo-metatools within your own applications. It also provides a really clean
paradigm for adding functionality to funtoo-metatools over time, avoiding
complex internal interdependencies that make code harder to maintain and adapt.
Of course, for day-to-day usage of funtoo-metatools, you are simply *using*
the framework, and we'll cover that next.

Installation
============

These instructions asssume you are using Funtoo Linux but should be easy to adapt
to other distributions.

Funtoo-metatools is easy to install. On Funtoo, it can simply be emerged::

  # emerge metatools

The primary executable, ``doit``, will now be in your path.

Alternatively you can use ``pip3`` to pull it from PyPi::

  $ pip3 install --user funtoo-metatools

If you would like to create an isolated virtual environment for funtoo-metatools,
you can use virtualenv as follows::

  $ emerge virtualenv
  $ virtualenv -p python3 venv
  $ source venv/bin/activate
  (venv) $ pip install funtoo-metatools

From this point forward, whenever you want to use the virtualenv, simply
source the activate script to enter your isolated python virtual environment.

Quick Usage
===========

To use the tool, go into an autogen-enabled tree like Funtoo's kit-fixups
repository and run ``doit``. This will auto-generate all ebuilds in the current
directory and below.

For production usage, install and start ``mongodb``, and run ``doit --cacher=mongodb``.
This will tell the framework to cache all HTTP requests in MongoDB so that if
an autogen script fails it will still be able to successfully generate ebuilds
using cached data.

Examples
========

Next, take a look at the contents of the ``example-overlay`` directory. This is a
Funtoo overlay or kit which contains a couple of catpkgs that perform auto-generation.

The ``net-im/discord-bin/autogen.py`` script
will auto-create a new version of a Discord package by grabbing the contents of an HTTP
redirect which contains the name of the current version of Discord. The Discord artifact
(aka SRC_URI) will then be downloaded, and new Discord ebuild generated with the proper
version. The 'master' ebuild is stored in ``net-im/discord-bin/templates/discord.tmpl`` and
while jinja2 templating is supported, no templating features are used so the template
is simply written out to the proper ebuild filename as-is.

The ``x11-base/xorg-proto/autogen.py`` script is more complex, and actually generates
around 30 ebuilds. This file is heavily commented and also takes advantage of jinja
templating.

Performing Auto-Generation
==========================

To actually use these tools to auto-generate ebuilds, you can simply change directories
into the ``example-overlay`` directory and run the ``doit`` command::

  $ doit

When ``doit`` runs, it will attempt to auto-detect the root of the overlay you are
currently in (a lot like how git will attempt to determine what git repo it is in.)
Then, it will look for all ``autogen.py`` scripts from the current directory and
deeper and execute these auto-generation scripts to generate ebuilds.

After running the command, you should be able to type ``git status`` to see all the
files that were generated.

Using in Overlays
=================

The ``example-overlay`` directory is included only as an example, and the ``doit``
command is capable of applying its magic to any overlay or kit. The tool will attempt
to determine what directory it is in by looking for a ``profiles/repo_name`` file in
the current or parent directory, so if your overlay or kit is missing this file then
``doit`` won't be able to detect the overlay root. Simply create this file and add
a single line containing the name of the repo, such as ``my-overlay``, for example.

Metatools is used extensively by Funtoo's `kit-fixups repository
<https://code.funtoo.org/bitbucket/projects/CORE/repos/kit-fixups/browse>`_.

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
