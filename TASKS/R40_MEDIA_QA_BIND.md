# Creator R40 — bind accepted Media R27 QA

Writable branch: agent/creator-r40-media-qa-bind-20261007
Exact start: 69b4cb17ba81e79b15583fbbf64c0b6e9de51c0e

Accepted Media QA certificate source:
foto6/boss@06ade2b1e8d40c4ab6559f3ffe1d69b0ee36fd78
hardwave_qa/certificates/creator.media_r27_independent_qa.r39.v1.json

Certificate accepts Media:
183838a24205c6885b2366ad6ffa394164283d91 / CI 37451069045 / artifact 11406357346 / digest sha256:9cfa2ddd358f2b25a3066ee60792c44c460c62715590210bacf5c5430d14a4b5

Goal: consume the exact independent QA tuple and move Creator from WAITING_MEDIA_R27_QA to the strongest justified local-rehearsal-ready state without authorizing publish.

Required:
- bind exact QA producer SHA/CI/artifact/matrix digest;
- reject stale/mismatched/fixture-only certificates;
- keep current-authority binder fail-closed;
- refresh Bridge authority to current accepted successor only after exact evidence exists; no moving refs;
- exact-head CI + deterministic readiness artifact;
- no provider/browser/live-publish effects.

Return exact SHA/CI/artifact and final readiness state.