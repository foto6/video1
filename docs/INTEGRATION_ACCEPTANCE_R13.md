# Creator R13 integration acceptance

R13 remains the durable end-to-end acceptance layer over Creator R11 orchestration, R12 publish recovery, Growth ingestion and restart-safe cross-repo boundaries. R16 does not weaken or replace those contracts.

## Readiness after Media R13

The original R13 synthetic harness was written while Media R11/R12 production compatibility was unresolved. Its historical \`BLOCKED_MEDIA\` evidence described that earlier state and must not be interpreted as the current production Media pin.

Creator R16 now consumes the official \`media.creator_consumer_compat.r13.v1\` contract from exact producer:

- repository: \`foto6/video2\`
- branch: \`agent/media-r13-creator-compat-20261001\`
- producer SHA: \`ad4e0ba487a3cabc84dd339d412e19a0db0f9add\`
- exact-head CI: \`36801556474\` — SUCCESS
- compatibility contract blob: \`ecfeaed347b53ed549124b9d1701ebf70b37eea3\`
- result-envelope schema blob: \`119b26b494df77c4ce8d83ffd63791afc112d264\`
- technical-QA schema blob: \`1b2f71e443b0038736e8be99f544493965693658\`
- creative-quality schema blob: \`c63f95b45f5440aabd8c14dc5fcb8eeae1fc8535\`

The exact Media CI artifact \`media-r13-compat\` is pinned by workflow artifact ID \`11136028209\`, bundle SHA-256 \`e5f45429604519e2776fddeedb11032baae2728799aebfff2f6f1076686eeb7f\`, and demo-envelope SHA-256 \`e7ee654f3a3b098f32d7611ff721e506eb26caffe44d1a77aa25f077be94541c\`.

That real compatibility path is now **READY_MEDIA_R13**. It is distinct from R13's older synthetic three-platform lifecycle harness.

## Three separate evidence classes

**Real Media R13 compatibility:** Creator validates the exact producer SHA, every pinned Git blob, the compatibility manifest/contract, the three consumer schemas, the producer-emitted bundle digest, technical QA, creative guardrails and source provenance. No synthetic substitution is used.

**Synthetic end-to-end breadth:** R13's deterministic Instagram/TikTok/YouTube integration harness remains useful for crash/replay, provider and Growth boundary breadth. Synthetic evidence remains explicitly conformance-only and cannot make live-performance claims.

**Live publishing:** still disabled. Media compatibility does not authorize release or publication. Existing \`release.authorization.v1\`, R12 provider capability/recovery gates and credential boundaries remain unchanged.

## Fail-closed rule

A changed producer SHA, changed pinned blob, unknown schema field, failed technical QA, failed creative guardrail, digest mismatch or source-provenance failure is rejected. The old failed Media R12 SHA \`98f298b88faaef106fb412712d6c9824e2b926d9\` remains invalid.

## Commands

Validate the current production Media pin:

\`\`\`bash
PYTHONPATH=src python -m creator_orchestrator.candidate_tournament readiness
\`\`\`

Run the source-bound real Media R13 roundtrip:

\`\`\`bash
PYTHONPATH=src python -m creator_orchestrator.candidate_tournament real-r13 --work-dir /tmp/creator-r16-media-r13
\`\`\`

The command re-emits the exact producer CI bundle/envelope bytes, ingests them through Creator's pinned compatibility consumer and R15 tournament acceptance, and creates no live publish action.
