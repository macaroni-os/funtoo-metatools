Dynamic Archives
~~~~~~~~~~~~~~~~

This document describes a new feature of metatools, which allows creation of "dynamic
archives". Basically, this means that autogens can create their own artifacts locally,
which will appear on Funtoo's CDN automatically. This is very useful if you need to
create a bundle of patches or Go modules for distribution with your ebuild. You don't
need to take manual steps to upload your special archive anywhere to get your ebuild to
work -- instead, your autogen can simply create it. It's magic.

How It Works
------------

The development of this feature was tracked in Funtoo Linux issue FL-9270, and this issue
also includes a diagram of the technical implementation of this feature.

A stand-alone Python autogen can now create an ``Archive``, which is now a base class
for ``Artifact``. This archive is created locally, on a developer's system, by the autogen
itself. When a PR is submitted with a new autogen, it is added to the official Funtoo tree,
and then the autogen will also create this dynamic archive on the official tree regen system.
The dynamic archive created during official tree regen will end up on the CDN automatically.
Thus, a Funtoo developer has a way for an autogen to create an archive which it in turn can
download from our CDN.

The thing to understand about the ``Archive`` is that from an ebuild perspective, it's
identical to an ``Artifact``. This means you will still pass it to the ``artifacts=``
keyword argument of your ``BreezyBuild``. This is actually required, as just like an
``Artifact``, an ``Archive`` is a file downloaded by ``ebuild``/``emerge`` and thus it
will need to have a ``Manifest`` entry generated for it. Therefore, it will need to be
in ``artifacts=`` and referenced in ``SRC_URI`` in the ebuild template itself.

How To Use
----------

Let's go through a gradual process to get familiar with how to use the ``Archive``:

To create a new archive, you will specify a ``final_name``, which is the name of the
archive on disk. This is done as follows:

.. code-block:: python

   my_archive = hub.Archive("foobar-go-modules-1.2.3.tar.xz")

Once the ``Archive`` has been created, files can be added to it, and then it can be stored.
When storing the archive, a dictionary key containing arbitrary values can optionally be
supplied, as follows:

.. code-block:: python

   master_gosum = "abcdef0123456789"
   my_archive.store(key={"gosum": master_gosum})

This is not complete code, as if you just create an ``Archive`` and store it, you will
have an archive with nothing in it. We're just getting familiar with the basic constructor
and ``store()`` method right now. You will notice the use of a ``key``.

This key is optional and is used to uniquely identify the archive and can be used to
differentiate it from previously-created archives that might otherwise seem identical due
to having the same name. So this key is a very powerful tool to ensure your autogen is
getting a correct and up-to-date archive, and you are encouraged to use it to include any
unique values that are associated with the particular archive being created.

Now that we have looked at these two methods, let's look at a full run of how you should
use an ``Archive`` in your code. The basic workflow is to:

1. Try to retrieve an existing ``Archive`` that might have been created in a previous
   autogen run that meets your criteria (i.e. ``final_name`` and any optional ``key``
   data matching.)
2. If found, you will simply using this retrieved previously-created archive and pass
   it your ``BreezyBuild`` ``artifacts=`` keyword argument and use it like a regular
   ``Artifact``.
3. If *not* found, then you will have code *create* the ``Archive`` in real-time, and
   call the ``.store()`` method to store it. You will then use this newly-created archive
   by passing it to your ``BreezyBuild`` ``artifacts=`` keyword argument.

Here is a snippet of code that uses an ``Archive`` properly:

.. code-block:: python

   master_gosum = "abcdef0123456789"
   my_archive = hub.Archive.find("foobar-go-modules-1.2.3.tar.xz", key={"gosum" : master_gosum})
   if my_archive is None:
       my_archive = hub.Archive("foobar-go-modules-1.2.3.tar.xz")
       my_archive.initialize("dynamic-archive-1.0")
       with open(os.path.join(my_archive.top_path, "README"), "w") as myf:
           myf.write("HELLO")
       my_archive.store(key={"gosum": master_gosum})

    # At this point in your code, your my_archive exists, whether it was created in this
    # run or retrieved from the local object store as it was created in a previous run.

    my_eb = hub.pkgtools.ebuild.BreezyBuild(**pkginfo, artifacts=[my_archive])

