# Creator R15 multi-candidate edit tournament

R15 provides the bounded edit tournament above the green R14 batch runner. R16 replaces R15's historical failed Media R12 production candidate with the official green Media R13 Creator-consumer compatibility bundle; R15's synthetic multi-candidate breadth remains conformance-only.

## Production Media pin

Production Media compatibility is now **READY_MEDIA_R13** only for this exact bundle:

- \`foto6/video2\` branch \`agent/media-r13-creator-compat-20261001\`
- producer SHA \`ad4e0ba487a3cabc84dd339d412e19a0db0f9add\`
- CI run \`36801556474\` — SUCCESS
- \`media.job.v1\` consumer manifest blob \`96b252acae743f8fe059fd634ee320f92bd9c79c\`
- \`media.artifact_manifest.v1\` manifest blob \`42aed1ca4720cddd4a5e48af076bc73b663322b0\`
- creative-plan manifest blob \`d031a07f1d392c690942bd5f8288a1713f1af791\`
- creative-plan contract blob \`5298aeb2a9e4e13ed31b1610ce88778b7a911592\`
- shortform editor manifest blob \`07c38a048d23490b8e55924697650e9969bf089f\`
- shortform profile blob \`d8f19d9a9d117c5736238159bd5e6d2491370986\`
- compatibility contract blob \`ecfeaed347b53ed549124b9d1701ebf70b37eea3\`
- result-envelope schema blob \`119b26b494df77c4ce8d83ffd63791afc112d264\`
- technical-QA schema blob \`1b2f71e443b0038736e8be99f544493965693658\`
- creative-quality schema blob \`c63f95b45f5440aabd8c14dc5fcb8eeae1fc8535\`

Creator vendors exact byte-for-byte copies of the compatibility contract/schema bundle and verifies their Git blob identities itself. It does not import Media runtime implementation.

The old failed SHA \`98f298b88faaef106fb412712d6c9824e2b926d9\` remains explicitly rejected.

## Real compatibility versus synthetic tournament breadth

The Media R13 workflow produced one real source-bound demo consumer envelope. R16 accepts exactly that one real envelope. It does **not** duplicate it into four supposed real variants.

The real envelope proves:

- exact producer and contract bundle;
- source asset provenance;
- technical QA pass;
- creative-quality pass;
- every exported creative guardrail pass;
- exact render, timeline, artifact-manifest and content digests.

Because one real demo envelope does not contain comparative R15 creative-preference signals for multiple real variants, R15 records the real candidate as hard-gate-passing but \`insufficient_evidence\` for automatic tournament winner selection. This is intentional: no heuristic quality certainty is fabricated.

R15's four-candidate deterministic fixture remains a separate **synthetic conformance** test. It still proves one technical rejection, one over-editing rejection, two valid synthetic candidates, deterministic winner selection and lost-ack recovery.

## Tournament safety

Technical QA and Media creative guardrails remain objective hard gates. Heuristic creative scoring occurs only for candidates with explicit source-bound comparative evidence and always sets \`qualityCertaintyClaimed=false\`.

Tie and insufficient-evidence decisions select no artifact automatically. Human override remains provenance-bound and cannot bypass technical or creative hard gates.

R14 campaign budget and concurrency accounting still wrap tournament breadth. Release authorization remains mandatory before R12 publication.

## Live publishing

Live publishing remains disabled. Media production compatibility is not publish authorization. No credentials are stored or used by R16.

## Commands

Exact production Media readiness:

\`\`\`bash
PYTHONPATH=src python -m creator_orchestrator.candidate_tournament readiness
\`\`\`

Real Media R13 cross-repo acceptance:

\`\`\`bash
PYTHONPATH=src python -m creator_orchestrator.candidate_tournament real-r13 --work-dir /tmp/creator-r16-media-r13
\`\`\`

Synthetic four-candidate tournament breadth:

\`\`\`bash
PYTHONPATH=src python -m creator_orchestrator.candidate_tournament replay --work-dir /tmp/creator-r15-tournament
\`\`\`
