This document is designed to help me update the design of how meta-repo is defined using
YAML (and potentially other mechanisms.)

Right now, meta-repo is defined using:

 * foundations.yaml, in kit-fixups
 * packages.yaml (for each kit), in kit-fixups
 * kit-fixups forked ebuilds and autogens themselves
 * In addition, independent kits can be part of what makes up the assembled meta-repo.

For my revision, I plan to:

Indy Kits
---------

Drop independent kits since they are incapable of autogen, and are also not useful at
being shared between releases. Instead, they can be moved to 'source kits' and the
'transport kits' can be autogenned versions of these kits.

To drop independent kits, I would also need/want to add a feature to packages.yaml so
that I can say "grab all the things from this source repository." So this creates the
need for defining a new packages.yaml format. Maybe rename this to kit.yaml? THIS CAN
BE DONE BY CREATING A DIRECT MAPPING BETWEEN steps.py FUNCTIONS AND YAML in packages.yaml.

There is also a need for 'collections' of packages to be defined in packages.yaml.
This file (in theory) is supposed to define what stuff gets copied into a kit from
various sources. But its purpose is evolving. It should now also allow functionality
to be defined to group kits into logical collections that should be maintained as
a whole. Think of this as a way to group packages in a kit that are related, but for
which we don't want to create a separate kit. Most likely, these packages will all
come from the same source repo, but it's also possible that they won't.

Moreover, we may want to list auto-generated or forked ebuilds in packages.yaml,
so we can reference them in collections and thus have these collections be complete,
documenting all packages that are related, even if we don't explicitly need to copy
them from some other source repo. And while it may be tempting to *require* all
autogenned packages to be listed in packages.yaml, to make it an authoritative
source for all packages in the kit, it is also very possible for autogens to
*dynamically create* packages and determine the names of these packages dynamically,
so this makes that not a good idea.

Foundations Improvements
------------------------

Beyond removal of support for indy kits,
we also need to make improvements to foundations.yaml, which defines each release,
and what source repositories are used for each kit in a release.

Foundations.yaml needs a capability of defining 'special kits' like
core-kit that must be generated first. So we need much more control over pipelines.
This is needed for llvm-kit. We also need to hook these magic kits into the hierarchy
for eclass resolution and not assume all eclasses are coming from core-kit. For this
we may want to think of these magic kits as core kit*s* -- plural, and designed to
work together. Exposing more repo settings such as repo stacking order into the
foundations.yaml is probably the way to go here. We can then think of kits in a
tree rather than linear list.

It would also be nice just to 'clean up' foundations.yaml, and have more consistent
conventions about how a release maps to kit names, maybe. At least with the removal
of indy kits this might be possible.

I could also see it being very useful to have one YAML file per release, since really
these should be maintained separately, and there is essentially no overlap, and if
there is, this can be handled with a copy/paste.

Python API
----------

Finally, while we have various functions for reading in this YAML, we lack a coherent
OOP model and API for accessing the data cleanly. This results in a lot of implementation-
specific loops in the metatools code for getting all this data and acting upon it. Ideally,
we should have some nice models for this that are leveraged and provide some abstraction
away from the raw YAML file formats. This should be fun to do.

Brainstorm -- Mirroring?
------------------------

Does it make sense to also define the mirror destination in foundations.yaml for meta-repo
and each kit? And then have this get integrated into meta-repo so that this stuff isn't
hard-coded? I think this makes a lot of sense, and will make it well-suited for other
projects to use. So some more thought needs to happen here as well.
