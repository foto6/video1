# Creator R12 durable publish provider layer

## Scope

R12 adds a provider-neutral publishing boundary after a validated Media render and release.authorization.v1 approval. It does not enable live publishing in CI and does not change the R11 Media dependency pin. Media R11 remains fail-closed at its unavailable pre-milestone head.

The provider contract version is creator.publish_provider.v1. A provider exposes four operations: prepare, submit, recover, and status. Prepare is side-effect-free and performs credential and capability gating. Submit creates the logical provider publish operation under Creator's stable idempotency key. Recover is always consulted before a submit when Creator has no durable provider operation handle. Status is read-only from Creator's point of view and follows asynchronous provider processing to a terminal state.

## Durable safety model

Creator persists creator.publish_request.v1 before any provider interaction. The request binds platform, account, destination, exact Media content SHA-256 and manifest digest, caption, CTA, credential reference, authorization lineage, and the complete release authorization digest and expiry.

Only opaque credential references and authorization lineage are durable. Provider tokens, passwords, Authorization headers, cookies, API keys, refresh tokens, and private keys are outside the ledger. Provider implementations are expected to resolve credential references only in their runtime backend.

The durable operator states are waiting_for_credentials, waiting_for_provider_processing, recoverable_unknown, published, and failed_terminal.

## At-most-one logical publish

The stable Creator publish idempotency key is content-addressed from the exact destination and release binding. A provider is accepted only if prepare proves both idempotent submit and authoritative recovery.

If Creator restarts before a provider handle is durable, it calls recover with the same idempotency key before it can submit. An authoritative absent result permits submit. A non-authoritative or unknown recovery produces recoverable_unknown and forbids blind replay.

The deterministic crash test injects a process crash after the mock provider has accepted the logical side effect but before Creator records the handle. On restart, recovery discovers the existing operation and Creator never submits again. The test asserts one accepted effect and one submit call.

## Asynchronous phases

The capability contract requires the phase plan:

create_or_upload_session -> provider_processing -> publish_commit -> terminal_receipt

The adapter may implement provider-specific container, upload session, processing, and commit details internally, but all phases remain under one Creator idempotency key and a recoverable provider operation identity.

A terminal creator.publish_provider_receipt.v2 binds the exact Media content SHA, manifest digest, platform, account, destination, caption, CTA, release authorization ID/digest/expiry, authorization lineage, provider operation, post identity, and timestamps.

## Capability and credential gates

prepare runs before recover or submit. Missing credential authorization produces waiting_for_credentials with zero provider side effects. Unsupported account/media combinations produce failed_terminal before recover or submit.

The conformance baseline keeps Creator's canonical short-form media profile: video/mp4, 9:16, 15-60 seconds. Production adapters may add narrower provider/account gates, but may not silently weaken these Creator constraints.

## Growth evidence boundary

build_growth_handoff first validates the complete provider receipt against the original publish request. Live-performance-claim eligibility is true only when both the receipt source is provider_receipt and the Media source is provider. Synthetic conformance receipts always produce synthetic_fixture handoff evidence with livePerformanceClaimEligible=false.

## CI and fixtures

fixtures/publish_provider_r12_conformance.json contains synthetic-only fixtures for instagram_reels, tiktok, and youtube_shorts. Their media sourceClass is synthetic_fixture, so they cannot pass the normal live Media gate unless conformance mode is explicitly enabled.

tests/test_publish_providers_r12.py proves all three adapters, asynchronous processing, credentials waiting, capability rejection before side effect, authorization expiry, receipt tamper rejection, secret non-persistence, recoverable unknown behavior, synthetic Growth ineligibility, and crash/lost-ack recovery with no duplicate submit.

No test performs network I/O or live publishing.
