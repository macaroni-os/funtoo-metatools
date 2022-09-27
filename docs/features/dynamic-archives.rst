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
also includes a diagram of the technical implementation of this feature. The initial
implementation has been improved as part of discussion/evaluation in FL-10403.

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

Autogen Workflow Overview
-------------------------

The dynamic archive API has been designed to allow several possible workflows, depending
on scenario.

The basic workflow that all autogens should follow is to first search for
the desired dynamic archive to see if it was created on a previous autogen run, and
then optionally perform additional processing/introspection to see if it wants to use
this previously-created archive.

If the dynamic archive is found and seems acceptable, the autogen should use it as-is. If
not, it should create a new dynamic archive, store it using this API, and use it for ebuild
creation. It will then be available for future autogen runs to retrieve.

Storage and Retrieval
---------------------

There are two supported mechanisms for storing and retrieving archives -- retrieval
by *filename* (optionally with an associated *key*), and retrieval purely by *key*.

Rather than go into the details right away, let's look at how to store and retrieve
dynamic archives by *filename*. You can use this approach if your autogen workflow
allows you to *know the name of the archive you want to use in advance.*

How To Use Retrieval By Filename
--------------------------------

Let's go through a gradual process to get familiar using retrieval by filename.

To create a new archive, you will specify a ``final_name``, which is the name of the
archive on disk. This is done as follows:

.. code-block:: python

   my_archive = hub.Archive("foobar-go-modules-1.2.3.tar.xz")

Once the ``Archive`` has been created, files can be added to it, and then it can be stored.
When storing the archive, a dictionary key containing arbitrary values can optionally be
supplied, as follows:

.. code-block:: python

   master_gosum = "abcdef0123456789"
   my_archive.store_by_name(key={"gosum": master_gosum})

This is not complete code, as if you just create an ``Archive`` and store it, you will
have an archive with nothing in it. We're just getting familiar with the basic constructor
and ``store_by_name()`` method right now. You will notice the use of a ``key``.

This key is optional and is used to uniquely identify the archive and can be used to
differentiate it from previously-created archives that might otherwise seem identical due
to having the same name. This means the key is used at *retrieval time* to further
specify a distinct archive, and if the key doesn't match what was stored, no archive
will be found.(Internally, the dynamic archive implementation
uses cryptographic digests to differentiate between otherwise-identical archives.)

Now that we have looked at these two methods, let's look at a full run of how you should
use an ``Archive`` in your code to store and retrieve by filename. The basic workflow is to:

1. Try to retrieve an existing ``Archive`` that might have been created in a previous
   autogen run that has a matching name (and any optional ``key``
   data matching.)
2. If found, you will simply using this retrieved previously-created archive and pass
   it your ``BreezyBuild`` ``artifacts=`` keyword argument and use it like a regular
   ``Artifact``.
3. If *not* found, then you will have code *create* the ``Archive`` in real-time, and
   call the ``.store_by_name()`` method to store it. You will then use this newly-created archive
   by passing it to your ``BreezyBuild`` ``artifacts=`` keyword argument.

Here is a snippet of code that uses an ``Archive`` properly:

.. code-block:: python

   master_gosum = "abcdef0123456789"
   my_archive, metadata = hub.Archive.find_by_name("foobar-go-modules-1.2.3.tar.xz", key={"gosum" : master_gosum}))
   if my_archive is None:
       my_archive = hub.Archive("foobar-go-modules-1.2.3.tar.xz")
       my_archive.initialize("dynamic-archive-1.0")
       with open(os.path.join(my_archive.top_path, "README"), "w") as myf:
           myf.write("HELLO")
       my_archive.store_by_name(key={"gosum": master_gosum})

Please also note the ``.initialize()`` method. This creates a new temporary on-disk location
for the archive that you can copy files into. It has an optional argument which you should generally
specify, which is the ``top_directory`` that will exist when the archive is extracted -- it's
best practice to create archives where all your files are themselves within a directory so that
others extracting your archive get a directory created for them.

