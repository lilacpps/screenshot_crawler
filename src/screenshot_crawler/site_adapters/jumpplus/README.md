# Shonen Jump+ adapter

The Discovery adapter enumerates the series episode list across the observed
range controls and bounded "more" expansion. The canonical order is
newest-first; complete listings carry contiguous site positions independent of
episode labels, including special episodes.

The adapter provides a read-only complete-listing preview for the Watchlist
editor. An exclusion preview binds one validated listing to the next Discovery
run for up to 30 seconds and is consumed once. Unknown exclusions, boundaries
outside the listing, and reversed boundaries fail closed before the first
record is yielded. Preview and replay do not write Catalog state.
Complete/bounded traversal additionally requires numeric range intervals to be
contiguous and native episode identities to be disjoint across ranges; gaps,
overlaps, and union-count mismatches fail before yielding.
Range numbers refer to listing slots, so their row counts must match but their
numbers need not equal the chapter numbers in titles. Title-number offsets,
special episodes and split chapters do not imply an incomplete listing.
The Exorcist listing was live-checked read-only on 2026-10-28: range `129 - 80`
held 50 unique rows titled 128..79. After correcting that unsupported equality
check, the GUI's listing service returned a ready, complete 129-row preview.

Read-only live verification on episode
`13932016480029260549` observed series identity `13932016480029260546` and 44
rows after one bounded list expansion, from chapter 43 through the prologue.
The production `preview_complete_listing` returned `ready=true`,
`listing_identity=jumpplus-series:13932016480029260546`, and digest
`c5086065894d2f7bb8b6994182e7c4784af38793020ae009b232cb05c467747d`.
No viewer or Catalog/Watchlist write was performed; future listing stability is
unverified.
