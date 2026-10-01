# Creator R15 multi-candidate edit tournament

R15 adds a bounded edit tournament above the green R14 batch runner. It preserves the existing R11 orchestration, R12 publish-provider recovery, R13 producer gates, and R14 campaign budget/concurrency model.

The tournament contract is \`creator.candidate_tournament.r15.v1\`; durable events use \`creator.candidate_tournament_ledger.r15.v1\`.

## Current Media R12 production gate

Production tournament use is fail-closed.

Observed Media R12 candidate:

- repository: \`foto6/video2\`
- branch: \`agent/media-r12-creative-polish-20261001\`
- producer SHA: \`98f298b88faaef106fb412712d6c9824e2b926d9\`
- creative-plan manifest blob: \`d031a07f1d392c690942bd5f8288a1713f1af791\`
- creative-plan contract blob: \`5298aeb2a9e4e13ed31b1610ce88778b7a911592\`
- preserved R11 job-contract blob: \`96b252acae743f8fe059fd634ee320f92bd9c79c\`
- preserved R11 artifact-manifest blob: \`42aed1ca4720cddd4a5e48af076bc73b663322b0\`
- exact-head CI run: \`36799818187\` — **failure**
- Creator-consumer compatibility blob: **missing**

Therefore \`media_r12_readiness()\` returns \`BLOCKED_MEDIA_R12\`. R15 synthetic fixtures may bind the observed candidate for conformance evidence, but mark \`producerCompatibilityAccepted=false\` and \`sourceClass=synthetic_fixture\`. They cannot be used as production evidence.

A future production pin must include an exact producer SHA, creative-plan manifest blob, creative-plan contract blob, Creator-consumer compatibility blob, and successful exact-head CI.

## Tournament model

One creative item produces a configured number of unique candidate requests. The current bounded dimensions are:

- pacing preset;
- caption style;
- B-roll density;
- hook cut;
- punch-in/zoom pattern;
- loop ending;
- CTA treatment;
- music/voice balance.

\`TournamentConfig\` caps candidates at eight and requires the entire configured candidate set to fit both local render-seconds and Media-action budgets before execution. Media concurrency is separately capped.

Candidate identity is deterministic over tournament ID, creative-item digest, ordinal and complete variant specification.

## Objective hard gates vs creative preference

Selection is deliberately two-stage.

First, Media technical QA is a hard gate. A candidate with failed technical QA becomes \`rejected_technical\`; no creative preference score is computed.

Second, the Media R12 over-editing guardrails are objective hard gates. Current pinned limits are cut rate 1.25/s, zoom rate 0.30/s, transition density 0.20/s, text density 22 chars/s, music gain no higher than -10 dB, at most two concurrent text items, and motion zoom no higher than 1.18. Violations become \`rejected_guardrail\`, again without creative comparison.

Only remaining candidates with source-bound evidence receive a deterministic preference score. Signals include hook clarity, pacing coherence, caption legibility, source-evidence use, loop coherence, CTA clarity and audio balance. The result explicitly sets \`qualityCertaintyClaimed=false\` and describes the score as a source-bound heuristic preference, not objective creative quality.

## Tie, insufficient evidence and human override

If fewer than the configured minimum number of valid evidence-bearing candidates remain, the decision is \`insufficient_evidence\`.

If the top two heuristic preference scores are within the configured epsilon, the decision is \`tie\`.

Neither state selects an artifact automatically. An explicit human override can resolve a tie or insufficient-evidence state, or replace an automatic heuristic selection, while preserving:

- prior decision digest;
- actor reference;
- override reason;
- winner evaluation digest;
- final override decision digest.

An override cannot select a candidate that failed technical QA or an objective hard guardrail.

## Durability and lost acknowledgement

Every planned candidate, request identity, Media result, producer source, timeline digest, artifact-manifest digest, content digest, QA digest, creative-evidence digest, evaluation, rejection and decision is append-only and digest-bound.

Before a candidate submit, R15 durably reserves its local render/action budget and records a Media in-flight slot. Recovery checks the provider's idempotency key before submit. If Media accepted a candidate but Creator lost acknowledgement, restart recovers the existing result and never performs a second logical render.

Conflicting duplicate results fail closed.

Partial tournaments resume from their durable per-candidate state; completed candidates are not re-rendered.

## R14 campaign interaction

\`BatchCampaignRunner.run_tournament()\` delegates one selected batch item into R15 without bypassing R14 controls.

Before every tournament candidate, R14 reserves the candidate's estimated render seconds against the campaign budget and acquires a campaign Media concurrency slot. Candidate planning/evaluation also consumes deterministic campaign generation units.

This means four variants consume four bounded candidate render reservations instead of silently multiplying work outside R14 accounting. If the outer campaign budget cannot fit another candidate, R14 raises \`BudgetExceeded\` before that Media side effect.

When R15 selects a winner, R14 records the selected artifact plus complete tournament provenance as its Media result, adds source-bound tournament QA, and moves the item to \`awaiting_release\`. The existing R14 external \`release.authorization.v1\` flow remains mandatory before R12 publication.

## Deterministic four-candidate fixture

The replay contains four candidates:

1. technical QA failure — excluded before creative comparison;
2. technical QA pass but cut-rate over-editing violation — excluded before creative comparison;
3. valid source-bound candidate;
4. valid source-bound candidate with the higher deterministic preference score.

The fourth candidate is selected reproducibly. Its first Media acknowledgement is intentionally lost after the synthetic side effect; restart recovers it by idempotency key. The fixture proves four logical Media effects and four submits, not five.

## Commands

Current Media R12 production readiness:

\`\`\`bash
PYTHONPATH=src python -m creator_orchestrator.candidate_tournament readiness
\`\`\`

This intentionally exits non-zero while the production pin is blocked.

Deterministic synthetic replay:

\`\`\`bash
PYTHONPATH=src python -m creator_orchestrator.candidate_tournament replay --work-dir /tmp/creator-r15-tournament
\`\`\`

No command performs live publishing or uses provider credentials.
