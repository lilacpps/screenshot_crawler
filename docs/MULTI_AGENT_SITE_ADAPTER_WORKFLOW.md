# Multi-Agent Site Adapter Workflow

## 1. Purpose

This is the evidence-gated workflow for autonomous new Site Adapters. The
intent is to move repository investigation, small proof, implementation,
independent review, and optional independent E2E inside a coordinated Codex
session; it is **not** to maximize simultaneous agents or simultaneous writes.

Every stage needs evidence-based decisions and bounded scope. The runbook for
the specific adapter narrows supported access and validation but must not
override repository authorities. For the Piccoma public ¥0 scope, use
`runbooks/piccoma-free/README.md`.

Do not silently replace the old BookWalker-specific workflow or its agents.

## 2. Roles

| Role | Model / reasoning effort | Scope |
| --- | --- | --- |
| Lead / Root orchestrator | GPT-6.1 Sol / Very High (`gpt-6.1-sol`, `xhigh`) | coherence, decisions, phase contract, checkpoints, sign-off |
| `site_adapter_explorer` | GPT-6 Luna / Very High (`gpt-6-luna`, `xhigh`) | code/site investigation and independent risks; read-only |
| `site_adapter_implementer` | GPT-6 Luna / Very High (`gpt-6-luna`, `xhigh`) | sole production writer; bounded probes, code, tests and notes |
| `site_adapter_reviewer` | GPT-6.1 Sol / High (`gpt-6.1-sol`, `high`) | independent read-only quality gate |
| `site_adapter_tester`, as needed | GPT-6 Luna / High (`gpt-6-luna`, `high`) | independent E2E/live/logs/artifact verification; no production edits |

The Lead selects the root model/reasoning effort for this particular session;
do **not** force the repository's global root model. Actual role model and
effort configuration lives in `.codex/config.toml` and matching
`.codex/agents/site-adapter-*.toml` files. Very High maps to `xhigh` in the
Codex configuration. Validate availability before starting; do not silently
substitute models or effort if unsupported. The legacy `site_adapter_worker`
entry remains for historical work only, not for a new runbook's Implementer.

### Lead
- Read authorities, tests, existing adapters, and the workstream runbook.
- Define each phase's objective, known evidence, unresolved questions,
  allowed paths, forbidden paths, constraints, acceptance, required tests and
  checkpoint; make design decisions from evidence, not speculation.
- Orchestrate sequential browser access and decide when to use Tester.
- Judge whether a phase should advance, repeat, split or stop for a genuine
  external blocker. Lead does not edit production files during this workflow.

### Explorer (read-only)
- Independently inspect current repository and site behavior; extract
  evidence, access-state distinctions, viewer/layout risks and edge cases.
- Distinguish OBSERVED, INFERRED/HYPOTHESIS and UNKNOWN; make targeted
  questions for a browser probe instead of writing speculative production.
- Never edit production or consume quota/tickets. If read-only sandbox cannot
  perform the required probe or persist diagnostic files, request a bounded
  Implementer probe through Lead.

### Implementer (only production writer)
- Carry out the bounded phase contract after Lead resolves assumptions.
- Create small PoC probes when necessary; implement and test only the
  accepted evidence-backed behavior.
- Update corresponding site README/`note/` and include exact changed paths,
  tests/skips, live facts, unresolved questions and safe logs in the handoff.
- Never modify unrelated user changes or route around access controls.

### Reviewer (independent, read-only)
- Inspect the actual diff and evidence against authority and phase contract.
- Prioritize correctness, identity/access gate, incomplete discovery,
  image/page fidelity, security, regression and missing tests; separate
  material problems from stylistic preferences.
- Classify findings as BLOCKING, NON-BLOCKING or VERIFIED. Never edit files.
  Send needed fix/probe requests through Lead.

### Tester (optional independent verifier)
- Independently execute targeted Integration, live E2E, or verify output,
  page sequence, manifest/ZIP, logs and Catalog status when high-risk behavior
  merits separation from Implementer's own tests.
- Tester has workspace-write solely to produce isolated test fixtures/logs
  and reports; **production code, specs and production tests are off-limits**.
- Follow Lead-managed exclusive shared browser access. Report
  PASS/FAIL/NOT VERIFIED with supporting facts and skip reasons.

## 3. Gated loop

1. Lead defines one bounded phase contract (purpose, evidence, unknowns,
   allowed and forbidden changes, safety, acceptance, tests, live checks,
   checkpoint format).
2. Explorer investigates missing facts. For known facts already documented,
   avoid ceremonial re-investigation.
3. Lead adjudicates evidence and delegates the accepted scope to Implementer.
4. Implementer writes production/tests/notes and returns diff + evidence.
5. Reviewer independently inspects material changes and returns
   BLOCKING/NON-BLOCKING/VERIFIED.
6. Each BLOCKING item returns to Implementer for a focused fix/probe and
   then Reviewer rechecks; do not advance while BLOCKING remains.
7. Tester is used for independent E2E/live validation when capture,
   entitlement, terminal, shared boundaries or output integrity warrant it.
   Tester findings that expose a bug reenter steps 3–6.
8. Lead records the checkpoint and either advances, revisits earlier
   hypotheses, or reports a genuine external blocker with unverified gates.

A stage can be merged/split/repeated. No simultaneous production writers.
Independent read-heavy Explorer/Reviewer work can overlap **only** when it
does not invalidate review on an in-flight change; final review always
addresses the exact completed diff. The shared live browser has one operator
at a time regardless of agent role.

## 4. Research-before-implementation rule

Do not assume a new site behaves like Magapoke, Jump+, Zebrack, BookWalker, or Manga ONE
just because its UI looks similar.

