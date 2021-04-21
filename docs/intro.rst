What is Metatools?
~~~~~~~~~~~~~~~~~~

Metatools is an advanced framework of powerful technologies to allow
the auto-creation of Gentoo ebuilds, maintenance of an independent fork of
Gentoo or Funtoo, or even building a non-Gentoo distribution. It contains
several technology components, including:

* ``doit``: A YAML and Jinja-based package pure Python auto-generation engine. See
  :ref:`Auto-generation`.

  This is used for auto-generation of
  ebuilds. Auto-generation can mean one or more of the following:

  * Querying upstream APIs such as GitHub_, GitLab_, PyPi_ and Web sites to find latest versions of packages.
  * Leveraging Jinja_ to create ebuilds using templates.
  * Downloading and extracting source code and inspecting build scripts to create ebuilds based on their contents. (example: `xorg-proto`_).

* ``merge-kits``: A YAML-based mechanism to build and update a "meta-repo"
  (ports tree) split into logical "kits", assembling these kits from either
  your own sets of packages or from third-party overlays and repositories.
  ``merge-kits`` leverages multi-threading as well as ``doit`` to perform
  auto-generation of ebuilds on a distro-wide scale. See :ref:`Working with Meta-Repo`.
* ``fastpull``: An efficient HTTP spider and CDN infrastructure, used to
  download and manage source code artifacts, implement
  source code traceability, and seed a content distribution network for
  download of source code.
* ``deepdive``: Package analytics functionality. This allows the contents
  of Funtoo or your distribution to be analyzed via MongoDB queries to
  understading relationships between packages.

.. _GitLab: https://docs.gitlab.com/ee/api/
.. _GitHub: https://developer.github.com/v3/
.. _Jinja: https://jinja.palletsprojects.com/
.. _PyPi: https://pypi.org/
.. _xorg-proto: https://code.funtoo.org/bitbucket/projects/CORE/repos/kit-fixups/browse/core-gl-kit/2.0-release/x11-base/xorg-proto/autogen.py

subpop framework
~~~~~~~~~~~~~~~~

Funtoo-metatools uses subpop_ (Plugin-Oriented Programming)
framework as its foundational paradigm for code organization. Subpop is an
experimental framework that encourages code
maintainability and extensibility, and successfully solves code bloat problems
inherent in application of OOP paradigms at scale. Here are some resources
related to subpop:

* subpop_ (PyPi page)

Subpop and Portage
~~~~~~~~~~~~~~~~~~

I am really excited about subpop because it helps to solve quite a few problems
that the current Portage (Gentoo package manager) code base suffers from.

Portage is not unique in this regard -- it's been around for a while, and has
had a ton of functionality bolted on which has made it hard to improve and
adapt.

In fact, many people who have tried to hook into Portage APIs get frustrated and
create their own code to try to do what they want -- because Portage's code is
set up almost exclusively for the purpose of implementing the functionality of
the ``ebuild`` and ``emerge`` commands -- and not really to be leveraged by
others.

This has been a source of over a decade of frustration for me. After all, I can
remember when ``ebuild`` was simply a 150-line bash script that I wrote. And
surprisingly, it implemented all the necessary functions to build packages. It
was very minimalistic. Now, portage consists of over 1000 *source code files*
and 135,000 lines of Python code. That's just really big.

This isn't really the "fault" of Portage as much as it is the result of being a
project that has been around for a while, and it has grown organically as new
features and capabilities have been added.

You would think that all this new code has resulted in a powerful API that other
people can use to do amazing things. But one of the failings of OOP (Object
Oriented Programming) at scale is that it creates complex hierarchies of
inter-dependent classes that don't really function in a stand-alone fashion. So
while the Portage code base enables ``emerge`` and ``ebuild`` to function, it is
not being leveraged by other tools. It was not really designed to do this.

Plugin-oriented programming helps to fix this. It turns the often insular OOP
paradigm upside-down and provides the technology to not only extend
funtoo-metatools easily, but also allow *your* tools and utilities to leverage
funtoo-metatools' internal code easily. So we're not just building a tool --
we're building a modern community framework that you can both contribute to and
leverage.

Also, please note -- my intent in mentioning Portage is not to pick on it, or
those who have maintained it over the years whose efforts I appreciate, but
rather to explain why I am so excited about building metatools and creating a
framework that can be more successfully leveraged by the Open Source community.
My long-held desire to continue to improve Portage has been restrained by the
very structure of the source code that has evolved within it. Originally,
Portage was a tool that solved problems. It created new paradigms. It has
evolved into something that while still cool, also enforces a paradigm that is
hard to change and adapt to new problems.

Due to our use of subpop, much of metatools functionality is extensible via
plugins. Plugins can be used to enhance the core functionality of the tool in a
modular 'plug-n-play' way, reducing code bloat. Subpop also encourages a simple,
microservices-style archictecture within the code itself. All this is very good
for a complex problem like the automation of updates of packages for the world's
source code.

So, remember -- plugin-oriented programming allows you to do two things. First,
it allows you to easily *extend* funtoo-metatools. Second, through the magic of
dynamic plugin registration, it allows you to easily *leverage* the power of
funtoo-metatools within your own applications. It also provides a really clean
paradigm for adding functionality to funtoo-metatools over time, avoiding
complex internal interdependencies that make code harder to maintain and adapt.

.. _subpop: https://pypi.org/project/subpop/