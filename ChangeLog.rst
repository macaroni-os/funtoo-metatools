metatools 1.3.5
===============

Released on November 9, 2023.

This is a general update including features and bug
fixes.

* Support for restarting of aborted downloads using HTTP
  206 Range requests, which can happen over bad networks
  or with upstream unreliable network.

* ``doit`` now has a ``--release`` option to specify the
  release it is doing autogens for. ``merge-kits`` will
  call ``doit`` with the proper release setting. There
  is also new support that allows our generators to be
  release-aware, and this was enable in our pypi 
  generators, for the following feature related to
  filtering.

* Add support for ``pypi-*`` generators to filter 
  upstream packages based on the versions of Python
  supported in the actual release. This prevents 
  unsupported versions of packages from entering Funtoo.
  If no match is found, an error is thrown.

* ``SRC_URI`` improvements:

  Allow the following format for ``src_uri`` in
  ``autogen.yaml``::

    src_uri:
      foo:
        - https://foo.bar.com
        - https://foo.bar.oni
      global:
        - https://bar.foo.com

  The ``simple-1`` generator supports this format to organize
  manually-defined artifact URLs in the YAML itself, and
  utilizes the Jinja variable ``{{src_uri_with_use}}`` to
  expand these to conditional USE artifacts, with ``global``
  being a non-conditional section. If you use ``{{src_uri}}``
  in a template, this list will be expanded without any 
  conditional USE. The ``src_uri`` in the YAML can be a
  string, a list (no conditional sections) or a nested
  object as above, and it should all work.

* Improvement to ``github.py`` ``release_gen()`` function
  to fetch desired tag directly by ref (thanks ``invakid404``)

* Fix ``zip`` artifact extraction.

* More HTTP 304 fixes to try to finally squash this issue.

* Additional debugging for 304 errors as well as improvements
  in error verbosity in some areas.

* Massive cleanup of output when there are fetch errors, by
  removing a duplicate traceback.

* Add a feature requested by ``siris`` in ``FL-10055``:
  when a ``git pull`` fails on a repo, prompt the user and
  ask them if they want to force pull.

* Complete ``distfile-kit-fetch`` which is a tool to fetch
  all non-autogenned distfiles (``SRC_URI`` referenced in
  non-autogenned ebuilds) in a kit. Use as follows::

    distfile-kit-fetch <release> <kit-name>

  It will then proceed to attempt to fetch all distfiles in
  the kit that are referenced in ebuilds but not already in
  metatools' object store.

  This is used to populate the CDN with distfiles from
  static ebuilds.

* Be more robust when handling JSONDecodeErrors from upstream JSON.
  Previously, we would traceback. Sourceforge in maintenance mode
  will return a regular non-404 404 page that is NOT JSON. In this
  case, it would nice to fall back to our cached version of the
  page.

metatools 1.3.4
===============

Released on July 28, 2023.

This is a maintenance/general update release.

* A hopefully (and I believe) "final fix" for HTTP 304
  responses not being properly handled. For some reason,
  I was not reading this code correctly and it should
  now be totally fixed.

* Adding of a ``ROADMAP.rst`` to remind me of things to
  work on.

* Catch ``ssl.SSLError`` as it appears httpx doesn't
  catch this exception, so we must catch it and handle
  it. This fixes an issue where invalid/expired SSL
  certs would cause a traceback rather than a "fallback"
  behavior.

* FL-11447: merge invakid404's improvements to support
  git-sourced rust crates.

metatools 1.3.3
===============

Released on July 13, 2023.

This is a maintenance/general update release.

* Fix an bug for where we could receive an HTTP 304 response
  and not call the proper handling code later, causing a
  traceback.

* IMPORTANT breaking API change for dynamic archives:
  myarchive.initialize() is now async and needs to be awaited.
  This now uses a higher-performance async function (see
  below for more info.)

* Hub now has a higher-performance hub.cmd.run_bg() function which
  can be used to run a command in the background and get its
  exit code as a return value, without pausing the metatools
  event loop. This should be used instead of ``os.system()``
  in your autogens.

* Hub now has a hub.cmd.capture_bg() command which is similar to
  hub.cmd.run_bg() except that it don't emit any output, but
  instead captures stdout and err into a combined string.
  It returns a tuple containing the process object (which can
  be inspected for error code, etc.) and the combined string of
  stdout and stderr.

* For dynamic archives: ``Archive`` now has a ``work_path`` and
  an async ``create_work_path`` method. This can be used as a
  'scratch area' for temporary work. Do an::

    await myarchive.create_work_path()

  ``myarchive.work_path`` is now empty and ready for use.

  ``Archive`` ``.store()`` and ``.store_by_name()`` now accept
  an ``existing=`` keyword argument which can be used to point
  to an archive/file that already exists. This will allow you
  to basically say "THIS is the archive I wish to store -- I
  have it already". Without using ``existing=``, the default
  behavior is to tar up the contents of the archive's
  ``temp_archive_dir`` to create the archive dynamically.

* Convert golang and rust dynamic archive code to use async.

metatools 1.3.2
===============

Released on June 29, 2023.

This is a maintenance/general update release.

* FL-11382: For ``Artifact``, throw exceptions when ``fetch()``,
  ``ensure_fetched()``, ``ensure_completed()`` fail. If ``throw=False``
  specified for ``ensure_fetched()`` then this behavior is disabled and
  ``None`` is returned on fetch failure.
* Add additional debugging for ``http_fetch`` if we get a 304 response
  and are not expecting it. In this case, log detailed header information
  so we can troubleshoot it. This may be an infrequently-occurring bug
  that still needs to be fixed. We should only get a 304 if we specify
  ``If-None-Match`` or ``If-Modified-Since``.
* Small fix to allow Funtoo to only have one Python implementation as
  up until now it has had two (2.7 and 3.7 in 1.4-release, and 3.7
  and 3.9 in next-release. We are now moving to just 3.9 in next.)
* Add a ``blos-check`` tool to scan the Integrity Database (this is the
  thing that maps a distfile name to a specific binary object in the
  Base Layer Object Store, or BLOS) to look for any missing binary
  objects. This is not really needed but sometimes when I am debugging
  our stores, I need to run this for due diligence. It hasn't found
  any issues yet.
* Add ``distfile-kit-fetch`` tool which you would run on the system
  you ran ``merge-kits`` on. It will try to grab all the non-autogenned
  distfiles and download all it can, ultra-fast-spider style, and store
  them locally in the BLOS. It is used like this:
  ``distfile-kit-fetch <release> <kit> <branch-of-kit>``
  It will use the kit-cache data from a previous ``merge-kits`` run.
  This kit-cache data is stored in ``~/repo_tmp/tmp/kit_cache``.
  This tool also will make sure it has a locally-checked out
  ``kit-fixups`` repo in ``~/repo_tmp/source-trees/kit-fixups`` and
  will utilize the ``thirdpartymirrors`` file located at
  ``core-kit/curated/profiles/thirdpartymirrors`` to expand any
  ``mirror://`` prefixes in ebuild ``SRC_URI`` strings. Additional
  work has been done on this tool to make it production-quality. For
  example, it won't stop running when it encounters a file download
  that errors out -- instead it will be greedy and try to keep
  downloading as many distfiles as it can.
* Support for archive verification of ``.tar`` files (no compression,
  and we do see these sometimes.)
* Add missing ``await`` for initializing ``kit-fixups`` repo in
  ``AutogenConfig`` initialization which should fix a potential
  race condition.


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
  overwrite these corrupt entries with new, corrected entries.


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
