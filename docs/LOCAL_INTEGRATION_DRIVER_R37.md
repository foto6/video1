# Creator R37 local integration driver

R37 adds `creator.local_integration_driver.r37.v1`, a coordinator-facing local integration driver with a deterministic fixture rehearsal and a fail-closed boundary for the actual local Media/Growth/Bridge loop.

## Exact authorities

R37 freezes and verifies the accepted read-only authorities already carried by R36:

- Growth R34: `foto6/video3@9ff243bc5ec6977bc5f0eb8f16cd5e51aa0dcdfc`, CI `37244660304`, artifact `11318054384`, digest `sha256:6fc329964c14ce7c11f27fd2dd47235912470a377c6a1f5a6f3e66f4481f5ac9`.
- Bridge R38: `foto6/WebAIBridge@f4f6070a975ac2c5bd8323777db1514c4733e427`, CI `37244988343`, with Ubuntu artifact `11318149497` / `sha256:aaca65ba7f3beaa9f7cb393325a7f44872b5874fe6881c586dab7c56e79bdbe4` and Windows artifact `11318049994` / `sha256:384c0cdcc6759541953d415dab0ad96dffdef48bd467017b9ea5a6047615da85`.
- QA R6: `foto6/boss@aa415759795beb24f1333d190ff842451020be5f`, CI `37245738748`, artifact `11318958558`, digest `sha256:5f2132293ecede7aa44bcf869fba42cd441454e778c361c3f49789cd7814fb8a`.

QA R6 accepts Growth R34 and Bridge R38 but records Media R25 as `WAITING_EXACT_GREEN`.

## Media is required and currently unaccepted

Media is not optional. The frozen evidence is:

- repo `foto6/video2`
- expected contract `media.multicandidate_round.r25.v1`
- status `UNACCEPTED`
- consumption `NOT_CONSUMED`
- QA R6 cutoff SHA `7ef00d9eec4b125f5ee7bcd28fc47cd390d82d86`
- cutoff CI `37245663074` with recorded status `queued`
- disposition `WAITING_EXACT_GREEN`

The real `run` command exits nonzero until an independently accepted Media authority JSON is supplied. That JSON must bind an exact producer SHA/CI/artifact/digest/blob set and an independent QA tuple whose accepted producer values match byte-for-byte. Moving branch names are never sufficient authority.

R37 does **not** claim an actual local-PC end-to-end execution in this milestone.

## Deterministic fixture closed loop

The fixture rehearsal executes, without network/provider/browser mutation:

`source -> 3 candidate identities -> Growth/Bridge-bound fixture review -> targeted re-edit -> winner -> Creator content-addressed proof graph -> R35 release-escrow fixture -> LOCAL_REHEARSAL_COMPLETE`

The proof graph also independently verifies the existing R36 proof bundle before binding the R37 winner.

Final fixture disposition is exactly:

`LOCAL_REHEARSAL_COMPLETE / LIVE_AUTHORIZATION_FALSE`

Provider effects and network effects remain zero.

## Durable restart ledger

`local-integration-ledger.r37.jsonl` is append-only and hash-chained. Every durable event binds the previous/new state digest and request digest. Reopening the driver after completion and replaying the same operation adds no event. Changed source, brief, authority, or event payload conflicts fail closed.

## Commands

Linux/macOS:

```bash
creator-local-integration-r37 readiness
creator-local-integration-r37 fixture-rehearsal --out .r37-fixture
creator-local-integration-r37 evidence --out .r37-evidence
creator-local-integration-r37 run --source input.mp4 --brief "make a short clip" --out .r37-local
```

The final command currently exits code 3 because no accepted Media tuple is frozen.

Future coordinator usage after independent Media acceptance:

```bash
creator-local-integration-r37 run \
  --source input.mp4 \
  --brief "make a short clip" \
  --media-authority accepted-media-r25.json \
  --out .r37-local
```

That validates and freezes source/brief/Media/Growth/Bridge authority into the durable local ledger and reports the next coordinator action. It still does not claim that a local PC E2E has occurred until the coordinator actually executes the runtime boundary.

Windows wrapper:

```bat
tools\creator-local-integration-r37.cmd readiness
tools\creator-local-integration-r37.cmd fixture-rehearsal --out .r37-fixture
tools\creator-local-integration-r37.cmd run --source input.mp4 --brief "make a short clip" --out .r37-local
```

## Safety

No live publish, provider network mutation, browser mutation, credentials, or merge is part of R37. Fixture review/model evidence is explicitly labeled fixture-only and is never represented as genuine model review.
