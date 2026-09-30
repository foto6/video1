# Creator R11 Autonomous Reels Orchestrator

## Scope

R11 adds an additive durable short-form orchestration ledger without changing the frozen
legacy `JobStage` / CampaignCheckpoint v1 state machine. The R11 ledger is append-only,
fsynced JSONL and is intentionally provider-neutral. It coordinates short-video planning,
source-bound Media results, critic/QA, an explicit release authorization, publish-provider
recovery, and the Growth R10 next-cycle handoff.

The canonical R11 stage order is:

`brief -> research_evidence -> idea_hook -> script -> asset_plan -> edit_request -> media_render -> critic_qa -> publish_queue -> publish_result -> analytics_handoff`

Every committed stage records a stable idempotency key, canonical payload digest, and
explicit provenance record. Restart reconstructs the logical state exclusively from the
durable event log.

## Canonical short-form profile

`creator.shortform_profile.v1` fixes the Creator-side output intent to:

- 1080 x 1920 pixels, 9:16, 30 fps;
- target duration 15-60 seconds;
- hook window 0-3 seconds;
- 48 kHz stereo audio with -14 LUFS target metadata;
- MP4 / H.264 / AAC / yuv420p with fast-start metadata;
- caption, CTA, hashtags, and Instagram Reels / TikTok / YouTube Shorts targets;
- a center-80% critical-text safe-area policy.

The profile is content-addressed by `profileDigest` and is bound into the edit request,
Media result, and durable cycle identity.

## Stage payload and provenance requirements

The stage payloads preserve enough evidence to reconstruct why a publish was permitted:

- `brief`: goal, topic, audience;
- `research_evidence`: source URI, SHA-256, capture time for every evidence item;
- `idea_hook`: idea, hook, and the exact canonical hook window;
- `script`: monotonic revision number, full text, SHA-256;
- `asset_plan`: external asset identity, source URI, SHA-256, rights reference;
- `edit_request`: voice, music, subtitles, declarative edit operations, profile digest;
- `media_render`: source-bound Media job/result/manifest/preview/timeline envelope;
- `critic_qa`: explicit pass decision, QA digest, individually passing checks;
- `publish_queue`: immutable final-artifact binding, caption/CTA, release authorization,
  and provider-adapter readiness/recovery evidence;
- `publish_result`: provider receipt only;
- `analytics_handoff`: a Growth `growth.shortform_publish_result.v1` payload plus
  content digest.

Secret-shaped fields such as API keys, bearer tokens, credentials, passwords, access
tokens, private keys, or raw Authorization headers are rejected before durable append.
Semantic release fields such as `releaseAuthorization` and `authorizationId` remain
allowed because they are authorization lineage identifiers, not credentials.

## Media R11 boundary

Creator does not contain ffmpeg, timeline compilation, rendering, probing, or codec logic.
`creator.media_r11_result_envelope.v1` only validates Media-owned output.

The envelope is bound to:

- repository `foto6/video2`;
- branch `agent/media-r11-autonomous-reels-20261001`;
- exact producer commit supplied to the ledger;
- `conformance/media.job.v1/consumer-manifest.json` and its exact Git blob SHA;
- `conformance/media.artifact_manifest.v1/manifest.json` and its exact Git blob SHA.

A successful result must contain a `media.job.v1` succeeded job and
`media.artifact_manifest.v1` whose logical job ID, idempotency key, render fingerprint,
profile digest, final content SHA-256/size, probe evidence, QA evidence, and atomic
finalization all agree. Probe evidence must prove a 1080x1920 video between 15 and
60 seconds, and QA must pass.

At implementation time the Media R11 branch still resolves to its pre-milestone head
`2366b3820c2cbf429aa734f2e623689699e73003`. Provider-class Media envelopes from that
head fail closed with `DependencyUnavailable`. Synthetic fixtures are accepted only when
the caller explicitly enables conformance mode. When Media R11 advances, Creator can be
pinned to that exact producer SHA without changing rendering logic.

Observed contract blobs used by the R11 conformance test:

- Media job consumer manifest:
  `96b252acae743f8fe059fd634ee320f92bd9c79c`;
- Media artifact-manifest conformance manifest:
  `42aed1ca4720cddd4a5e48af076bc73b663322b0`.

