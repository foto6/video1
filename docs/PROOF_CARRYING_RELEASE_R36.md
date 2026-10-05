# Creator R36 proof-carrying release rehearsal

R36 defines `creator.proof_carrying_release_rehearsal.r36.v1`. It is a deterministic, independently verifiable rehearsal bundle above accepted Creator R35. It does not publish, call a provider, access credentials, or mutate a browser/account.

## Immutable accepted authority envelope

The bundle freezes only the QA-R6 accepted authorities:

- Creator R35 `4793b7cb1735d21db6d211244018591b80c329a4`, CI `37244869884 SUCCESS`, artifact `11318269083`, digest `sha256:06753496d0d9cbe94d8b8a5218b10f5b38fa7455d98c89684374c6ba92965e0e`, contract `creator.release_escrow_canary.r35.v1`.
- Growth R34 `9ff243bc5ec6977bc5f0eb8f16cd5e51aa0dcdfc`, CI `37244660304 SUCCESS`, artifact `11318054384`, digest `sha256:6fc329964c14ce7c11f27fd2dd47235912470a377c6a1f5a6f3e66f4481f5ac9`, contract `growth.counterfactual_policy_promotion.r34.v1`. It remains advisory-only.
- Bridge R38 `f4f6070a975ac2c5bd8323777db1514c4733e427`, CI `37244988343 SUCCESS`; Ubuntu artifact `11318149497 / sha256:aaca65ba7f3beaa9f7cb393325a7f44872b5874fe6881c586dab7c56e79bdbe4`; Windows artifact `11318049994 / sha256:384c0cdcc6759541953d415dab0ad96dffdef48bd467017b9ea5a6047615da85`; contract `bridge.agent_dag_orchestrator.r38.v1`.
- independent QA R6 `foto6/boss@aa415759795beb24f1333d190ff842451020be5f`, CI `37245738748 SUCCESS`, artifact `11318958558`, digest `sha256:5f2132293ecede7aa44bcf869fba42cd441454e778c361c3f49789cd7814fb8a`.

QA R6 accepted Creator R35, Growth R34 and Bridge R38. Media R25 was explicitly `WAITING_EXACT_GREEN` at the immutable QA cutoff. R36 therefore records Media R25 as **UNACCEPTED / NOT_CONSUMED**. Later branch movement is not authority.

## Content-addressed proof graph

Every generated bundle has exactly this chain:

`INTENT_FROZEN -> AUTHORITY_VERIFIED -> ESCROW_REHEARSED -> CANARY_REHEARSED -> CANARY_RECONCILED -> EXPANSION_REHEARSED -> FINAL_REHEARSAL_VERDICT`.

Each node hashes its evidence and predecessor. The final bundle hashes the authority envelope, intent, graph and fake-provider journal. `verify_bundle()` independently recomputes all authority tuples, journal hashes, graph hashes and the final bundle digest.

The canary rehearsal deliberately records a fake unknown outcome followed by read-only reconciliation. The graph proves `blindRetry=false`; no provider effect is produced.

## Fake-provider journal only

The journal is evidence of a simulated control path. Every entry carries:

- `providerEffects=0`
- `networkEffects=0`
- `liveAuthorization=false`

No real provider operation ID, credential, post, browser mutation or account mutation is created.

## Adversarial rehearsal

R36 executes 40 deterministic tamper cases covering accepted-authority drift, QA drift, accidental Media R25 consumption, graph reordering/digest tamper, journal chain/effect tamper, unknown-effect retry, render/platform intent drift, bundle digest drift and false LIVE_READY verdicts. Every mutation must be rejected by the independent verifier.

Run:

```bash
creator-proof-release-r36 readiness
creator-proof-release-r36 rehearsal --out .r36-rehearsal
creator-proof-release-r36 verify --bundle .r36-rehearsal/proof-bundle.r36.json
creator-proof-release-r36 status --bundle .r36-rehearsal/proof-bundle.r36.json
```

Final disposition is always `SOURCE_READY_NO_LIVE_PROVIDER`.
