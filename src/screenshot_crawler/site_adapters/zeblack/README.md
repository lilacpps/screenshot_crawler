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

Batch's deferred Work Ticket resolver can perform one conditional predecessor
reread when none of its pending candidates is currently ticket-available, even
if older completed chapters are available. It requires positive stock from the
same title's native ticket banner, refreshes and validates the complete display
order, then takes the row immediately before the first pending quota candidate,
excluding active RENTAL from that search. Only FREE or safely unexpired RENTAL
predecessors are opened. Paid, expired, unconfirmed or explicitly excluded
predecessors produce an NG without acquiring rights; manual handling is indicated
where access is required.

Rereading rewinds to page_0, advances to verified END/NEXT_CONTENT, and closes
with the observed native `button.sc-bEHKTb`. It never clicks next-story, captures
content or creates acquisition state. Limits are 100 content images, 120 reverse
and 120 forward operations, and 180 seconds overall. Existing runtime content
pacing and AccessGuard remain active. The explicit final list reload alone
provides the prepared entry document; cached native return requires no API event.
There is no new CLI/configuration flag and manual quota entry is unchanged.

An isolated production resolver/Executor run on title 7 reread chapter 100 and
restored ticket availability for pending chapter 101; the final same-document
handle was validated without a ticket click. Expired/paid guards are verified
with artificial browser fixtures. See note/06_zeblack.md for evidence and limits.
