# Stage 06 registration capability matrix

Updated 2026-11-03, Phase 06A. These are separate capabilities; title observation
does not imply URL conversion, complete-list preview or free/paid eligibility.
All existing strict canonical entry forms remain usable with human confirmation.

| Site | Canonical input | Additional conversion | Automatic title | Complete-list detail |
|---|---|---|---|---|
| bookwalker | series/list | product→series unsupported (membership/ambiguity not proved) | exact series document, canonical + unique known h1; one-work live | Stage 07, unsupported |
| comicdays | episode | series/work→seed unsupported | no proven non-reader path from episode | existing supported |
| comicfuz | manga/work | viewer→work unsupported (work ID absent from viewer URL) | canonical + native page/mangaId + matching title/og:title; one-work live | Stage 07, unsupported |
| hanayume | episode | series→seed under investigation | safe series document exposes title; episode→work association still requires proof | Stage 07, unsupported |
| jumpplus | episode | work→seed unsupported; /series is multi-work navigation | no proven non-reader work identity path from episode | existing supported |
| kadocomi | detail/work | same-prefix episode→detail (Stage 01) | existing exact-detail og:title, one-work live | Stage 07, unsupported |
| magapoke | title/episode | work→seed under investigation | work endpoint returned 302 in bounded probe; not followed | existing supported |
| mangaone | manga/chapter | work→seed unsupported | known /manga/work endpoint returned 404; no reader fallback | Stage 07, unsupported |
| piccoma | web/viewer/product/episode | product/listing→seed under investigation | derived product listing, canonical + exact input episode binding + unique title; one-work live | Stage 07, unsupported |
| younganimal | series/work | episode→series unsupported (work ID absent) | canonical + unique og:title/document-title shape; one-work live | Stage 07, unsupported |
| zeblack | title/chapter/list | numeric title/chapter/viewer→same-title list, pure | static list/detail returned generic site name only; unsupported | existing supported |

Phase 06A evidence: `.tmp/watchlist-registration/stage06-probe-work-docs.json`,
`stage06-probe-binding.json`, `stage06-probe-zeblack.json`, `stage06a-live.json`.
The new metadata paths use one exact document GET, reject redirects and abort
subresources/POSTs; Piccoma viewer input is never navigated. No full Discovery,
resource action, Capture, persisted-data write or comic artifact is used.

Dynamic work→seed conversion needs input/document/seed/native-identity evidence
bound through preview/save. It is not enabled merely because a work page has
episode links. Stage 06B will assess this small shared contract before exposing
such input to the GUI. Stage 07 is not started.
