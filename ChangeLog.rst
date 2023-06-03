metatools 1.3.1
===============

Released on June 3, 2023.

This is a bugfix release.

* Add a missing __init__.py to ``metatools/zmq`` so that these
  source files get included in the distribution. This fixes a
  traceback due to these missing files which prevented the 
  distributed PyPi source from working.
* If ``doit`` was interrupted, it could write incomplete JSON
  to disk using ``FileStorageBackend``. In this case, the JSON
  will be corrupt and the retrieved data will be invalid, and
  there was no obvious way to clear out this corrupt data.
  This would result in cached JSON data from ``get_page()``
  being invalid and re-running ``doit`` would not fix this.
  So a fix was added so that any corrupt entries in
  ``FileStorageBackend`` will be treated as if they don't exist
  (returning a ``CacheMiss()``) which will allow ``doit`` to
  overwite these corrupt entries with new, corrected entries.

metatools 1.3.0
===============

Released on May 29, 2023.

This is a feature release containing a number of new capabilities
and improvements.

* Refactor of how we handle the ``--immediate`` option internally to
  be more intuitive in the source code.
* Initial implementation of ZeroMQ-based "moonbeam" communications
  framework to allow child ``doit`` processes to communicate with
  the master ``merge-kits`` process. This will initially be used to
  implement logging of all issues encountered during the ``merge-kits``
  run so we can generate a nice summary of problems (see FL-11179).
  The initial framework has just been added but the logging/reporting
  functionality is not yet implemented.
* When running ``ensure_fetched()``, use an ``asyncio.wait(0)`` to allow
  scheduling/execution of new asyncio tasks. This method often gets
  hammered with hundreds of new requests and this can stall out
  existing async tasks (like when a bunch of crates or go modules
  are getting queued for download all at once.)
* In doit and merge-kits, a large conversion from more thread-oriented
  to single-process async (with forked subprocesses for external
  commands) whenever possible, keeping threads only for CPU
  parallelization for Portage metadata generation. This allows
  "moonbeam" to be able to send/receive messages efficiently when
  other stuff is going on.
* Python 3.7 compatibility restored to the codebase (I made a minor
  change which made the code 3.9+.)
* Add ``--howdy`` argument for merge-kits which causes "HOWDY" to be
  printed every 0.1 seconds from the moonbeam ZeroMQ engine. This is
  used to test for any issues related to async tasks not being
  scheduled to run frequently. If you don't see HOWDY printed
  continuously then some long-running task is blocking the async
  event loop and this should probably be fixed.
* Fix a 3-year-old bug where the Python USE-optimization code was not
  generating deterministic results in package.use files.
* Misc fixes to pyhelper to introduce sorting in some areas to reduce
  randomization (non-deterministic order) of elements in ebuilds.
* Reimplementation of ``deepdive``. Add an advanced ``deepquery`` that can
  actually rewrite packages.yaml files for us to remove unused ebuilds
  automatically. This is an active area of work and needs some docs
  and cleanup.
* When specifying assets: for github-1 to grab, add a special keyword
  ``"<source.tar.gz>"`` literal string which allows you to grab the
  auto-generated default tarball. There was not previously a way to
  grab this as well as other assets that were uploaded to a release.
* Support ETag and Last-Modified HTTP 304 responses. This dramatically
  improves API limits for GitHub, etc.
* FL-11369: tweak to ``rust.py`` to background and make the cargo update
  async-compatible.
* Deprecate max_age= parameter for fetching (this was a vestigial thing
  that was not being used.)
* As part of the work on HTTP 304 support, ``spider.http_fetch`` now returns
  a tuple of headers and content. This is necessary so we can extract
  "Last-Modified" and "ETag" headers and store them in the fetch
  cache so we can use them for successive requests for the HTTP
  304 support.
* Fix an issue with ``doit`` that is common to all Python programs --
  All python programs will attempt to import things from
  the current working directory if some directory exists
  with the same name as a module it needs. This is really,
  really dumb.
  This caused ``doit`` to fail in python-modules-kit, inside
  ``curated/dev-python``, due to the "click" directory existing
  after first ``doit`` is run, which then caused successive
  ``doit``s to fail when ``httpx`` tries to import the ``click``
  module.
* Cleaned up some error output issues.
* FL-11300: attempt to address Tree OOP hierarchy to ensure
  initialize is available for AutoCreatedGitTree class. (Thanks:
  borisp)

metatools 1.2.1
===============

Released May 1, 2023.

This is a bugfix release that fixes some critical git tree
initialization issues that in some circumstances would result
in the wrong source branch's ebuilds being copied into kits.
See FL-11276. (Thanks: overkill, siris)

metatools-1.2.0
===============

Released April 28, 2023.

This is a feature release containing a number of new capabilities
and improvements.

* Implement dynamic archives API improvements. (FL-10403)
* Add ``{{src_uri}}`` jinja variable to easily output correct
  ``SRC_URI`` in ebuild templates in nearly all cases.
* Fix compatibility with httpx-0.23+ (FL-9888)
* Fetch go dependencies in parallel (FL-11168: thanks: invakid404)
* Fetch rust dependencies in parallel (FL-10404: thanks: invakid404)
* HTTP/2 support with support for re-using existing TCP connections.
* Improved "rich" progress bars (using external module)
* Production-tested tuning to avoid saturating upstream Web
  sites/endpoints.
* Spider will auto-start.
* Removal of threads (``ThreadPoolExecutor``) from main autogen loop. We are
  now purely async.
* Improved repo initialization, to avoid redundant git repo inits which
  is IO intensive and slows merge-kits down.
* Improved reliability of reading redirects.
* 15-minute ``get_page()`` caching by default was broken. It is now fixed.
* Archive verification support. Common file types such as .tar.gz,
  .tar.bz2, .tar.xz, .gz, .bz2, .xz will be checked for integrity. A
  background process will be spawned to extract the data to /dev/null
  and an exception will be thrown if the archive is corrupt. This
  prevents archives from being used or stored that are invalid.
* Addition of a bin/fetch command which can be used to troubleshoot
  fetching problems. It calls ``get_page()`` for all URLs specified on the
  command-line, using the spider. It will throw away the content of
  the page. Just allows you to see if the fetch works. (Like ``wget`` but
  uses our code paths and modules.)
* Removal of erroneous "portage import" (caused by PyCharm adding the
  wrong reference and me clicking on "portage"
* When a ``get_page()`` fails, we will attempt to print the JSON body if
  it's available. This body often contains error details.
* Fix major bug in ``http_fetch_stream()`` (which is used for grabbing
  Artifacts) retrying code, which caused an aborted download that was
  restarted to append the contents of the new download at the end of
  the aborted file. This now works properly.
* Fix ``bin/merge-gentoo-staging`` (FL-10850: thanks: borisp)
* Minor fix to .zst archive handling for dynamic archives.
* Rework of error handling, fixes related to aggregating errors (FL-10556)
* Add GitHub tag pagination using async generators (thanks: invakid404)
* Allow ``create_branches=True`` with a GitTree to create missing branches
  even in prod mode.
