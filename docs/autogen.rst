Auto-generation
===============

``metatools`` includes the ``doit`` command, which implements "auto-generation"
of ebuilds. But what exactly is "auto-generation"?

In its broadest sense, "auto-generation" is the high-level creation of ebuilds.
This can involve any number of advanced capabilities,
such as querying GitHub_ or GitLab_ to find the latest version of a package,
actually fetching source code and looking inside it, or using Jinja_ to generate
ebuilds using templates. Typically, multiple approaches are used together.

We use these capabilities to *reduce the manual labor required to
maintain packages*. These capabilities
exist to give us *leverage* over the complex world of software so that we
can automate as much as possible, so we can do more with less.

Running Auto-Generation
~~~~~~~~~~~~~~~~~~~~~~~

To actually use these tools to auto-generate ebuilds, it is recommended that you
check out the `kit-fixups`_ repository, which is the master repository of Funtoo
Linux. This repository is organized into directories for each kit, and sub-directories
for each kit version, with ``current`` often used as a sub-directory name for kit
version. So, for example, if we wanted to auto-generate all ebuilds in
``core-kit/current``, we would do this::

  $ cd development
  $ git clone https://code.funtoo.org/bitbucket/scm/core/kit-fixups.git
  $ cd kit-fixups/core-kit/curated
  $ doit

In the above example, it will see that the directory ``kit-fixups/core-kit/curated``
is an overlay that contains categories, and it will look inside it for all "autogens"
and execute them.

When ``doit`` runs, it will determine its context by looking at the current
working directory, similar to how the ``git`` command will find what git
repository it is in by looking backwards from the current working directory. It
will then fire off auto-generation in the current directory, looking in the
current directory *and any sub-directories* for all autogens, and will execute
them. You will see a lot of ``....`` being printed on the screen, which means
that files are being downloaded. What is actually happening is that ``doit`` is
querying Web APIs like GitHub and GitLab to find the latest versions of
packages, and then downloading the source code tarballs (in ``metatools``
vernacular: "artifacts") for these packages, and a period is printed for each
block of data received to show progress. Often times, multiple artifacts are
being downloaded at the same time. Then, as the artifacts are received,
``doit`` creates ebuilds for these packages, and also creates ``Manifest``
files referencing the SHA512 and other digests of the downloaded Artifacts. You
end up with ebuilds that you can test out by running ``ebuild foo-1.0.ebuild
clean merge``.

Where are these "autogens"? They are ``autogen.py`` files that exist in the
repository. Think of our autogens as plug-ins, written in Python and leveraging
the :ref:`subpop framework`, that contain a ``generate()`` function which can
generate one or more ebuilds using the ``metatools`` API. The ``metatools``
API, which we'll look at in a bit, is an extensible API that lets us query Web
APIs, use Jinja and perform other neat tricks to generate ebuilds.

In addition to raw autogens, there are also ``autogen.yaml`` files which allow
for creation of ebuilds *en masse*. In the YAML, you specify an autogen (also
called a metatools "generator") plus packages and package-specific metadata to
feed to that generator. When you feed package data to a generator, it spits out
ebuilds. This is both highly efficient (it's fast) and also a nice way to
generate ebuilds with little or no redundant code. ``metatools`` contains a
number of built-in generators that can be used with the YAML system, such as
generators that build ebuilds for Python packages on PyPi.

Go ahead and poke around inside `kit-fixups`_ and look at the ``autogen.py``
and ``autogen.yaml`` files. You'll begin to get a sense for what they look like
and and inkling of how everything works.

Also type ``git status``. You should see that a bunch of ebuilds (along with
``Manifest`` files) were created. These files are *not* added to git. They
simply sit in your local repo, and you can blow them away by running::

  $ git clean -fd

When doing developent, we actually *do not* want to commit the auto-generated
ebuilds themselves to `kit-fixups`_ -- we just want to commit the autogens
(``autogen.py`` and ``autogen.yaml``.) There is a separate step, peformed by
the ``merge-kits`` command, which updates the meta-repo and will commit the
generated ebuilds to kits which are then pushed out to users. But for
``kit-fixups``, we're doing development, not updating the tree, so we just want
to commit the autogens.

.. include:: autogen-dev.rst

.. _kit-fixups: https://code.funtoo.org/bitbucket/projects/CORE/repos/kit-fixups/browse
.. _GitLab: https://docs.gitlab.com/ee/api/
.. _GitHub: https://developer.github.com/v3/
.. _Jinja: https://jinja.palletsprojects.com/
