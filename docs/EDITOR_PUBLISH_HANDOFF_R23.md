# Creator R23 editor-to-publish handoff

R23 bridges a terminal R22 editor result into the existing R21/R12 durable publish-provider path. It does not change R22 editing decisions or R21 provider semantics and does not perform a real social post.

## Contract

`creator.editor_publish_handoff.v1` binds:

- exact source ID/SHA and R22 loop identity;
- R22 bundle digest and winner decision digest;
- winning candidate ID and final render SHA;
- Media timeline/artifact-manifest/technical-QA digests;
- exact `release.authorization.v1`;
- target platform/account/destination plus opaque credential and authorization references;
- exact R12 `creator.publish_request.v1`.

The canonical schema is at `conformance/creator.editor_publish_handoff.v1/schema.json`.

## Eligibility gate

Only `creator.autonomous_edit_final_bundle.r22.v1` with:

- `state=final_bundle`;
- `decision.state=winner`;
- matching winner candidate ID;
- `humanReviewRequired=false`;
- passing Media technical QA;
- no Growth hard-failure observations;

may proceed.

Tie, insufficient evidence, human-review outcomes, human-review-required outcomes, and objective render failures fail closed before publish intent.

## Artifact lineage

The local canonical artifact must be named `final.mp4`. Its bytes are ffprobed and SHA-256 hashed. The hash must exactly equal the terminal R22 winning render SHA. The publish request carries the same SHA and exact R22 artifact-manifest digest.

A stale, wrong-candidate, or modified MP4 cannot enter the provider path.

Release authorization is additionally required to bind:

- `candidateId` to the R22 winner;
- `artifactId/artifactHash` to the exact final MP4;
- `lineageHash` to `sha256:<R22 bundleDigest>`;
- provider/destination scope to the requested target.

## Durable intent and recovery

R23 writes `publish_intent_committed` to `creator.editor_publish_handoff_ledger.v1` before invoking the R12 coordinator.

R12 then preserves its existing semantics:

`prepare -> authoritative recover -> submit only when absent -> status -> receipt`.

Lost acknowledgement after an accepted provider effect therefore recovers by existing R12 idempotency/recovery rather than blindly resubmitting.

R23 persists only opaque credential/authorization references. Tokens, cookies, passwords, Authorization headers and refresh tokens are rejected from durable payloads.

## One-command synthetic E2E

```bash
creator-editor-publish-r23 \
  --media ./final.mp4 \
  --editor-bundle ./terminal-result.json \
  --authorization ./release.authorization.v1.json \
  --platform tiktok \
  --account-id account-r23 \
  --destination privacy:SELF_ONLY \
  --credential-ref vault-ref://tiktok/r23 \
  --authorization-ref oauth-grant-ref://tiktok/r23 \
  --caption "R23 synthetic handoff" \
  --cta "Learn more" \
  --out ./r23-out
```

This command uses only the existing R12 synthetic provider implementation. It writes:

- `editor-publish-handoff.json`
- `editor-publish-ledger.jsonl`
- `publish-ledger.jsonl`
- `provider-receipt.json`
- `growth-handoff.json`
- `handoff-report.json`

The Growth handoff remains `synthetic_fixture` and `livePerformanceClaimEligible=false`.

## Fault coverage

Focused tests cover:

- noneligible R22 terminal states;
- stale/wrong final MP4 SHA;
- release-authorization winner/lineage mismatch;
- target account/request mismatch;
- durable intent before side effect;
- lost ACK with restart/recovery and one logical provider effect;
- duplicate handoff/idempotent event replay;
- provider timeout/recoverable-unknown;
- authorization-required stop before mutation;
- blocked/account mismatch before submit;
- real generated MP4 synthetic E2E.

No CAPTCHA/2FA bypass exists. R23 never performs a live provider mutation.