## Growth R10 boundary and exactly-once consumption

`creator.growth_r10_seed_envelope.v1` consumes the actual Growth R10 contract
`growth.reels_next_cycle_seed.v1` from:

- repository `foto6/video3`;
- branch `agent/growth-r10-autonomous-reels-20261001`;
- producer SHA `7209a2a9033c4ced0690b8311e6f1661681e7ca2`;
- `growth_analytics/autonomous_reels.py`;
- Git blob SHA `808ebeb3df424f480dea4a394174fcf7356849b8`;
- conformance document `conformance/growth.autonomous_reels.v1/contract.json`, blob
  `0a63ebece0fe8620a57e635143cc3ea16d095f59`.

Creator validates the exact current v1 top-level field set, including the R10 `evidence`
bundle added by the final producer. The embedded `growth.shortform_publish_result.v1` and
`growth.shortform_metric_snapshot.v1` are digest-checked and must bind the same platform
post, cycle revision, source class and lineage; the seed metrics must match the embedded
snapshot, and a bound decision reference must match its embedded handoff digest. Creator
also checks live/synthetic eligibility, advisory-only authority flags, Growth idempotency
identity, and the complete seed digest. A seed for a stale/future source revision or a
different Creator cycle fails closed.

The R11 event log records `growth_seed_consumed` before acknowledging receipt. Therefore:

1. an identical replay is a no-op;
2. the same idempotency key with changed bytes is rejected;
3. restart reconstructs the accepted-key set;
4. a crash after durable consume but before acknowledgement replays as `duplicate`;
5. stale or out-of-order cycle revisions cannot advance the cycle.

Growth evidence never authorizes publishing; its authority flags must explicitly keep
auto-publish, external mutation, release authorization, and publish authorization false.

## Publish authorization and provider recovery

Publish is not enabled merely because Media and critic/QA passed.

`publish_queue` requires:

- an approved exact `release.authorization.v1`;
- `decisionSource == "external"`;
- immutable binding to the final Media content ID and SHA-256;
- exact provider/destination release scope;
- a future expiry relative to the decision;
- provider adapter state `ready`;
- recovery support and idempotent submit;
- durable adapter-state evidence digest.

`execute_publish(provider, now=...)` re-validates the queued authorization and checks its
expiry at execution time before any provider call. The runtime provider must match the
queued provider/destination and advertise recovery + idempotent submission.

The ledger writes `publish_operation_prepared` before the external call. On retry it first
calls `recover(idempotency_key)`. If the provider performed the side effect but the
acknowledgement was lost, recovery returns the original receipt and Creator commits
`publish_receipt_committed` plus the `publish_result` stage without submitting again.

Creator cannot manufacture credentials or a live post claim. The synthetic reference
provider emits `sourceClass=synthetic_fixture`; the subsequent Growth publish-result
handoff therefore has `live_performance_claim_allowed=false` and fixture provenance.
A live Growth publish-result can be emitted only from a validated provider-class receipt.

## Deterministic fault evidence

`fixtures/autonomous_reels_r11_e2e.expected.json` freezes the canonical profile, source
pins, stage-crash snapshot, and fault outcomes.

`tests/test_autonomous_reels_r11.py` proves:

- crash/restart after every R11 stage;
- deterministic state reconstruction and byte-stable expected evidence;
- duplicate Media result is a no-op, conflicting duplicate fails closed;
- Media provider evidence fails closed while the R11 producer is still at its
  pre-milestone head;
- Growth seed lost acknowledgement replays exactly once;
- stale Growth revision is rejected;
- publish side effect + lost acknowledgement is recovered by the same idempotency key;
- exactly one provider side effect occurs in that recovery scenario;
- external release authorization and ready provider state are mandatory;
- expired release authorization is rejected before provider invocation;
- synthetic publish evidence cannot become a live Growth claim;
- secret-shaped durable stage fields are rejected.

## Reproduction

Focused R11 suite:

    PYTHONPATH=src python -m unittest discover -s tests -p 'test_autonomous_reels_r11.py' -v

Full Creator suite:

    PYTHONPATH=src python -m unittest discover -s tests -v

The branch CI runs both commands independently on Python 3.11. No merge, release, live
provider mutation, Media repository mutation, or Growth repository mutation is performed
by this milestone.