Then you will see use of the ``.top_path`` property, which will give you the path *inside*
the top directory of your archive, and within ``.top_path`` is where you should create files. In
our case, this is where we create a ``README`` file that will become a part of our archive.

Finally, we ``.store_by_name`` our new ``Archive``, using an optional unique key we want to associate with our
archive, which could be some kind of master gosum or a GitHub commit hash which *must* match
for the ``Archive`` to be returned. Then, we use our
``Archive`` just like an ``Artifact``, and voila -- we have the ability to create tarballs
from autogens!

How To Use Retrieval By Key
---------------------------

There may be autogen workflows where you do not know the exact name of the Archive in
advance, but want to retrieve the archive based on other criteria you *do* know -- don't
worry, we have a method for that too! This approach is more advanced, but you will see
that the code is very similar.

Using a pure key allows unlimited flexibility and
adaptability to pretty much any possible autogen workflow. Here's an example where we
can retrieve an Archive just by knowing the unique key it was stored under:

.. code-block:: python

   master_gosum = "abcdef0123456789"
   key={"catpkg": catpkg, "gosum" : master_gosum}
   my_archive, metadata = hub.Archive.find(key=key))
   if my_archive is None:
       my_archive = hub.Archive(f"foobar-go-modules-{version}.tar.xz")
       my_archive.initialize(f"dynamic-archive-{version}")
       with open(os.path.join(my_archive.top_path, "README"), "w") as myf:
           myf.write("HELLO")
       my_archive.store(key=key)

    # At this point in your code, your my_archive exists, whether it was created in this
    # run or retrieved from the local object store as it was created in a previous run.

    my_eb = hub.pkgtools.ebuild.BreezyBuild(**pkginfo, artifacts=[my_archive])

Above, we store the ``Archive``, indexed exclusively by the catpkg of the ebuild, and
the master gosum. This means we don't need to know the exact filename used to store the
``Archive``. However, if the ``Archive`` can be retrieved, it will be populated with the
name that it had when it was created.

Why is this useful? There are several scenarios:

Maybe we have several ebuilds that share a dynamic archive. It may be easier to store by
an agreed-upon key rather than specific filename.

Maybe our autogen doesn't care about the version of the dynamic archive it is using -- it
simply wants to use the "latest" archive. This allows easy retrieval in this case.

Maybe our autogen wants to avoid using a version in the archive name altogether, and
instead use some kind of arbitrary hash. This is also now possible.

Maybe our autogen wants to retrieve an Archive, but do additional investigation to see if
the archive can still be used. Maybe, if it needs replacement, the autogen will want to
increment the version number or revision of the archive itself, so "extras-1.0.0.tar.xz"
becomes "extras-1.0.1.tar.gz", etc. This is now possible!

Using Metadata
--------------

You will notice that our calls to ``Archive.find()`` and ``Archive.find_by_name()`` return
a ``metadata`` value:

.. code-block:: python

   my_archive, metadata = hub.Archive.find_by_name("foobar-go-modules-1.2.3.tar.xz", key={"gosum" : master_gosum}))

What is metadata, and what is it useful for? Well, the metadata can store things just like
the key, but it is not used to match when retrieving the object. So you can always store additional
information in the metadata as follows, if you do not want it used to find the archive, but might
have use for this data later in processing. Both ``archive.store()`` and ``archive.store_by_name()``
accept an optional metadata dictionary:

.. code-block:: python

    my_archive.store(key=key, metadata={ "author" : "drobbins was here!" })

You can use this metadata to perform further processing to determine if the archive you retrieved
is truly acceptable to your autogen. You could also store a version counter or build number here
if you wanted to dynamically increment it.

Bonus feature of metadata: your ``metadata`` will always contain a ``created_on`` timestamp containing the UTC
time of when the archive was created by the autogen process.

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

What can I store in the ``metadata=`` keyword argument?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Same as ``key=``. See above.

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

