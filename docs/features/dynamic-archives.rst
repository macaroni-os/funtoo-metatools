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

Before understanding this feature, you will need to understand basic stand-alone Python
autogens.

A stand-alone Python autogen can now create an ``Archive``, which is now a base class
for ``Artifact``. This is used by specifying a ``final_name``, which is the name of the
archive on disk. This is done as follows:

.. code-block:: python

   my_archive = Archive("foobar-go-modules-1.2.3.tar.xz")

Once the ``Archive`` has been created, files can be added to it, and then it can be stored.
When storing the archive, a dictionary key containing arbitrary values can be supplied,
as follows:

.. code-block:: python

   master_gosum = "abcdef0123456789"
   my_archive.store(key={"gosum": master_gosum})

Rather than recreating archives on each autogen run, autogens should check to see if the
desired archive already exists. So typically, an autogen will *query* for the existence
of an ``Archive`` first:

.. code-block:: python

   master_gosum = "abcdef0123456789"
   my_archive = Archive.find("foobar-go-modules-1.2.3.tar.xz", key={"gosum" : master_gosum})
   if my_archive is None:
       my_archive = Archive("foobar-go-modules-1.2.3.tar.xz")
       # add files here
          my_archive.store(key={"gosum": master_gosum})

Some things to note here -- when looking for an existing archive, the final name is
specified, as well as the exact key that was used to store the archive. This key must match
exactly for the archive to be retrieved. Also note that there is no hard requirement for
there to be only one definitive version of a specific archive final name (filename),
although for clarity it is often helpful to put a part of the key in the filename to
avoid confusion for users as well as Portage if multiple variants of the same filename
may be downloaded to ``/var/cache/portage/distfiles``. Here's an example of how one might
do that:

.. code-block:: python

   my_archive = Archive.find(f"foobar-go-modules-1.2.3-{master_gosum[:7]}.tar.xz", key={"gosum" : master_gosum})
