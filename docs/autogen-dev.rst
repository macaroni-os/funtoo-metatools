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

The ``autogen.py`` script is, as you might guess, a python file. And it is actually treated as a *plugin*
which gives it a special structure. The auto-generation function that gets called to do all
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


The ``doit`` command, when run in the same directory in the ``autogen.py`` or in a parent directory that
is still in the repo, will find this ``autogen.py`` file, map it as a plugin, and execute its ``generate()``
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

pkginfo Basics
--------------

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
``gen_path``
  This is a special variable that will allow you to reference the path where the ``autogen.yaml`` or
  ``autogen.py`` lives, from the perspective of the ebuild. This is useful if you are generating a
  bunch of ebuilds in different categories, but you want to have all files in ``files/${PN}/<filename>``
  relative to the actual autogen instead of in ``${FILESDIR}``. In this scenario, in the ebuild, you can
  reference patches by using the reference ``{{gen_path}}/${PN}/my-pkg.patch`` instead of
  ``${FILESDIR}/my-pkg.path``. Behind the scenes, ``gen_path`` uses ``${FILESDIR}`` and some path
  magic to reference the correct path to find the files you want in the ``kit-fixups`` repo.


While this "pkginfo" construct doesn't seem to be the most useful thing right now, it will soon once you start to take
advantage of advanced autogen features. For now, it at least helps
us to avoid having to explicitly passing ``name``, ``cat`` and ``template_path`` to our ``BreezyBuild`` --
these are arguments that our ``BreezyBuild`` expects and we can simply "pass along" what was auto-detected
for us rather than specifying them manually.

BreezyBuild Basics
------------------

There are also several values that you typically pass in to the ``BreezyBuild`` constructor as keyword
arguments to augment what is automatically set for you via ``pkginfo``. These arguments are:

``version``
  The version of the ebuild you are generating (not including revision). Auto-generated BreezyBuilds will
  often perform some HTTP calls to figure out the latest available version of a package, and generate that
  version. The version is passed into the BreezyBuild constructor this way.
``revision``
  The ebuild revision, specified as an integer. This defaults to 0.
``artifacts``
  This is a list or dictionary of ``Artifact`` objects that represent downloadable files that the ebuild
  uses -- things that would typically go in ``SRC_URI`` in the ebuild. Artifacts are 'special' as the
  ``BreezyBuild`` will ensure that all artifacts are fetched and will also take care of auto-generating
  Portage Manifest files using the results of the fetch.


Querying APIs
-------------

It is not required that you query APIs to determine the latest version of a package to build, but this is
often what is done in an ``autogen.py`` file. To this end, the official method to grab data from a remote
API is ``hub.pkgtools.fetch.get_page()``. Since this is an ``async`` function, it must be ``await``\ ed.
If what you are retrieving is JSON, then you should pass ``is_json=True`` as a keyword argument, and you
will get decoded JSON as a return value. Otherwise, you will get a string and will be able to perform
additional processing. For HTML data, typically people will use the ``re`` (regular expression) module
to extract data, and ``lxml`` or ``xmltodict`` can be used for parsing XML data.

There is also a ``refresh_interval`` keyword argument which can be used to limit updates to the remote
resource to a certain time interval. For example, this is used with the ``brave-bin`` autogen to ensure
that we only get updates every 5 days (they update the Brave browser daily and this update interval
is a bit too much for us):

.. code-block:: python

   json_dict = await hub.pkgtools.fetch.get_page(
     "https://api.github.com/repos/brave/brave-browser/releases", is_json=True, refresh_interval=timedelta(days=5)
   )

If you run ``merge-kits``, or even ``doit`` in a repository that hits the GitHub API a lot, you will
quickly discover that GitHub has rate limiting for unauthenticated API requests. To address this, it is
possible to specify authentication for GitHub by creating a ``~/.autogen`` file as follows::

  authentication:
    api.github.com:
      username: mygithub_username
      password: 123409809abcda098ad098a0v0a98098098d09d

In the above file, which is in YAML format, specify a *personal access token* value for *password*. In
the GitHub UI, you can create personal access tokens by navigating to:

1. Settings
2. Developer Settings
3. Personal Access Tokens

When this is set up, ``doit`` will now authenticate to GitHub for every GitHub API call, which should result
in no more 'access denied' messages.

The ``~/.autogen`` ``authentication`` section is totally extensible. If you find new sites that require
authentication, just put the necessary credentials in the file. If the API request matches the specified hostname,
the credentials will be used. The credentials are passed using HTTP basic authentication.


HTTP Tricks
-----------

Sometimes, it is necessary to grab the destination of a HTTP redirect, because the version of an
artifact will be in the redirected-to URL itself. For example, let's assume that when you go to
``https://foo.bar.com/latest.tar.gz``, you are instantly redirected to ``https://foo.bar.com/myfile-3002.tar.gz``.
To grab the redirected-to URL, you can use the following method:

.. code-block:: python

  next_url = await hub.pkgtools.fetch.get_url_from_redirect("https://foo.bar.com/latest.tar.gz")


``next_url`` will now contain the string ``https://foo.bar.com/myfile-3002.tar.gz``, and you can
pull it apart using standard Python string operators and methods to get the version from it.

Note that both the `Zoom-bin autogen`_ and `Discord-bin autogen`_ use this technique.

Using Jinja in Templates
------------------------

Up until now, we have not really talked about Templates. Templates contain the actual literal content
of your ebuild, but can include Jinja processing statements such as variables and even conditionals and
loops. *Everything passed to your ``BreezyBuild``* can be expanded as a Jinja variable. For example,
you can use the following variables inside your template:

