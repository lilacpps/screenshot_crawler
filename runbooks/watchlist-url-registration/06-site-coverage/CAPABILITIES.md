# Stage 06 registration capability matrix

Updated 2026-11-03, Phase 06A/B. These are separate capabilities; title observation
does not imply URL conversion, complete-list preview or free/paid eligibility.
All existing strict canonical entry forms remain usable with human confirmation.

| Site | Canonical input | Additional conversion | Automatic title | Complete-list detail |
|---|---|---|---|---|
| bookwalker | series/list | product→series unsupported (membership/ambiguity not proved) | exact series document, canonical + unique known h1; one-work live | Stage 07, unsupported |
| comicdays | episode | series/work→seed unsupported | no proven non-reader path from episode | existing supported |
| comicfuz | manga/work | viewer→work unsupported (work ID absent from viewer URL) | canonical + native page/mangaId + matching title/og:title; one-work live | Stage 07, unsupported |
| hanayume | episode | series→seed unsupported: scoped public links observed, but native episode/Work binding, order and completeness not established for registration | safe series document exposes title; episode→work association remains unproved | Stage 07, unsupported |
| jumpplus | episode | work→seed unsupported; /series is multi-work navigation | no proven non-reader work identity path from episode | existing supported |
| kadocomi | detail/work | same-prefix episode→detail (Stage 01) | existing exact-detail og:title, one-work live | Stage 07, unsupported |
| magapoke | title/episode | work→seed unsupported: bounded work endpoint redirected; no proven non-consuming seed | work endpoint returned 302 in bounded probe; not followed | existing supported |
| mangaone | manga/chapter | work→seed unsupported | known /manga/work endpoint returned 404; no reader fallback | Stage 07, unsupported |
| piccoma | web/viewer/product/episode | exact web/product/id/episodes → observed first unconditional-free DOM seed, with 0..300s proof; one-work live | derived product listing, canonical + product/episode binding + unique title; one-work live | Stage 07, unsupported |
| younganimal | series/work | episode→series unsupported (work ID absent) | canonical + unique og:title/document-title shape; one-work live | Stage 07, unsupported |
| zeblack | title/chapter/list | numeric title/chapter/viewer→same-title list, pure | static list/detail returned generic site name only; unsupported | existing supported |

Phase 06A evidence: `.tmp/watchlist-registration/stage06-probe-work-docs.json`,
`stage06-probe-binding.json`, `stage06-probe-zeblack.json`, `stage06a-live.json`.
The new metadata paths use one exact document GET, reject redirects and abort
subresources/POSTs; Piccoma viewer input is never navigated. No full Discovery,
resource action, Capture, persisted-data write or comic artifact is used.

Phase 06B production observation at 2026-11-03 06:16 JST:
`stage06b-live.json`, Piccoma product28600, 432 validated oldest-first rows,
DOM1 unconditional-free episode1910027, titleベルセルク. The viewer was never
opened. A sandbox-restricted first attempt safely stayed blocked; the authorized
network verification succeeded. Optional GUI observation retains the initially
checked metadata setting and can be disabled. Without observed proof, listing
input stays blocked with no human override. Proof/URLs/identity/age are rechecked
purely in readiness/preview/save; YAML stores only the canonical seed URL and the
preview labels original input vs saved URL. Native Qt and tests use synthetic
data; they are not additional live certification of other products.
The final Page-lifetime guard was also live checked at 2026-11-03 07:43 JST on
the same BookWalker317089, ComicFUZ1970, Younganimal7103c2c1e9f08 and Piccoma28600
works. Four exact work/listing GETs returned titles and accepted pure validation;
Piccoma again converted to1910027 without opening it. Dedicated Pages were closed.
Evidence: `stage06-final-live.json`. No other work/account states are certified.

All eleven canonical forms are covered by strict offline parser tests. Live
certification is bounded to the explicit works above, not every Work/account or
site variation. Other formats including short/share URLs, product root without
`/episodes`, BookWalker book/product, FUZ viewer, Younganimal episode and unsupported
query/fragment/percent-escaped forms remain blocked. A site table row marked
unsupported is a deliberate fail-closed capability boundary, not an automatic
conversion promise. Existing canonical inputs retain human confirmation when
metadata is unknown. Cross-site same-Work decisions always require humans.

Dynamic work→seed conversion requires input/document/seed/native-identity evidence
bound through preview/save, per [PROOF_CONTRACT](PROOF_CONTRACT.md). Links alone
are insufficient. Hanayume's ten exposed public rows do not prove its complete
inventory or native Work binding, so no series conversion was enabled. Stage 07
is not started; full-list WorkEditor remains the existing four sites only.
