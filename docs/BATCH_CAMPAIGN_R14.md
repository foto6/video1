# Creator R14 durable batch campaign runner

R14 adds a durable campaign layer above the frozen Creator R11-R13 contracts. It does not replace the R11 short-form state machine, R12 publish-provider protocol, or R13 integration acceptance gates.

## Scope

One campaign brief can expand into a bounded batch of distinct short-form items. Each item carries its own concept, script, asset plan, Media result, QA state, release authorization, R12 publish request/receipt, and Growth handoff. Item failures are isolated; a Media or QA failure on one item does not stop unrelated items.

The campaign contract is \`creator.batch_campaign.r14.v1\`. Durable events use \`creator.batch_campaign_ledger.r14.v1\`.

## Hard limits

\`BatchCampaignConfig\` requires:

- an exact batch size (1-50);
- an explicit Instagram Reels / TikTok / YouTube Shorts platform mix whose counts sum to the batch size;
- generation, Media and provider concurrency ceilings;
- deterministic ceilings for external generation units, render seconds and provider actions;
- a publish window plus positive stagger interval.

Budget is reserved durably before external work. A reservation that would exceed its ceiling raises \`BudgetExceeded\` before the corresponding operation. Reservations are idempotent under restart. In-flight operations are durable too, so a restart cannot silently create a new concurrency slot.

## Diversity

Concept candidates are compared using deterministic normalized semantic-token Jaccard similarity. Duplicate concepts are rejected before item creation. Hooks have both an opening signature and a family; exact signature reuse and configurable family overuse are rejected. Scripts are independently checked against scripts already committed to the campaign.

Rejected candidates remain in the ledger as evidence; they do not consume a batch slot.

## Independent item states

Campaign reports expose the requested operational categories:

- \`ready\`: QA passed and a separate release authorization is bound, but no provider receipt exists;
- \`blocked_media\`: exact Media evidence is unavailable or Media failed;
- \`qa_failed\`: Media succeeded but Creator QA rejected the item;
- \`awaiting_release\`: QA passed but no external \`release.authorization.v1\` is attached;
- \`analytics_pending\`: a validated provider receipt and source-bound Growth handoff exist but Growth acknowledgement is pending;
- \`published\`: the provider receipt exists and the Growth handoff has been acknowledged.

These are per-item states. The campaign itself can be active, paused or canceled.

## Pause, resume, cancel and restart

Control changes are append-only durable events. Pause prevents new budget reservations and side-effecting operations. Resume restores work. Cancel is terminal and cannot be resumed. Restart reconstructs control state, item stages, budget consumption, in-flight operations, and dedup evidence from the JSONL ledger.

## Media and publish boundaries

R14 delegates Media result validation to the existing R11 validator and R13 exact Media pin model. With no accepted Media pin, an item becomes \`blocked_media\` before render budget or provider work is spent.

Synthetic Media is permitted only when the caller explicitly enables conformance mode. Media \`sourceClass\` is preserved unchanged into the R12 publish request; R14 does not promote synthetic Media to provider evidence.

R14 delegates publish idempotency/recovery and terminal receipt validation to R12. Provider actions are wrapped with campaign budget accounting. Lost acknowledgement after a provider side effect is recovered through the existing R12 authoritative-recovery path instead of a second logical publish.

No live provider adapter is introduced by R14.

## Growth is advisory only

A Growth experiment/seed object may be attached to campaign creation. R14 stores only a sanitized advisory projection: source version/class, evidence digest, recommendations, and whether an attempted publication-authority flag was ignored.

Growth cannot create \`release.authorization.v1\`, move an item from \`awaiting_release\` to \`ready\`, or invoke publication. Even an input containing \`publish_authorized=true\` remains advisory and is recorded with \`publicationAuthorityAccepted=false\`.

Post-publication Growth handoffs are produced only from validated R12 receipts.

## Deterministic 12-reel replay

\`run_synthetic_12_campaign\` and the focused R14 tests execute one deterministic campaign with:

- 12 accepted items across a 4/4/4 platform mix;
- 14 generated candidates containing two injected semantic duplicates;
- one deterministic Media terminal failure;
- one Creator QA failure;
- one item intentionally awaiting release;
- one release-authorized item intentionally left ready;
- eight mocked provider publishes;
- one crash after provider side effect but before local acknowledgement, followed by campaign restart and R12 recovery;
- seven Growth-acknowledged published items and one analytics-pending item.

Expected final item counts are:

\`ready=1, blocked_media=1, qa_failed=1, awaiting_release=1, published=7, analytics_pending=1\`.

The synthetic replay performs no network publishing and uses opaque credential references only.

## Command

Run the deterministic 12-reel acceptance replay without changing code:

\`\`\`bash
PYTHONPATH=src python -m creator_orchestrator.batch_campaign synthetic-12 --work-dir /tmp/creator-r14-batch
\`\`\`

The command emits a machine-readable campaign report including state counts, budget use, maximum observed concurrency, Growth advisory projection, exact R13/Growth source pins, Media readiness evidence, and replay counters.
