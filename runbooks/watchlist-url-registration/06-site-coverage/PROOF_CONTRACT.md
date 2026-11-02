# Stage 06B — observed work-to-seed conversion contract

Status: IMPLEMENTED / independent implementation review PASS (2026-11-03).
Independent Reviewer design gate passed subject to the following boundaries.

- Start with Piccoma's exact `/web/product/<id>/episodes` form. Pure parsing
  returns blocked, no Discovery URL or verified work identity, plus a strictly
  validated observation URL. Normal metadata observe is unchanged; a separate
  opt-in conversion observer handles only such declared candidates.
- Use one exact guarded work/listing document GET; no redirects, subresources,
  POSTs, reader, Discovery, Catalog/Watchlist/ZIP writes or resource actions.
  Observation owns a dedicated Page only. Its restrictive route remains until
  that Page closes, including success/error/exception cleanup; it is not removed
  at context exit. The caller closes its Page and never reuses it for browsing.
- Canonical, list container/order, unique declared count and exact DOM count,
  every row's same product/unique episode/complete status structure must agree.
  Select the first row in the observed oldest-first DOM order whose existing
  classify_piccoma_access result is free. Never use numeric ID order or the
  reversed Discovery output order; never select quota/rental/paid/unknown.
- Immutable in-memory proof binds original input, site, exact document URL,
  native Work identity, selected external ID and canonical Discovery URL, DOM
  position/count, free selection evidence and observation time. It is internal
  evidence, not an externally accepted serialized token or a persistence schema.
- Shared pure revalidation checks a fresh pending parse, every URL/identity
  binding, the canonical seed parser and a site-owned default-deny validator.
  Proof age must be 0..300s with an aware timestamp. Preview/readiness/save use
  the same validation; save performs no browser/network under locks.
- URL edits/retry discard proof. blocked() discards old proof. Normal safe
  canonical URLs without proof retain the existing manual confirmation path.
  Titles may remain unknown after a proved conversion; humans confirm label/IDs.
- GUI's optional safe-observation checkbox explicitly covers conversion and metadata.
  It retains the existing initially-checked metadata preference; users see the
  expanded label before Analyze and may disable observation. There is no second
  permission modal. Disabled means pending listing input remains blocked.
  Input URL stays in resolution/proof/origins; Watchlist stores the proved
  canonical seed because existing Discovery accepts viewer-shaped inputs only.
  Preview labels input vs saved URL, while YAML shows the actual saved seed.
- Stage 07 complete-list preview remains unavailable. Reading row attributes to
  bind one seed is not a complete-list proof for WorkEditor/scope editing.

Tests: pure unsafe/pending boundaries; tampered field/foreign work/future/stale
proof rejection; missing/ambiguous/paid-only/incomplete status/count/order and
redirect/error no-write browser fixtures; explicit opt-in GUI path; exact YAML
save parity; existing metadata/manual registration/owner/CAS/atomic regressions.
Because model/resolver/save validation is shared, finish with an isolated full
suite using tracked default YAML, not user operational data.
