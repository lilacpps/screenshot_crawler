# 01 — Evidence-first site reconnaissance

Status: ACCEPTED. [Parent runbook](../README.md); [PROGRESS](../PROGRESS.md).
Lead owns the decision; Explorer gathers read-only evidence. Implementer may
create a minimal bounded PoC only when read-only observation is insufficient.

## Objective and inputs
Inspect provided viewer URLs (28600/1910027, 28600/4142286, 28606/2001009)
and https://piccoma.com/web/product/28600/episodes. Read AGENTS.md,
docs/SITE_ADAPTER_GUIDE.md, docs/CAPTURE_STRATEGY.md, and the Comic DAYS,
Jump+ and Zeblack adapters/notes before relying on familiar patterns.

## Work
1. In shared Chrome/CDP determine listing expansion/pagination, full count,
   native order, product/episode stable IDs, canonical URL, label/title,
   metadata, and whether the supplied seeds appear. The index for product
   28606 must be verified before use.
2. Investigate public ¥0, 待てば¥0, ¥0+, paid, purchased, previously
   unlocked and campaign displays. Record exact, positive site-native signals
   separating **unconditional free** from merely readable. Do not click
   charge/ticket/purchase/unlock controls.
3. Find at least one genuinely current ¥0 episode if available. Observe
   viewer mode (horizontal/vertical, image/canvas), body page identity,
   source formats/dimensions, page turns, lazy loading, reading position,
   interstitials, final screen, END and NEXT_CONTENT. A logged-in shared
   profile must not be treated as evidence of public free entitlement.
4. Bounded response inspection only; sanitize URLs and metadata, record
   actual site request types without secrets or payloads. Never infer original
   image provenance merely from size or a guessed tile transform.
5. Note how product 28606 differs from 28600, especially view types.

## Evidence and gate
Produce a table of each target URL, observed ID, access classification
evidence, viewer type, navigation, capture candidates, END observation,
confidence and unverified items. Distinguish OBSERVED/HYPOTHESIS/BLOCKED.

Accept only after Lead has enough evidence to specify a trustworthy listing
and free-entry contract; otherwise record the external blocker. No production
code needed in this phase. Reviewer may be requested for high-risk decisions.
No site consumption allowed. Record checkpoint in PROGRESS.md.
