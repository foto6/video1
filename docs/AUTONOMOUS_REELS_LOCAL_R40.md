# Creator R40 — autonomous local Reels closure

This companion layer addresses the evidence gap left by the source-green R40 Media-QA binder. CI run 37647880405 and artifact 11495710902 prove control-plane behavior only; they do **not** prove a user-local real montage or a social publish.

## Exact authority audit

Media R27 is independently accepted:

- Media: `183838a24205c6885b2366ad6ffa394164283d91`
- CI: `37451069045 SUCCESS`
- artifact: `11406357346`
- artifact digest: `sha256:9cfa2ddd358f2b25a3066ee60792c44c460c62715590210bacf5c5430d14a4b5`
- QA signer: `foto6/boss@6ab529846e99e572d77006dee48d6c4b01caea12`
- QA CI/artifact: `37452884976 SUCCESS / 11407720740`
- matrix digest: `831804bedce4652156ac052e1c50f1e6f3642cd36dadbc58a00907804e646a54`

Growth R39 exact observed SHA `887567bb62a3df0879505d68ac6a2be725b57173` is **not** accepted as an R39 implementation. Comparing it to parent `608ec634d9f38ecf054ccd63ba6e7f3a1cd79cae` shows exactly one changed file: `TASKS/R39_MEDIA_QA_BIND.md`. Its run `37645554562` is green but uploads inherited R38-and-earlier artifacts and no Growth R39 successor artifact. Creator therefore fails closed before autonomous real quality review.

Bridge R44 current head `004bca97fe0db5c3cbba9d086f5000345af4e843` has exact-head CI `37647792789 SUCCESS` and Ubuntu/Windows artifacts `11493954827` and `11495056376`. Its own readiness is `EXACT_HEAD_READY_FOR_NEW_LOCAL_PREFLIGHT`; local preflight/cutover acceptance is still a separate required operation and Creator does not authorize it.

Boss Integration R9 current observed SHA `9f439b41c2b11640451a803cee8b8d6198ddd04b` is likewise task-pointer-only over `06ade2b1e8d40c4ab6559f3ffe1d69b0ee36fd78`; no R9 CI/GO disposition exists.

## What the new runner does

`creator-autonomous-reels-local-r40` is Windows-first and fail-closed. A real run:

1. validates the non-fixture accepted Media R27 QA certificate;
2. requires an exact accepted Growth R39 authority envelope before heavy rendering;
3. verifies the Media checkout is exactly R27 SHA and exact command/runtime blobs, with no tracked dirtiness;
4. runs `RUN_LOCAL_R27.cmd` and `VERIFY_LOCAL_R27.cmd` on the supplied source;
5. independently rehashes the source plus all four distinct real candidate MP4s;
6. consumes real-local review envelopes bound to the exact Growth authority and Media bundle;
7. executes Media R19 targeted re-edit requests, allowing at most two re-edit rounds;
8. copies the selected bytes to `final/final.mp4`;
9. seals a release escrow over source/final/review/authority hashes;
10. prepares a deterministic transaction ID/idempotency key for Reels/TikTok/Shorts.

There is deliberately no live Send implementation. Even with a human approval file and future Boss R9 GO, this milestone only prepares transaction readiness; provider/network mutation remains false.

## Commands

Current diagnostic:

```bat
creator-autonomous-reels-local-r40 diagnose
```

CI-only deterministic fixture:

```bat
creator-autonomous-reels-local-r40 fixture --workspace .r40-reels-fixture
```

Future real local execution after an accepted Growth R39 authority exists:

```bat
tools\creator-autonomous-reels-local-r40.cmd run ^
  --source "E:\media\input.mp4" ^
  --workspace "E:\media\creator-r40-reels" ^
  --media-root "E:\worktrees\video2-r27" ^
  --growth-authority "E:\evidence\growth-r39-authority.json" ^
  --review-dir "E:\evidence\growth-reviews" ^
  --platform instagram_reels ^
  --account-ref "my-account" ^
  --destination "profile:my-account"
```

The expected review files are `round-0.json`, then only if requested `round-1.json` and `round-2.json`. A third re-edit is rejected.

Successful real execution writes `evidence/real-input-output-receipt.r40.json`. Absence of that receipt must be reported as absence of real local E2E evidence.

## Current minimum blocker

The authorized Windows Desktop Commander device was offline during this implementation session, so no real local input could be rendered here. More importantly, autonomous quality review is independently blocked by the pointer-only Growth R39 head. Boss R9 GO is also absent. These are explicit blockers rather than inferred success.

No drafts or source material are deleted. The runner issues no reset, force checkout, stash, provider Send, browser mutation, or social publish.
