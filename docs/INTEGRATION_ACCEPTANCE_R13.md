# Creator R13 integration acceptance

R13 is an acceptance layer over the already-green Creator R11 orchestration and Creator R12 durable publish provider layer. It does not replace either contract. The acceptance contract is \`creator.integration_acceptance.r13.v1\`, and the durable boundary ledger is \`creator.integration_acceptance_ledger.v1\`.

## Current readiness

The committed readiness report is \`reports/CREATOR_R13_INTEGRATION_READINESS.json\`.

Creator R11 and R12 are green at the R12 starting head \`3594a907bb0c16469f33909af102714bdecaaafd\`. Growth R11 is pinned read-only to \`foto6/video3@c4ed94d3e76b75d36bf8cc8280f6937f455133a6\`, including conformance manifest blob \`8b47817cb344c4a1670d338fca351c1056e8ba6f\`, implementation blob \`3fde5ed6fbae9356cc232613a8a81ea442c74315\`, and unchanged R10 conformance blob \`0a63ebece0fe8620a57e635143cc3ea16d095f59\`.

Media remains fail-closed. At implementation time the R11 branch was observed at candidate \`530e0ea43288840d2d66609ca2407640522df3f7\`, with short-form manifest blob \`07c38a048d23490b8e55924697650e9969bf089f\`, Creator-consumer blob \`8d979c9a8f59259c5092c20b0c48c153f41b64a8\`, job-contract blob \`96b252acae743f8fe059fd634ee320f92bd9c79c\`, and artifact-manifest blob \`42aed1ca4720cddd4a5e48af076bc73b663322b0\`. No GitHub Actions run existed for that exact head at observation time, so R13 reports \`BLOCKED_MEDIA\`. Contract files alone are not treated as a green Media producer.

## Lifecycle exercised

Once an exact Media pin is supplied, the synthetic acceptance runner executes:

\`brief -> research -> idea/hook -> script -> asset plan -> edit/Media request -> Media result -> critic/QA -> release authorization -> R12 publish request -> asynchronous provider recovery/status -> terminal publish receipt -> Growth handoff -> Growth R11 provider-metrics evidence -> R10-compatible next-cycle seed -> Creator next-cycle consumption\`.

The seven cross-system boundaries are each committed to an fsync-backed append-only acceptance ledger. Replaying identical bytes returns \`duplicate\`; conflicting replay fails closed.

## Media fail-closed rule

A Media pin must include the exact producer SHA, the existing \`media.job.v1\` and \`media.artifact_manifest.v1\` Git blob SHAs, the R11 short-form conformance manifest and Creator-consumer blob SHAs, and an exact-head CI run ID whose supplied conclusion is \`success\`. Missing evidence, the pre-milestone producer SHA, or a non-success CI conclusion produces \`BLOCKED_MEDIA\` before any synthetic lifecycle is run.

The command-line runner does not query GitHub. The independent coordinator is responsible for supplying evidence it has independently verified against the landed Media head. This prevents a moving branch ref from silently becoming acceptance evidence.

## Growth R11 provenance

The harness pins the Growth R11 provider-ingestion producer, manifest, implementation, R10 contract, and all three provider fixture Git blobs. Growth evidence must remain \`growth.shortform_platform_metrics.v1\`.

Synthetic metrics require \`source_class=synthetic_fixture\`, provider \`fixture\`, an explicit fixture SHA-256, and \`live_performance_claim_allowed=false\`. Live evidence requires \`source_class=platform_export\`, provider equal to the platform, no fixture SHA, and the live flag set. A synthetic R12 mock receipt therefore cannot be promoted to a live-performance claim.

The generated Growth next-cycle seed is validated again by Creator's existing strict R10 consumer contract before it is durably consumed by a new Creator cycle.

## Recovery and exactly-once evidence

Focused R13 tests inject or simulate restart at every recorded cross-repo boundary. Additional unknown-ack tests cover all side-effecting integration boundaries:

- Media accepts the logical render before Creator acknowledgement, then replay returns the same result under the same idempotency key;
- R12 publish accepts the logical provider side effect before local acknowledgement, then authoritative recovery resumes without a second submit;
- Growth accepts the handoff before Creator acknowledgement, then replay returns the same provider-metrics/seed result.

Each test asserts one logical side effect. The provider flows are deterministic mocks for Instagram Reels, TikTok and YouTube Shorts. CI performs no network provider mutation and stores no credentials.

## Commands

Current fail-closed readiness check:

\`\`\`bash
PYTHONPATH=src python -m creator_orchestrator.integration_acceptance readiness
\`\`\`

That command intentionally exits non-zero while Media is blocked.

After Media R11 lands and an independent coordinator has verified an exact compatible head and successful exact-head CI, the full three-platform synthetic acceptance is one command and requires no code edit:

\`\`\`bash
PYTHONPATH=src python -m creator_orchestrator.integration_acceptance run \
  --platform all \
  --work-dir /tmp/creator-r13-acceptance \
  --media-producer-sha <EXACT_MEDIA_SHA> \
  --media-job-contract-blob-sha <MEDIA_JOB_V1_BLOB_SHA> \
  --media-manifest-contract-blob-sha <MEDIA_ARTIFACT_MANIFEST_V1_BLOB_SHA> \
  --media-conformance-manifest-blob-sha <MEDIA_R11_SHORTFORM_MANIFEST_BLOB_SHA> \
  --media-creator-consumer-blob-sha <MEDIA_R11_CREATOR_CONSUMER_BLOB_SHA> \
  --media-ci-run-id <EXACT_HEAD_CI_RUN_ID> \
  --media-ci-conclusion success
\`\`\`

A successful run reports \`SYNTHETIC_ACCEPTANCE_GREEN\` and always sets \`productionReadinessClaim=false\`. It is evidence that the versioned boundaries compose deterministically; it is not authorization for live publishing.
