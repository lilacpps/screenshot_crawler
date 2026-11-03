# Stage 06 registration capability matrix

Updated 2026-11-03, Phase 06A/B and seven-site follow-up. These are separate capabilities; title observation
does not imply URL conversion, complete-list preview or free/paid eligibility.
All existing strict canonical entry forms remain usable with human confirmation.

| Site | Canonical input | Additional conversion | Automatic title | Complete-list detail |
|---|---|---|---|---|
| bookwalker | series/list | product→series unsupported (membership/ambiguity not proved) | exact series document, canonical + unique known h1; one-work live | Stage 07, unsupported |
| comicdays | episode | www/trailing slash→canonical; series/work→seed unsupported | exact static episode metadata: canonical + readableProduct.id/series.id/title + matching heading; 3 works live | existing supported |
| comicfuz | manga/work | viewer→work unsupported (work ID absent from viewer URL) | canonical + native page/mangaId + matching title/og:title; one-work live | Stage 07, unsupported |
| hanayume | episode | `/episodes/<13hex>/<positive page>`→base, www/trailing slash→canonical; series→seed unsupported | exact static base episode: canonical + unique strict official Work anchor/title; 3 works live | Stage 07, unsupported |
| jumpplus | episode | www/trailing slash→canonical; work→seed unsupported; /series is multi-work navigation | exact static episode metadata: canonical + readableProduct.id/series.id/title + matching heading; 3 works live | existing supported |
| kadocomi | detail/work | same-prefix episode→detail, supported query removal (Stage 01) | canonical + native work queryKey/code/title preferred; known og:title fallback, conflicts block; 2 works live | Stage 07, unsupported |
| magapoke | title/episode | existing canonical aliases only; work→seed unsupported | exact static episode metadata: canonical + unique Work h1 + present og:title agreement; 3 works live | existing supported |
| mangaone | manga/chapter | canonical chapter only; work→seed unsupported | canonical + unique og:title/document title agreement and known numeric episode suffix; 3 works live | Stage 07, unsupported |
| piccoma | web/viewer/product/episode | exact web/product/id/episodes → observed first unconditional-free DOM seed, with 0..300s proof; one-work live | derived product listing, canonical + product/episode binding + unique title; one-work live | Stage 07, unsupported |
| younganimal | series/work | episode→series unsupported (work ID absent) | canonical + unique og:title/document-title shape; one-work live | Stage 07, unsupported |
| zeblack | title/chapter/list | numeric title root or title/chapter/viewer→same-title list, pure | fixed public title_detail GET; exact response URL/status/type/size + unique native title ID/name; 3 works live | existing supported |

Follow-up live verification at 2026-11-03 08:11 JST used production observers on
all fourteen supplied URLs plus six distinct Watchlist URL/label samples (the
first Kadocomi sample duplicated a supplied Work). All twenty returned titles
and passed pure resolution/save validation. No full Watchlist sweep. Watchlist
was explicitly authorized as read-only ground truth; it is never a runtime
title table/fallback or test fixture. Evidence: ignored
`.tmp/watchlist-registration/coverage_followup_live.json`.

For Magapoke/MangaONE/ComicDAYS/Jump+/Hanayume, only the requested static HTML
metadata document is fetched; scripts, images, iframes and POSTs are denied, so
no viewer is initialized. Kadocomi uses the same guard on its derived detail
page, now retained until dedicated Page close. Zeblack's official frontend
proved the fixed public GET `/api/browser/title_detail?os=browser&title_id=<id>&tab=detail`
on api2.zebrack-comic.com: Response21 TitleDetailView1/2 are ID/name. This is a
site-owned metadata exception, with no shell/JS/viewer/chapter inventory request.
Missing metadata retains explicit manual confirmation; binding/navigation
contradictions block. Titles do not create native grouping proofs or auto-merge.
ComicDAYS/Jump+ validate the episode-bound JSON series ID's shape, without
independently proving a persisted series identity. Hanayume's strict Work link
is title evidence, without an independent native episode/Work binding proof.
These three sites therefore retain identity unknown; a matching title alone
cannot combine episodes or Works. Stage07's complete-list proof is separate.

All document observers additionally replace the response CSP with script-src
'none', object-src 'none', worker-src 'none' and form-action 'none'. Inline
viewer bootstrap cannot run; inert JSON/text metadata remains readable. The
dedicated Page's route guard still remains through close. Lifecycle tests inject
their POST timer explicitly through Page.evaluate, independently of HTML script
execution, so CSP cannot hide an unroute/cleanup regression.

Official names retain subtitles and typography: Kadocomi KC_005686_S returns
「シンコンクエスト 魔王の娘は真面目勇者を堕としたい♡」; Hanayume's sampled
「Ｓ・Ａ」uses full-width letters while the existing label uses half-width.
No legitimate digits, subtitles or existing labels are silently removed.

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
inventory or native Work binding, so no series conversion was enabled. Stage07
separately validates every declared public range for preview without enabling
series conversion. Stage07 is partial: full-list WorkEditor supports8sites
(magapoke/jumpplus/zeblack/comicdays/piccoma/hanayume/younganimal/bookwalker);
BookWalker requires a complete single page in latest-release order. ComicFUZ,
Kadocomi and MangaONE remain blocked for detail; see the Stage07 runbook.