When a production decision depends on unknown real-site behavior:

1. inspect the live site through the existing CDP-connected Crawler Chrome;
2. prefer a small bounded Probe/PoC;
3. record the relevant observation;
4. implement only after the observation is strong enough to support the contract.

Examples that normally require observation include:

- episode-list structure and expansion;
- stable work/episode identity;
- free/paid/quota semantics;
- viewer entry flow;
- image/canvas/source-native capture path;
- scrambling or reconstruction;
- page identity and page-change signals;
- spread/order behavior;
- loading/interstitials/ads;
- final-page behavior, END, and NEXT_CONTENT.

If evidence remains ambiguous, stop that production decision and probe further instead
of guessing.

## 5. Parallelism policy

Parallelism is allowed for independent, read-heavy repository or source
analysis. Avoid two agents changing the same mutable area. Implementer is
the **sole production writer**; Explorer and Reviewer are read-only.
Tester may write isolated test artifacts and reports only, never code.

Do not let Explorer, Implementer and Tester concurrently drive the shared
Crawler Chrome/CDP viewer. Browser operations, including read-only
navigation, can mutate reading position, account/session state and
response traces; Lead assigns an exclusive window per operator.
Final Reviewer gate follows the completed Implementer diff, not a
partially written branch.

## 6. Browser policy

All real-site work follows the repository Browser Session policy:

```text
shared Crawler Chrome/profile
    ↑ CDP
Playwright Browser / Context / Page
    ↓
Core Runner
    ↓
Site Adapter
```

The new adapter must not launch Chrome, choose profiles, resolve the endpoint, or call
`connect_over_cdp()` itself.

Use Playwright for normal browser interaction. Raw CDP Protocol is only for cases that
cannot reasonably be handled with Playwright and must follow existing repository
architecture.

## 7. Safety and isolation for experimental adapters

Before production edits:
- Use a feature branch, not `main`/`master`. Preserve unrelated uncommitted
  user changes; if safe branching is impossible, stop and report.
- Use a task-specific Watchlist, SQLite Catalog, output and protected
  evidence directory. Never silently switch to normal `catalog.sqlite`.
- A Git branch does not isolate shared Chrome profile or runtime files.
- Never commit cookies, browser profile, secrets, signed credentials, private
  logs, or copyrighted page bodies; sanitize diagnostic URLs.

For live Discovery/Batch:
- Avoid CAPTCHA/MFA bypasses, payment, access-control/DRM circumvention.
- In free-only scope do **not** consume ticket/charge/coin/point/gift or
  automate login/paid operations. Personally readable content or a prior
  unlock is **not** proof of unconditional free access.
- Listing and actual Viewer entry must both validate the target identity
  and current free access; unknown/mismatch/expiration fails closed.
- Negative access tests use synthetic/local fixtures, never real quota.
- Respect AccessGuard, pacing, finite retries, max_pages, and complete
  capture/terminal guards.

## 8. Suggested phase shape for a new manga site

Adapt phases to evidence; don't start with guessed source-native capture.

### Phase 0/1: site and repository reconnaissance
Explorer inspects existing code, full native listing, identity, free/paid
semantics, UI/viewer, source provenance and terminal signals. Implementer
can write a small bounded probe where necessary; Lead records findings.

### Phase 2: Discovery production
Implementer adds parser, access classification and minimal explicit
registration; verify complete list before yield, full/incremental and
site-native bounded ordering where proven. Reviewer gates.

### Phase 3: Viewer/capture production
Probe and implement only observed viewer variants; require current free
preflight, page identity, reading order and source-native provenance.
Reviewer gates; Tester may independently audit captures.

### Phase 4: Site Policy and Batch
Connect only supported resources to generic Planner/Executor/Runner and
manifest/ZIP, without speculative shared refactors. For free-only, policy
is direct-only and all non-free modes are ineligible.

### Phase 5: end-to-end
Independent Tester checks real Discovery → Catalog → Batch → Crawl →
manifest/ZIP and representative actual pages, as available. Reviewer
re-checks any resulting production fixes. Lead signs off verified scope,
known limitations and unverified gates.

For Piccoma, use the detailed phase entry/exit contracts under
`runbooks/piccoma-free/` instead of this general outline.

## 9. Review checklist

Reviewer prioritizes materially wrong or unsupported behavior:
- contradictions between live evidence, code and declared supported modes;
- misclassified public free versus quota, purchased, rented or UNKNOWN;
- incomplete/partial listing, identity collision, stale Catalog, wrong order
  or range-local numbering;
- paid/charge/control entry risk or wrong-target navigation;
- image provenance, quality, page/spread completeness, duplicates, loss;
- incorrect END/NEXT_CONTENT, unbounded retry, hidden stale page state;
- Core or shared abstraction leakage, regression to other adapters;
- insufficient Unit/Integration/live verification or wrong site notes.

Style-only preferences are NON-BLOCKING unless material to maintainability.

## 10. Completion contract

A new adapter is complete only when:

- the requested supported access scope is explicit;
- Discovery behavior is implemented and tested;
- crawl behavior is implemented and tested;
- required live-site assumptions have been verified;
- the requested end-to-end path succeeds on at least one representative supported item;
- output/manifest behavior is consistent with repository contracts;
- relevant note/README documentation reflects current behavior;
- reviewer has no remaining `BLOCKING` findings;
- independent Tester has checked actual images/E2E when the work is high risk
  and a usable live browser is available;
- remaining limitations and unverified behavior are listed explicitly.

At the end, the root reports:

- phases actually executed;
- important observed site facts;
- changed files;
- tests and results;
- live verification performed;
- known limitations;
- deferred access modes/features;
- any verification that could not be completed and why.
