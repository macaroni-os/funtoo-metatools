*******
Roadmap
*******

Items to be added soon:

1. FL-11179: Enhanced Reporting
2. Once #1 is complete, add Reports for unfetchable URLs, etc.
3. Release-specific versioning and other YAML metadata, so you
   don't have to copy YAML to different directories if only 
   something such as version is different. This can be done via
   dict merging "release: next: " keys on top of existing keys.
4. Enhanced pipelines that allow stacking.
5. Frozen trees, or semi-frozen trees. I have thought about this
   and I think maybe the best way to handle this is -- have some
   releases/ YAML option to completely freeze a tree, so it no
   longer receives updates. Additionally, have a new way to say
   "this tree is mostly frozen". In this state, we will autogenerate
   a new kit to a temp dir, but we will only sync over the specified
   directory globs onto the actual to-be-updated tree before doing
   our final metadata-generation steps.
   This will allow things like firefox-bin and other desktop apps
   to be "allowed updates" while other things don't get updated.
   Maybe we also mark what directories to actually run autogens in.
   By default, we could include any to-be-copied directories, but
   since autogens don't map 1:1 to directories, we could for example
   say run autogens in "dev-util/jetbrains" -- and then grab all
   resultant catpkgs? It would be cool if doit would be aware of
   what catpkgs were created so we can simply get this result and
   sync these dirs.
