# Creator R16 Media R13 production pin and real cross-repo acceptance

R16 promotes Media compatibility from the failed R12 candidate state to the exact green Media R13 Creator-consumer contract without enabling publishing.

## Exact producer

Media source is pinned to \`foto6/video2@ad4e0ba487a3cabc84dd339d412e19a0db0f9add\` on \`agent/media-r13-creator-compat-20261001\`, exact-head CI run \`36801556474\` SUCCESS.

Creator consumes \`media.creator_consumer_compat.r13.v1\` directly. Exact source contract and schema bytes are vendored into Creator and retain the same Git blob IDs as Media. No Media runtime module is imported.

## CI artifact proof

Media run \`36801556474\` uploaded artifact \`media-r13-compat\` (artifact ID \`11136028209\`). Creator pins the exact emitted bundle bytes:

- compatibility bundle SHA-256: \`e5f45429604519e2776fddeedb11032baae2728799aebfff2f6f1076686eeb7f\`
- demo consumer envelope SHA-256: \`e7ee654f3a3b098f32d7611ff721e506eb26caffe44d1a77aa25f077be94541c\`
- Media bundle digest: \`e3b412095c1f645263d9b1571f600f90fc1e092b0b241c056d7e2e1176748d06\`

The Creator reproduction command deterministically re-emits the same canonical JSON bytes and re-ingests them through the exact pinned contract.

## Fail-closed acceptance

Creator rejects changed producer SHA, changed Git blob IDs, changed schema fields, failed technical QA, failed creative guardrails, digest drift, and invalid source-provenance evidence. Regression coverage explicitly rejects the old failed Media R12 SHA \`98f298b88faaef106fb412712d6c9824e2b926d9\`.

## R15 interaction

The real artifact contains one producer-generated compatibility envelope, so R16 persists exactly one real R15 candidate. It passes technical and creative hard gates, but the tournament decision remains \`insufficient_evidence\` because one envelope cannot establish a comparative multi-candidate heuristic preference. No extra real render or score is invented.

The existing four-candidate R15 synthetic fixture remains conformance-only and independently proves bounded tournament breadth, rejection logic, deterministic selection and lost-ack recovery.

## Publishing boundary

Live publishing remains disabled. R16 introduces no credentials and does not bypass \`release.authorization.v1\` or the R12 publish-provider safety/recovery layer.

## Commands

\`\`\`bash
PYTHONPATH=src python -m creator_orchestrator.candidate_tournament readiness
PYTHONPATH=src python -m creator_orchestrator.candidate_tournament real-r13 --work-dir /tmp/creator-r16-media-r13
PYTHONPATH=src python -m creator_orchestrator.candidate_tournament replay --work-dir /tmp/creator-r15-tournament
\`\`\`