``{{cat}}``
  Will expand to package category.
``{{name}}``
  Will expand to package name (without version).
``{{version}}``
  Will expand to package version.
``{{artifacts[0].src_uri}}``
  Will expand to the string to be included in the ``SRC_URI`` for the first (and possibly only) Artifact.
``SRC_URI="{{artifacts|map(attribute='src_uri')|join(' ')}}"``
  Will expand to be your full ``SRC_URI`` definition assuming you don't have any conditional ones based on
  ``USE`` variables.

It's important to note that in some cases, you will not even need to use a single Jinja-ism in your
template, and can simply have the entire literal ebuild as the contents of your template. The
`Discord-bin autogen`_ template is like this and simply contains the contents of the ebuild, because
the only thing that changes between new Jinja versions is the filename of the ebuild, but not anything
in the ebuild itself. So we don't need to expand any variables.

But when we get into more advanced examples, particularly YAML-based auto-generation, Jinja tends to
be used more heavily.

Here are some other Jinja constructs you may find useful:

.. code-block:: jinja

  {%- if myvar is defined %}
  myvar is defined.
  {%- else %}
  myvar is not defined.
  {%- endif %}

  {%- if foo == "bar" %}
  This text will only be included if the variable "foo" equals the string "bar".
  {%- elif foo == "oni" %}
  Hmmm... foo is oni?
  {%- endif %}

  {%- for file in mylist %}
  {{file}}
  {%- endfor %}

You can see that Jinja gives you a lot of power to generate the final representation of the ebuild that you
want. Remember that you can always pass new keyword arguments to the constructor for ``BreezyBuild`` and
then access them in your templates. For more information on what Jinja can do, browse the
`official Jinja Documentation`_ or look in the kit-fixups repo for interesting examples.


Using Multiple Templates or BreezyBuilds
----------------------------------------

As mentioned earlier, you can place templates in the `templates/` directory next to your autogen, and
by default, the ``BreezyBuild`` will use the template with the same name as your package. To change this, you
can pass the ``template="anothertemplate.tmpl"`` keyword argument to your ``BreezyBuild`` or pass a different
``name`` to your ``BreezyBuild`` (``name`` is normally part of the ``**pkginfo`` dict.) You might want
to do this if you are using your ``autogen.py`` to generate *more than one* ebuild -- which is perfectly
legal and supported. In this case, you will want to vary the ``name`` and/or ``cat`` arguments that get
passed to ``BreezyBuild`` (these typically come via ``**pkginfo``) to specify a new package name and/or
category. Remember to call ``.push()`` for every ebuild you want to generate. See the `Virtualbox-bin Autogen`_
for an example.

Introspecting Inside Artifacts
------------------------------

You may be wondering if it is possible to grab a source tarball, look inside it, and parse things like
``Makefile`` or ``meson.build`` files to base your build steps on stuff *inside* the Artifact. Yes, this
is definitely possible. To do it, you will first want to define an ``Artifact`` all by itself, and then
call its ``ensure_fetched()`` or ``fetch()`` async method. You can then unpack it and inspect its contents:

.. code-block:: python

  import os
  import glob

  async def generate(hub, **pkginfo):
    my_artifact = Artifact(url="https://foo.bar.com/myfile-1.0.tar.gz")
    await my_artifact.ensure_fetched()
    my_artifact.extract()
    for meson_file in glob.iglob(os.path.join(my_artifact.extract_path, "*/meson.build"):
      ...
    my_artifact.cleanup()

See our `xorg-proto Autogen`_ for an example of this. It downloads ``xorg-proto`` and introspects inside
it to generate a bunch of stub ebuilds for each protocol supported by ``xorg-proto``.

Pre-processing the List of Packages
-----------------------------------

If you use an ``autogen.yaml`` to specify a list of packages to generate, it is now possible to use a
``preprocess_packages()`` function to arbitrarily modify the list of ``pkginfo`` dictionaries that get
fed into ``generate()`` in your generator. This allows you to prune the list of packages you want to
generate, add common metadata to the pkginfo, or do other things. It is perfectly fine to do things like
HTTP calls from ``preprocess_packages()``. An example might look like this:

.. code-block:: python

  import os
  import glob

  skip_versions = [ '1.2.3' ]

  async def preprocess_packages(hub, pkginfo_list):
    for pkginfo in pkginfo_list:
        pkginfo['foo'] = 'bar'
        if pkginfo['version'] in skip_versions:
            continue
        yield pkginfo

As you can see, the ``preprocess_packages()`` method is an async python generator, and uses the ``yield``
operator. Anything you yield will be generated using ``generate()``, while anything you don't yield will
not be generated. This gives you ultimate control over what gets fed to your ``generate()`` function --
``preprocess_packages()`` runs right before any ``generate()`` starts for your currently-running generator.

.. _Virtualbox-bin Autogen: https://code.funtoo.org/bitbucket/projects/CORE/repos/kit-fixups/browse/core-kit/curated/app-emulation/virtualbox-bin/autogen.py
.. _xorg-proto Autogen: https://code.funtoo.org/bitbucket/projects/CORE/repos/kit-fixups/browse/core-gl-kit/2.0-release/x11-base/xorg-proto/autogen.py
.. _Zoom-bin Autogen: https://code.funtoo.org/bitbucket/projects/CORE/repos/kit-fixups/browse/net-kit/curated/net-im/zoom-bin/autogen.py
.. _Discord-bin Autogen: https://code.funtoo.org/bitbucket/projects/CORE/repos/kit-fixups/browse/net-kit/curated/net-im/discord-bin/autogen.py
.. _official Jinja Documentation: https://jinja.palletsprojects.com


