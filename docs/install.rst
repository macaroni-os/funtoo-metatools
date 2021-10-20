
Installation
============

These instructions asssume you are using Funtoo Linux but should be easy to adapt
to other distributions.

Installing Latest Official Release
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. warning::
   This is not currently working -- but you can use ``emerge --onlydeps metatools`` to set up
   dependencies, and then proceed to follow the steps in :ref:`Installing Latest Development Sources`.

Funtoo-metatools is easy to install. On Funtoo, it can simply be emerged:

.. console::
  # emerge metatools

Recent version of metatools also require MongoDB to be installed and running locally. MongoDB is used by the ``doit``
command to store distfile integrity hashes, as well as for maintaining a cache of HTTP API requests for more resilience
related to network interruption. It is also used by ``deepdive`` to provide package analytics functionality.

MongoDB can be installed and started on Funtoo Linux as follows:

.. console::
  # emerge mongodb
  # rc-update add mongodb default && rc

Alternatively you can use ``pip3`` to pull it from PyPi:

.. console::
  $ pip3 install --user funtoo-metatools

If you would like to create an isolated virtual environment for funtoo-metatools,
you can use virtualenv as follows:

.. console::
  $ emerge virtualenv
  $ virtualenv -p python3 venv
  $ source venv/bin/activate
  $%venv% pip install funtoo-metatools

From this point forward, whenever you want to use the virtualenv, simply
source the activate script to enter your isolated python virtual environment.

Installing Latest Development Sources
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you need the absolute latest features, you may want or need to install ``metatools``
from git master. To do this, you will want to clone the repository locally:

.. console::
  # cd ~/development
  # git clone ssh://git@code.funtoo.org:7999/~drobbins/funtoo-metatools.git
  # git clone ssh://git@code.funtoo.org:7999/~drobbins/subpop.git

Next, you will want to add something similar to the following to you shell init script,
such as your ``./.bashrc`` file::

  export PATH=$HOME/development/funtoo-metatools/bin:$PATH
  export PYTHONPATH=$HOME/development/subpop:$HOME/development/funtoo-metatools

When these settings are active, your current shell will be able to find the binaries
such as ``doit`` as well as the python modules in the live git repository.

Finally, you will want to ensure that all dependent modules are installed. On Funtoo,
this can be accomplished via ``emerge --onlydeps metatools``.

