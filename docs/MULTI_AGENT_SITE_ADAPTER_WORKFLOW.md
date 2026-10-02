# Multi-Agent Site Adapter Workflow

## 1. Purpose

This document defines the gated multi-agent workflow for adding a new Site Adapter.

The goal is not to parallelize writes. The goal is to move the existing
"plan -> investigate/implement -> review -> fix -> review" loop inside Codex while
keeping one clear writer and an independent read-only reviewer.

Use this workflow when the user explicitly asks for autonomous or multi-agent
implementation of a new Site Adapter.

## 2. Roles

### Root orchestrator

The root Codex session is the orchestrator.

For this workflow, start the root session with **GPT-6.1 Sol** at high reasoning effort.
The repository does not force the root model globally so ordinary Codex work can keep
using a cheaper model when desired.

Responsibilities:

- read repository authorities and relevant existing adapters before planning;
- define the current phase from evidence, not from a fixed script;
- give the worker a bounded task with purpose, scope, constraints, acceptance criteria,
  and required tests/live verification;
- inspect worker evidence and send the result to the reviewer;
- decide whether more Probe/PoC work, a fix, or a phase change is needed;
- keep the workflow moving until the overall acceptance criteria are met or a genuine
  external blocker requires the user.

The root orchestrator should not implement production code itself during this workflow.
Production changes belong to the worker so review boundaries remain clear.

### `site_adapter_worker`

Configured in `.codex/config.toml` and backed by GPT-5.6 Luna.

Responsibilities:

- perform repository investigation assigned by the root;
- use the existing shared Crawler Chrome/CDP path for real-site research;
- create and iterate small Probe/PoC helpers when behavior is unknown;
- implement the current bounded phase;
- update tests and the relevant site note in the same change;
- run the tests selected by `docs/TEST_STRATEGY.md`;
- perform live verification when the phase requires it;
- return observed facts, changed files, design decisions, tests, live results, and
  remaining uncertainty to the root.

The worker is the only subagent role allowed to modify production files during this
workflow.

### `site_adapter_reviewer`

Configured as GPT-6.1 Sol with a read-only sandbox.

Responsibilities:

- review the worker result against repository authorities and the current phase contract;
- distinguish observed live-site facts from assumptions;
- inspect implementation, tests, notes, and reported live evidence;
- identify correctness bugs, missing edge cases, regression risk, architecture
  violations, and insufficient verification;
- avoid blocking on style preferences that do not cause a material problem.

The reviewer reports findings in three groups:

- `BLOCKING`: must be resolved before the phase can complete;
- `NON-BLOCKING`: useful follow-up that is not required for the current phase;
- `VERIFIED`: contracts/evidence that were checked and appear consistent.

The reviewer never edits files. If additional commands or tests are needed, it asks the
root to send that work to the worker.

## 3. Gated loop

For every phase, the root follows this loop:

1. Define the phase contract:
   - purpose;
   - known facts;
   - unknowns to resolve;
   - allowed change scope;
   - constraints;
   - acceptance criteria;
   - targeted/affected/integration/live checks required.
2. Delegate the phase to `site_adapter_worker`.
3. Wait for the worker result.
4. Delegate review of that exact result/diff/evidence to `site_adapter_reviewer`.
5. If any `BLOCKING` finding exists:
   - assess whether the problem is an implementation bug, missing evidence, or a wrong
     design assumption;
   - send a focused follow-up to the same worker when possible;
   - review again after the worker finishes.
6. Repeat until `BLOCKING` is empty.
7. Advance only when the phase acceptance criteria and required verification are
   satisfied.

A phase may be split, merged, repeated, or replaced when evidence changes the plan.
The initial plan is guidance, not authority over observed site behavior.

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

Parallelism is allowed only for independent read-heavy work such as:

- reading separate existing adapters;
- inspecting separate logs or probe artifacts;
- checking independent hypotheses.

Do not have multiple agents edit the same mutable area concurrently.

During the gated Site Adapter workflow, there is exactly one production writer:
`site_adapter_worker`.

Worker and reviewer are normally sequential, not concurrent.

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

- work on a feature branch, not `main`/`master`;
- do not discard unrelated uncommitted user changes;
- if the current branch is `main`/`master` and the working tree is clean, create a
  feature branch appropriate to the site;
- if branch creation would overwrite or discard user work, stop and report the blocker.

For live Discovery/Batch experiments:

- do not mutate the user's normal `catalog.sqlite` when the task supplies an
  experiment-specific catalog;
- use the experiment catalog throughout the task;
- do not silently switch back to the normal catalog;
- do not automate CAPTCHA/MFA bypasses or paid purchases;
- if the requested scope is free-only, do not consume tickets, points, coins, or other
  quota/paid resources.

Generated crawl output and browser-profile state are not protected by Git branching, so
the root must keep the experiment scope explicit.

## 8. Suggested phase shape for a new manga site

The root may start from this shape, but must adapt it to evidence.

### Phase 0: repository and site reconnaissance

Read authorities and relevant adapters. Identify the smallest investigation needed.
No speculative production implementation.

### Phase 1: Discovery research

Probe listing/episode identity, ordering, expansion, metadata, and access states.

### Phase 2: Discovery productionization

Implement Discovery and the minimum registry/watchlist/policy integration required by
the observed contract.

### Phase 3: viewer/capture research

Probe viewer entry, capture source, navigation, identity, loading, END, and
NEXT_CONTENT. Prefer source-native capture when supported by evidence and repository
capture policy.

### Phase 4: crawl productionization

Implement the Site Adapter and any site-local capture helper needed for the supported
scope.

### Phase 5: end-to-end verification

Verify the supported scope through the real pipeline, for example:

```text
Discovery -> Catalog -> Batch/selection -> Crawl -> manifest/output -> normal terminal state
```

Update site documentation/note with verified behavior and known limitations.

These phases are not mandatory boundaries. The root may insert additional Probe phases
or revisit an earlier phase when new evidence invalidates an assumption.

## 9. Review checklist

The reviewer prioritizes material issues:

- mismatch between live evidence and code;
- unsupported assumptions;
- incorrect/free/paid/quota classification;
- incomplete Discovery or wrong ordering/identity;
- wrong capture source, degraded image quality, or duplicate/missing pages;
- unsafe END/NEXT_CONTENT logic;
- unbounded waits/retries or removed guards;
- site-specific logic leaking into Core;
- premature shared abstraction;
- regression risk to existing sites;
- inadequate targeted/integration/live tests;
- note/documentation that disagrees with implementation.

Style-only preferences are non-blocking unless they create a maintainability or
correctness risk.

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
