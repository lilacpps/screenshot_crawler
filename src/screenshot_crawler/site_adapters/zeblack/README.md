# Zeblack adapter

The Discovery adapter reads the chapter-list page and its matching protobuf
response. It validates the DOM/protobuf identity set and order before yielding
any records. Records are yielded newest first and carry the site position from
the listing.

The adapter also provides a read-only complete-listing preview for the
Watchlist editor. An exclusion preview binds one validated listing to the next
Discovery run for up to 30 seconds and is consumed once. Unknown exclusions,
boundaries outside the listing, and reversed boundaries fail closed before the
first record is yielded. Preview and replay do not write Catalog state.

Read-only live verification on title 56 observed 44 unique chapter rows from
`chapter5441` (prologue) through `chapter5484` (chapter 43). No viewer or
Catalog/Watchlist write was performed. The production
`preview_complete_listing` returned `ready=true`,
`listing_identity=zeblack-title:56`, and digest
`c8bba701f5fcb9bd1bed8a885ff80367688d60c420b31a030ef043a6b41e5d24`.
Future listing stability is unverified.
