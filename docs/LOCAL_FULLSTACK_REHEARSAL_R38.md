# Creator R38 local full-stack rehearsal driver

R38 defines creator.local_fullstack_rehearsal.r38.v1. It packages the accepted Creator control plane into a Windows-first one-command local rehearsal coordinator while remaining fail-closed until an exact, independently accepted Media R26 authority tuple exists.

## Frozen authorities

- Creator R37: foto6/video1@1f7cb9ed8f1985cd4faca79ce55f1c5fda9e3a57, CI 37398299900 SUCCESS, contract creator.local_integration_driver.r37.v1.
- Growth R36: foto6/video3@a53f9deb180bb256d193f0422c6ffd7a5923d97a, CI 37398558145 SUCCESS, artifact 11383953328, digest sha256:89e719718b5480ad889190a09c837efdfff31a15ea899f1e836ddb9d033f0894, contract growth.local_rehearsal_evidence.r36.v1.
- Bridge R40: foto6/WebAIBridge@9fca5e7e4cdc820a1a3aee6ada9102fc97649d16, CI 37399009019 SUCCESS, Ubuntu artifact 11384052747 / sha256:324183d5f94f2794f5391c472484e81952293555f0189544d7deb13db6402c0e, Windows artifact 11384304238 / sha256:6c18e7220aecb59b4b249fdb34b0c644a9ff0e950f82973e6d844c0867fb9709, contract bridge.operator_lifecycle.r40.v1.
- Media R26 is required but currently unaccepted. R38 contains no R25 fallback.

Current readiness: WAITING_MEDIA_AUTHORITY.

## Windows-first usage

Run tools\creator-local-fullstack-r38.cmd readiness for the gate. After independent Media R26 acceptance, run the same launcher with: run --source <source.mp4> --brief <brief> --workspace <workspace> --media-authority <accepted-media.json> --media-root <video2-checkout>.

dry-run and status never perform render/provider/browser side effects. The PowerShell runner sets CREATOR_R38_NO_NETWORK=1 and CREATOR_R38_LIVE_AUTHORIZATION=0 before invoking Python.

## Offline review boundary

If --review-input is omitted, R38 emits an explicit OFFLINE_FAKE_REVIEW package. Exact local review input is accepted only when candidate hashes bind generated candidates and providerEffects=0, networkEffects=0, liveAuthorization=false. Growth R36 is consumed as local advisory authority; the decision cannot authorize publish.

Bridge R40 is frozen into the authority envelope and final manifest. R38 never starts/cuts over Bridge or Chrome.

## Durable ledger and workspace

Every expensive stage writes STAGE_STARTED before work and STAGE_COMPLETED after hashing outputs: MEDIA_CANDIDATES, REVIEW_PACKAGE, GROWTH_DECISION, TARGETED_REEDIT, FINALIZE. Exact reruns reuse verified completed artifacts. Changed source, brief, authority, resources, or review input in the same workspace conflicts.

Layout: authorities/authority-envelope.r38.json; inputs/source-package.r38.json; ledger/identity.r38.json; ledger/stage-ledger.r38.jsonl; candidates/; review/review-package.r38.json; growth/growth-decision.r38.json; reedit/targeted-reedit.mp4; final/final.mp4; evidence/final-rehearsal-manifest.r38.json; evidence/status.r38.json; temp/.

The user source is not copied or deleted by Creator. Only its name, size, SHA-256 and brief digest are recorded.

## Resources and cleanup

Defaults are explicit: two CPU workers, GPU mode none, no CUDA assumption, 4096 MiB disk budget and temp/ under the workspace. Hosted CI uses tiny deterministic bytes only and never performs a heavy render.

cleanup removes only temp/ and .staging/. It preserves source material, authority evidence, ledger, candidates, review/decision evidence, targeted re-edit, final.mp4 and final manifest.

## Final evidence

Completed rehearsal seals exact hashes for source metadata, all candidates, Growth decision, targeted re-edit, selected winner, final.mp4, stage ledger and all parent authorities. Provider/network effects remain zero; live authorization, publish, credentials and live Bridge cutover remain false.

The CI-only synthetic Media tuple is marked fixtureOnly and is rejected by normal run readiness. It exists solely to validate orchestration with tiny hosted fixtures.
