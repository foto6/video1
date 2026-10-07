# Creator R40 — Media R27 independent-QA bind

R40 consumes the exact standalone Creator certificate materialized in `foto6/boss@06ade2b1e8d40c4ab6559f3ffe1d69b0ee36fd78` and advances the R39 Media gate without weakening any live-effect boundary.

## Exact independent QA

The pinned certificate is `creator.media_r27_independent_qa.r39.v1` and binds:

- QA producer: `foto6/boss@6ab529846e99e572d77006dee48d6c4b01caea12`
- QA CI: `37452884976 SUCCESS`
- QA artifact: `11407720740`
- QA artifact digest: `sha256:910326676dd9371745cb70099ec3db76a21ad7f0d5e171bcd59bddfa091bd7d8`
- source acceptance matrix SHA-256: `831804bedce4652156ac052e1c50f1e6f3642cd36dadbc58a00907804e646a54`
- certificate refresh source commit: `06ade2b1e8d40c4ab6559f3ffe1d69b0ee36fd78`
- certificate Git blob: `93a0713048ad4a8fe04cea5a1c9dbbec154fcefb`
- certificate raw SHA-256: `1e0d788ff59814eac1482d03c8f1934d48c08358ae5835413793c961aa361f1d`

It accepts exactly Media R27 `183838a24205c6885b2366ad6ffa394164283d91`, CI `37451069045 SUCCESS`, artifact `11406357346`, digest `sha256:9cfa2ddd358f2b25a3066ee60792c44c460c62715590210bacf5c5430d14a4b5`, contract `media.real_input_local_rehearsal.r27.v1`, and Growth bundle `media.real_input_growth_bundle.r27.v1`. The certificate is explicitly `fixtureOnly=false`.

R40 rejects any stale QA producer tuple, changed matrix digest, changed Media tuple, extra/moving-ref authority field, or fixture-only certificate.

## Bridge successor gate

R40 rechecked Bridge rather than treating a moving branch as authority. R43 source `46dc74dd65bae303ecda1236e52680f7532b0912` has dedicated exact-head CI `37644197933 SUCCESS` and Ubuntu/Windows artifacts, but its own readiness is only `EXACT_HEAD_READY_FOR_CONTROLLED_PREFLIGHT`.

No exact accepted controlled preflight, controlled cutover, and Projects-reconcile evidence at that SHA is present. Therefore R40 does **not** promote R43 to current accepted control-plane authority. The selected Bridge authority remains accepted R42 `a6adf698764776856567239b07b0687e8ac89fa5`. This is fail-closed and does not authorize a Bridge cutover.

## Readiness

With the exact Media QA certificate bound, the inherited R39 current-authority binder validates as `SOURCE_READY`. R40 therefore reports:

`SOURCE_READY`

This means Creator's local-rehearsal source/authority gate is ready. It is not an overall stack GO, does not claim that the real local-PC rehearsal ran, and does not authorize publish.

The deterministic CI fixture exercises the full R39 bind using the real QA certificate and synthetic media bundle bytes only. It terminates `LOCAL_REHEARSAL_COMPLETE / LIVE_AUTHORIZATION_FALSE`.

## Commands

```text
creator-media-qa-bind-r40 readiness
creator-media-qa-bind-r40 validate-certificate --certificate conformance/creator.media_qa_bind.r40.v1/source/creator.media_r27_independent_qa.r39.v1.json
creator-media-qa-bind-r40 fixture --workspace .r40-fixture
creator-media-qa-bind-r40 status --workspace .r40-fixture
creator-media-qa-bind-r40 evidence --out .r40-evidence
```

No provider mutation, browser mutation, live Bridge cutover, credential access, social publish, merge, or live authorization is performed.