Some things to note here -- when looking for an existing archive, the final name is
specified, as well as the exact key that was used to store the archive. This key must match
exactly for the archive to be retrieved. For clarity it is often helpful to put a part of
the key in the filename to avoid confusion for users as well as Portage if multiple variants
of the same filename may be downloaded to ``/var/cache/portage/distfiles``. Here's an example
of how one might do that:

.. code-block:: python

   my_archive = hub.Archive.find(f"foobar-go-modules-1.2.3-{master_gosum[:7]}.tar.xz", key={"gosum" : master_gosum})

Please also note the ``.initialize()`` method. This creates a new temporary on-disk location
for the archive that you can copy files into. It has an optional argument which you should generally
specify, which is the ``top_directory`` that will exist when the archive is extracted -- it's
best practice to create archives where all your files are themselves within a directory so that
others extracting your archive get a directory created for them.

Then you will see use of the ``.top_path`` property, which will give you the path *inside*
the top directory of your archive, and within ``.top_path`` is where you should create files. In
our case, this is where we create a ``README`` file that will become a part of our archive.

Finally, we ``.store`` our new ``Archive``, using the unique key we want to associate with our
archive, which could be some kind of master gosum or a GitHub commit hash. Then, we use our
``Archive`` just like an ``Artifact``, and voila -- we have the ability to create tarballs
from autogens!

Q&A
---

What archive formats are supported?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Currently, ".tar.xz" and ".tar.zstd" format archives are supported, and the compression format is
specified by the filename of your archive.

What can I store in the ``key=`` keyword argument?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``key=`` must be a dictionary, but it can contain a lot of things, including booleans, strings, integers,
floating-point, DateTime, lists and other dictionaries. So you can organize the data within ``key=`` so
that it makes sense for your needs and it's definitely possible to create nested and more
complex structures that contain different kinds of data. For a complete list of supported object types,
see https://pymongo.readthedocs.io/en/stable/api/bson/index.html for a list of objects that are listed
as "both" for "Supported direction"

How does my archive end up on the CDN?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When your autogen is run during official tree regeneration, it will create a dynamic archive which
gets automatically populated to our CDN. In addition, any ebuild(s) autogenerated during this tree
regeneration will specifically reference this archive.

Where is the archive stored locally when I run ``doit``?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The archive itself is stored in ~/repo_tmp/stores/blos, but it is indexed by hash so it is not
trivial to find the archive by filename. An entry in ~/repo_tmp/stores/dynamic is created to
reference this dynamic file by the final_name and key.

If the archive is stored in a weird place, how does my locally-autogenned ebuild actually find it?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If your user is in the ``portage`` group, dynamic archives will be copied to ``/var/cache/portage/distfiles``
when generated, so the you can easily validate your autogenned ebuild and the archives will be found
by Portage, even though they are not on the CDN yet. This convenience feature will be disabled when
metatools is doing a production tree regeneration.

Anything special to be aware of for autogen developers?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The hashes of the final file that ends up on our CDN and referenced by the official ebuild is not
guaranteed to be "binary identical" to the one generated by your autogen locally. Therefore, if you
are working on a dynamic-file ebuild, it's possible that the one that ``doit`` copied to
``/var/cache/portage/distfiles`` could be different than the official one on our CDN, and might
require a manual cleaning of the locally-generated archive to avoid a bad digest. If you see a
bad digest in this situation, be sure to see if you created a dynamic archive locally that may be
conflicting with our "official" version.

Is there a way to force ``doit`` to regenerate dynamic archives?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Yes! I just added this for convenience. ``doit --force_dynamic`` will force the recreation of
dynamic archives, which is very useful for testing autogens locally if you have made code changes.
It works by forcing the ``Archive.find()`` method to return ``None``, so that no existing files
will be found, and thus your archive creation code is guaranteed to run.

Why do we use ``hub.Archive`` instead of ``hub.pkgtools.ebuild.Archive``, like with ``Artifact``?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

An upcoming release of metatools will map commonly-used classes to the root of the hub, so
``hub.Archive`` is being used to anticipate this upcoming change, so people start to use archives
"the right way".

