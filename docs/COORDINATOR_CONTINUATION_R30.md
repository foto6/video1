# Creator R30 coordinator E2E continuation loop

R30 is the coordinator-facing continuation boundary after Growth R27 has ingested one genuine Bridge R31/R30 live review. It does not perform browser or social-provider mutation.

## Exact authorities

- Media R22: `foto6/video2@e82a7ac04f3758d0e3e21ea3d05265dbc2822132`, CI `37001071721 SUCCESS`.
- Growth R27: `foto6/video3@d80592ad660b7b73ad13298880918a5944411c38`, CI `37002456031 SUCCESS`, authority-profile digest `57ab464f85ba95f1ca4dfefeaeb0a19371ce7d666ca8142daeb86e3162d2c634`.
- Bridge R31: `foto6/WebAIBridge@104281e49122233f251c692abba726ae31cee0d5`, CI `36999908386 SUCCESS`.

Media R22 consumes an exact Media R21 round directory, so R30 also verifies the R22-pinned R21 producer `d753e9e4c1f4448386608a1425232dbc1dba87ea`. Moving branches are never authority.

## Continuation command

```bash
creator-coordinator-r30 continue \
  --media-r22-checkout /exact/video2-r22 \
  --media-r21-checkout /exact/video2-r21 \
  --growth-r27-checkout /exact/video3-r27 \
  --bridge-r31-checkout /exact/WebAIBridge-r31 \
  --candidate-root /work/candidate \
  --candidate-context /work/candidate-context.json \
  --growth-index /growth/growth.dynamic_live_review_ingest_index.r27.v1.json \
  --growth-envelope /growth/creator-dynamic-review-....json \
  --out /work/continuation
```

For a terminal winner, add `--release-authorization` and `--publish-target`. The publish handoff is materialized only; no provider submit occurs.

## Durable sequence

The R30 journal persists immutable authorities, Growth R27 capture/index identity, selected Creator envelope and candidate lineage, Media re-edit effect, R21 next-round package identity, R22 materialized operator-package identity, and terminal outcome. Exact replay is idempotent; changed response/index/envelope bytes for an existing round conflict.

Review rounds are limited to 0, 1 and 2. Targeted re-edit at round 2 is rejected, enforcing at most two edit effects.

Successful targeted re-edit records `REVIEW_ACCEPTED -> REAL_REEDIT_EXECUTED -> NEXT_REVIEW_PACKAGE_READY`. Tie, insufficient evidence and human review emit `NON_PUBLISHABLE_REVIEW_RESULT`. Only winner can emit `WINNER_HANDOFF_READY`.

## Real-MP4 rehearsal

```bash
creator-coordinator-r30 rehearsal --out .r30-rehearsal
```

The rehearsal creates and probes a real vertical MP4, then stops at `WAITING_GENUINE_CAPTURE`. It fabricates no model judgment.

No browser/provider mutation, credentials, CAPTCHA/2FA handling, human-ground-truth label, human-parity claim, or merge is part of R30.
