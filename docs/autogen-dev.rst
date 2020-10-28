Developing Auto-Generation Scripts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Now that we've covered how to execute auto-generation scripts, let's take a look at creating them.

Basic Stand-Alone Layout
------------------------

The simplest form of auto-generation is called *stand-alone* auto-generation. Stand-alone auto-generation scripts
have the name ``autogen.py`` and can be located inside a catpkg directory -- at the same level that you would place
ebuilds. Typically, you would also create a ``templates/`` directory next to ``autogen.py``, containing template files
that you use to create your final ebuilds. For example, if we were doing an autogen for a package called ``sys-apps/foobar``,
which is a "core" system package, we would:

1. Create an ``autogen.py`` file at ``kit-fixups/curated/sys-apps/foobar/autogen.py``
2. Create a ``kit-fixups/curated/sys-apps/foobar/templates/foobar.tmpl`` file (a template for the ebuild.)

The Generator
-------------

The ``autogen.py`` script is, as you might guess, a python file. And it is actually treated as a *plugin* (see
:ref:`POP Framework`) which gives it a special structure. The auto-generation function that gets called to do all
the things is called ``generate()`` and should be defined as:

.. code-block:: python

   async def generate(hub, **pkginfo):

Here is a full example of an ``autogen.py`` that implements auto-generation of the ``sys-apps/hwids`` package:

.. code-block:: python

  #!/usr/bin/env python3

  async def generate(hub, **pkginfo):
    github_user = "gentoo"
    github_repo = "hwids"
    json_list = await hub.pkgtools.fetch.get_page(
        f"https://api.github.com/repos/{github_user}/{github_repo}/tags", is_json=True
    )
    latest = json_list[0]
    version = latest["name"].split("-")[1]
    url = latest["tarball_url"]
    final_name = f'{pkginfo["name"]}-{version}.tar.gz'
    ebuild = hub.pkgtools.ebuild.BreezyBuild(
        **pkginfo,
        github_user=github_user,
        github_repo=github_repo,
        version=version,
        artifacts=[hub.pkgtools.ebuild.Artifact(url=url, final_name=final_name)],
    )
    ebuild.push()


The ``doit`` command, when run, will find this ``autogen.py`` file, map it as a plugin, and execute its ``generate()``
method. This particular auto-generation plugin will perform the following actions:

1. Query GitHub's API to determine the latest tag in the ``gentoo/hwids`` repository.
2. Download an archive (called an *Artifact*) of this source code if it has not been already downloaded.
3. Use ``templates/hwids.tmpl`` to generate a final ebuild with the correct version.
4. Generate a ``Manifest`` referencing the downloaded archive.

After ``autogen.py`` executes, you will have a new ``Manifest`` file, as well as a ``hwids-x.y.ebuild`` file in
the places you would expect them. These files are not added to the git repository -- and typically, when you are
doing local development and testing, you don't want to commit these files. But you can use them to verify that the
autogen ran successfully.

The Base Objects
----------------

Above, you'll notice the use of several objects. Let's look at what they do:

``hub.pkgtools.ebuild.Artifact``
  This object is used to represent source code archives, also called "artifacts". Its constructor accepts two
  keyword arguments. The first is ``url``, which should be the URL that can be used to download the artifact.
  The second is ``final_name``, which is used to specify an on-disk name if the ``url`` does not contain this
  information. If ``final_name`` is omitted, the last part of ``url`` will be used as the on-disk name for
  the artifact.

``hub.pkgtools.ebuild.BreezyBuild``
  This object is used to represent an ebuild that should be auto-generated. When you create it, you should pass
  a list of artifacts in the ``artifacts`` keyword argument for any source code that it needs to download and
  use.

These objects are used to create a declarative model of ebuilds and their artifacts, but simply creating these
objects doesn't actually result in any action. You will notice that the source code above, there is a call
to ``ebuild.push()`` -- this is the command that adds our ``BreezyBuild`` (as well as the artifact we passed to
it) to the auto-generation queue. ``doit`` will "instantiate" all objects on its auto-generation queue, which
will actually result in action.

What will end up happening is that the ``BreezyBuild`` will ensure that all of its source code artifacts have
been downloaded ("fetched") and then it will use this to create a ``Manifest`` as well as the ebuild itself.

pkginfo
-------

You will notice that our main ``generate`` function contains an argument called ``**pkginfo``. You
will also notice that we pass ``**pkginfo`` to our ``BreezyBuild``, as well as other additional information.
What is this "pkginfo"? It is a python dictionary containing information about the catpkg we are generating.
We take great advantage of "pkginfo" when we use advanced YAML-based ebuild auto-generation, but it is
still something useful when doing stand-alone auto-generation. The ``doit`` command will auto-populate
``pkginfo`` with the following key/value pairs:

``name``
  The package name, i.e. ``hwids``.
``cat``
  The package category, i.e. ``sys-apps``.
``template_path``
  The path to where the templates are located for this autogen, i.e. the ``templates`` directory next to
  the ``autogen.py``

While this "pkginfo" construct doesn't seem to useful right now, it will soon once you start to take
advantage of advanced autogen features. For now, it at least helps
us to avoid having to explicitly passing ``name``, ``cat`` and ``template_path`` to our ``BreezyBuild`` --
these are arguments that our ``BreezyBuild`` expects and we can simply "pass along" what was auto-detected
for us rather than specifying them manually.


