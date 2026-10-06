from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import autonomous_reels as reels
from . import proof_carrying_release_r36 as r36

CONTRACT_VERSION = "creator.local_integration_driver.r37.v1"
LEDGER_VERSION = "creator.local_integration_driver_ledger.r37.v1"
STATUS_VERSION = "creator.local_integration_driver_status.r37.v1"
PROOF_VERSION = "creator.local_integration_proof_graph.r37.v1"
REHEARSAL_VERSION = "creator.local_integration_rehearsal.r37.v1"
READINESS_VERSION = "creator.local_integration_driver_readiness.r37.v1"
EVIDENCE_VERSION = "creator.local_integration_driver_evidence.r37.v1"

FINAL_FIXTURE_STATE = "LOCAL_REHEARSAL_COMPLETE"
LIVE_AUTHORIZATION_FALSE = False
MAX_REEDIT_ROUNDS = 2

GROWTH_AUTHORITY = {
    "repository": "foto6/video3",
    "producerSha": "9ff243bc5ec6977bc5f0eb8f16cd5e51aa0dcdfc",
    "ciRunId": 37244660304,
    "artifactId": 11318054384,
    "artifactName": "growth-r34-counterfactual-policy-promotion",
    "artifactDigest": "sha256:6fc329964c14ce7c11f27fd2dd47235912470a377c6a1f5a6f3e66f4481f5ac9",
    "contract": "growth.counterfactual_policy_promotion.r34.v1",
    "advisoryOnly": True,
    "blobs": {
        "authority": "ef6d2d636a651a927702e106609084e405124d22",
        "contract": "d65858f6644d8445d6ba1665e793b371f5d93d7b",
        "candidatePolicySchema": "8ec92c37761c5b8104739fcb894ac6c01f8ede19",
        "corpusSchema": "722104d2ac77448a1db09b81d1bb3fa6266ad9ef",
        "creatorEnvelopeSchema": "2ee8dc030ea418b4e25cc986288dbdee738df398",
        "decisionSchema": "1199664fb0226a68449ec1a380734851896ecd79",
        "policy": "c9ef96296d0883852df32b2a90ee6271474e033f",
        "implementation": "74c847fe925375561a045b86f076498b85aafe8c",
        "tests": "cd435e80096f5b2492ad4afff3b961d49767c76b",
        "docs": "2ebbc64638ef7a6edf7ed8472ad6d9671fb8455b",
    },
}

BRIDGE_AUTHORITY = {
    "repository": "foto6/WebAIBridge",
    "producerSha": "f4f6070a975ac2c5bd8323777db1514c4733e427",
    "ciRunId": 37244988343,
    "contract": "bridge.agent_dag_orchestrator.r38.v1",
    "artifacts": [
        {
            "id": 11318149497,
            "name": "r38-reboot-resilient-agent-dag-ubuntu-latest",
            "digest": "sha256:aaca65ba7f3beaa9f7cb393325a7f44872b5874fe6881c586dab7c56e79bdbe4",
        },
        {
            "id": 11318049994,
            "name": "r38-reboot-resilient-agent-dag-windows-latest",
            "digest": "sha256:384c0cdcc6759541953d415dab0ad96dffdef48bd467017b9ea5a6047615da85",
        },
    ],
    "blobs": {
        "workflow": "d738d85554607d585c6ceeb351bad315a5dfaa6b",
        "runtime": "052a463a3d507fd6c9e014500513dcc06d5d47d4",
        "tests": "095d5296e841741add9c649d0d1960c4d8cfa614",
        "nodeSchema": "cfdd64ccad7ee1c0a9924e5d86ea217b29d842a3",
        "orchestratorSchema": "3cc5645eb9667ec5bff91fa7c734691a4b74fad2",
        "journalSchema": "1daaffa185317add81ed67b188e1caebfd51b609",
        "statusSchema": "ffbeea3e39dcdddfc63e0f3713516ba61e424232",
        "chaos": "c4075b2492d0e841c3dad6b470b8e770243af89f",
        "rehearsal": "054e0923b1b7dded89201ee736188de87f34d92e",
        "status": "fe4a91767e85725dac707b2caae8964d3ef5ea90",
        "readiness": "a131cc06241791a1b7fe2581999b6055e3c7cb93",
        "docs": "96f57d53e6c29bd13a2ce46b4bf8ee62370d2253",
    },
}

QA_R6_AUTHORITY = copy.deepcopy(r36.QA_R6)

MEDIA_REQUIRED_UNACCEPTED = {
    "repository": "foto6/video2",
    "contract": "media.multicandidate_round.r25.v1",
    "status": "UNACCEPTED",
    "consumption": "NOT_CONSUMED",
    "qaR6CutoffSha": "7ef00d9eec4b125f5ee7bcd28fc47cd390d82d86",
    "qaR6CutoffCiRunId": 37245663074,
    "qaR6CutoffCiStatus": "queued",
    "qaR6Disposition": "WAITING_EXACT_GREEN",
    "laterBranchMovementTrusted": False,
}

REQUIRED_MEDIA_CONTRACT = "media.multicandidate_round.r25.v1"
REQUIRED_MEDIA_REPOSITORY = "foto6/video2"
REQUIRED_MEDIA_BLOB_KEYS = {
    "contract",
    "schema",
    "manifest",
    "runtime",
}
ALLOWED_DIRECTIVES = {
    "trim_span",
    "caption_emphasis",
    "reframe_subject",
    "audio_mix",
}
STAGES = (
    "INITIALIZED",
    "AUTHORITIES_VERIFIED",
    "CANDIDATES_READY",
    "REVIEW_DECISION_READY",
    "TARGETED_REEDIT_APPLIED",
    "WINNER_SELECTED",
    "PROOF_GRAPH_VERIFIED",
    "RELEASE_ESCROWED",
    FINAL_FIXTURE_STATE,
)


class DriverError(ValueError):
    pass


class AuthorityError(DriverError):
    pass


class MediaAuthorityRequired(AuthorityError):
    pass


class ReplayConflict(DriverError):
    pass


class StateError(DriverError):
    pass


def _clone(value: Any) -> Any:
    return json.loads(reels.canonical_json(value))


def _sha(value: Any) -> str:
    return reels.sha256_json(value)


def _hex(value: Any, size: int, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != size
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise DriverError(f"{field} must be lowercase {size}-hex")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DriverError(f"{field} must be positive integer")
    return value


def _canonical_file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def authority_envelope(media_authority: Mapping[str, Any] | None = None) -> dict[str, Any]:
    media = MEDIA_REQUIRED_UNACCEPTED if media_authority is None else _clone(media_authority)
    value = {
        "contractVersion": "creator.local_integration_authority.r37.v1",
        "growth": _clone(GROWTH_AUTHORITY),
        "bridge": _clone(BRIDGE_AUTHORITY),
        "qaR6": _clone(QA_R6_AUTHORITY),
        "media": _clone(media),
    }
    value["authorityDigest"] = _sha(value)
    return value


def _validate_growth_bridge(envelope: Mapping[str, Any]) -> None:
    if envelope.get("growth") != GROWTH_AUTHORITY:
        raise AuthorityError("Growth R34 authority drift")
    if envelope.get("bridge") != BRIDGE_AUTHORITY:
        raise AuthorityError("Bridge R38 authority drift")
    qa = envelope.get("qaR6")
    if qa != QA_R6_AUTHORITY:
        raise AuthorityError("QA R6 authority drift")
    expected = {
        "creatorR35": "ACCEPTED",
        "growthR34": "ACCEPTED",
        "bridgeR38": "ACCEPTED",
        "mediaR25": "WAITING_EXACT_GREEN",
    }
    if qa.get("disposition") != expected:
        raise AuthorityError("QA R6 disposition drift")


def validate_media_authority(
    media: Mapping[str, Any] | None,
    *,
    require_accepted: bool,
) -> dict[str, Any]:
    if media is None:
        if require_accepted:
            raise MediaAuthorityRequired("independently accepted Media R25 authority is required")
        return _clone(MEDIA_REQUIRED_UNACCEPTED)
    if media.get("repository") != REQUIRED_MEDIA_REPOSITORY:
        raise AuthorityError("Media repository mismatch")
    if media.get("contract") != REQUIRED_MEDIA_CONTRACT:
        raise AuthorityError("Media contract mismatch")
    if not require_accepted:
        if media != MEDIA_REQUIRED_UNACCEPTED:
            raise AuthorityError("fixture mode must use frozen unaccepted Media evidence")
        return _clone(media)

    required = {
        "repository",
        "contract",
        "status",
        "producerSha",
        "ciRunId",
        "ciConclusion",
        "artifactId",
        "artifactName",
        "artifactDigest",
        "blobs",
        "independentQa",
    }
    if set(media) != required:
        raise MediaAuthorityRequired("accepted Media authority fields mismatch")
    if media["status"] != "ACCEPTED":
        raise MediaAuthorityRequired("Media R25 is not independently accepted")
    _hex(media["producerSha"], 40, "media.producerSha")
    _positive_int(media["ciRunId"], "media.ciRunId")
    _positive_int(media["artifactId"], "media.artifactId")
    if media["ciConclusion"] != "success":
        raise MediaAuthorityRequired("Media exact-head CI is not success")
    if not isinstance(media["artifactName"], str) or not media["artifactName"]:
        raise MediaAuthorityRequired("Media artifact name missing")
    digest = media["artifactDigest"]
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise MediaAuthorityRequired("Media artifact digest missing")
    _hex(digest.removeprefix("sha256:"), 64, "media.artifactDigest")
    blobs = media["blobs"]
    if not isinstance(blobs, Mapping) or set(blobs) != REQUIRED_MEDIA_BLOB_KEYS:
        raise MediaAuthorityRequired("Media exact blob identity set mismatch")
    for key, value in blobs.items():
        _hex(value, 40, f"media.blobs.{key}")

    qa = media["independentQa"]
    required_qa = {
        "repository",
        "producerSha",
        "ciRunId",
        "ciConclusion",
        "artifactId",
        "artifactDigest",
        "disposition",
        "acceptedMediaProducerSha",
        "acceptedMediaCiRunId",
        "acceptedMediaArtifactId",
        "acceptedMediaArtifactDigest",
        "acceptedMediaContract",
    }
    if not isinstance(qa, Mapping) or set(qa) != required_qa:
        raise MediaAuthorityRequired("Media independent QA tuple fields mismatch")
    if qa["ciConclusion"] != "success" or qa["disposition"] != "ACCEPTED":
        raise MediaAuthorityRequired("Media independent QA has not accepted producer")
    _hex(qa["producerSha"], 40, "media.independentQa.producerSha")
    _positive_int(qa["ciRunId"], "media.independentQa.ciRunId")
    _positive_int(qa["artifactId"], "media.independentQa.artifactId")
    if not isinstance(qa["artifactDigest"], str) or not qa["artifactDigest"].startswith("sha256:"):
        raise MediaAuthorityRequired("Media QA artifact digest missing")
    _hex(qa["artifactDigest"].removeprefix("sha256:"), 64, "media.independentQa.artifactDigest")
    if (
        qa["acceptedMediaProducerSha"] != media["producerSha"]
        or qa["acceptedMediaCiRunId"] != media["ciRunId"]
        or qa["acceptedMediaArtifactId"] != media["artifactId"]
        or qa["acceptedMediaArtifactDigest"] != media["artifactDigest"]
        or qa["acceptedMediaContract"] != media["contract"]
    ):
        raise MediaAuthorityRequired("Media QA acceptance does not bind exact producer tuple")
    return _clone(media)


def validate_authority_envelope(
    envelope: Mapping[str, Any],
    *,
    require_accepted_media: bool,
) -> dict[str, Any]:
    if not isinstance(envelope, Mapping):
        raise AuthorityError("authority envelope must be object")
    expected_fields = {
        "contractVersion",
        "growth",
        "bridge",
        "qaR6",
        "media",
        "authorityDigest",
    }
    if set(envelope) != expected_fields:
        raise AuthorityError("authority envelope fields mismatch")
    if envelope["contractVersion"] != "creator.local_integration_authority.r37.v1":
        raise AuthorityError("authority envelope version mismatch")
    _validate_growth_bridge(envelope)
    validate_media_authority(envelope["media"], require_accepted=require_accepted_media)
    material = _clone(envelope)
    digest = material.pop("authorityDigest")
    if digest != _sha(material):
        # Backward-compatible authority_envelope hashes the object before authorityDigest.
        expected = {
            "contractVersion": envelope["contractVersion"],
            "growth": envelope["growth"],
            "bridge": envelope["bridge"],
            "qaR6": envelope["qaR6"],
            "media": envelope["media"],
        }
        if digest != _sha(expected):
            raise AuthorityError("authority envelope digest mismatch")
    return _clone(envelope)


class DriverLedger:
    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        source_sha256: str | None = None,
        source_size: int | None = None,
        brief_digest: str | None = None,
        mode: str | None = None,
        authority: Mapping[str, Any] | None = None,
    ) -> None:
        self.root = Path(root)
        self.path = self.root / "local-integration-ledger.r37.jsonl"
        self.events: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        self.state: dict[str, Any] = {}
        if self.path.exists():
            self._load()
            if source_sha256 is not None and self.state["source"]["sha256"] != source_sha256:
                raise ReplayConflict("source changed on restart")
            if brief_digest is not None and self.state["briefDigest"] != brief_digest:
                raise ReplayConflict("brief changed on restart")
            if authority is not None and self.state["authorityDigest"] != authority["authorityDigest"]:
                raise ReplayConflict("authority changed on restart")
            return
        if None in (source_sha256, source_size, brief_digest, mode, authority):
            raise DriverError("new ledger requires source, brief, mode and authority")
        _hex(source_sha256, 64, "sourceSha256")
        _positive_int(source_size, "sourceSize")
        _hex(brief_digest, 64, "briefDigest")
        if mode not in {"fixture", "local"}:
            raise DriverError("mode must be fixture or local")
        initial = {
            "contractVersion": CONTRACT_VERSION,
            "state": "INITIALIZED",
            "mode": mode,
            "sessionId": "r37:" + _sha(
                {
                    "sourceSha256": source_sha256,
                    "briefDigest": brief_digest,
                    "authorityDigest": authority["authorityDigest"],
                    "mode": mode,
                }
            ),
            "source": {"sha256": source_sha256, "size": source_size},
            "briefDigest": brief_digest,
            "authorityDigest": authority["authorityDigest"],
            "authority": _clone(authority),
            "round": 0,
            "reeditRound": 0,
            "candidates": [],
            "review": None,
            "winner": None,
            "proof": None,
            "releaseEscrow": None,
            "providerEffects": 0,
            "networkEffects": 0,
            "liveAuthorization": False,
            "blockers": [],
        }
        self._append(
            event_key="initialize",
            event_type="DRIVER_INITIALIZED",
            request={"initial": initial},
            new_state=initial,
            previous_state={},
        )

    def _load(self) -> None:
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReplayConflict(f"invalid ledger JSON at line {line_number}") from exc
            required = {
                "ledgerVersion",
                "sequence",
                "eventKey",
                "eventType",
                "requestDigest",
                "previousStateDigest",
                "newStateDigest",
                "newState",
                "eventDigest",
            }
            if set(event) != required or event["ledgerVersion"] != LEDGER_VERSION:
                raise ReplayConflict("ledger event shape/version mismatch")
            if event["sequence"] != len(self.events) + 1:
                raise ReplayConflict("ledger sequence mismatch")
            if event["eventKey"] in self.by_key:
                raise ReplayConflict("duplicate ledger event key")
            if event["previousStateDigest"] != _sha(self.state):
                raise ReplayConflict("ledger previous-state chain mismatch")
            if event["newStateDigest"] != _sha(event["newState"]):
                raise ReplayConflict("ledger new-state digest mismatch")
            identity = {k: v for k, v in event.items() if k != "eventDigest"}
            if event["eventDigest"] != _sha(identity):
                raise ReplayConflict("ledger event digest mismatch")
            self.events.append(event)
            self.by_key[event["eventKey"]] = event
            self.state = _clone(event["newState"])

    def _append(
        self,
        *,
        event_key: str,
        event_type: str,
        request: Mapping[str, Any],
        new_state: Mapping[str, Any],
        previous_state: Mapping[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        request_digest = _sha(request)
        existing = self.by_key.get(event_key)
        if existing is not None:
            if (
                existing["eventType"] != event_type
                or existing["requestDigest"] != request_digest
                or existing["newStateDigest"] != _sha(new_state)
            ):
                raise ReplayConflict(f"conflicting replay for {event_key}")
            return "duplicate", _clone(existing)
        old = self.state if previous_state is None else _clone(previous_state)
        event = {
            "ledgerVersion": LEDGER_VERSION,
            "sequence": len(self.events) + 1,
            "eventKey": event_key,
            "eventType": event_type,
            "requestDigest": request_digest,
            "previousStateDigest": _sha(old),
            "newStateDigest": _sha(new_state),
            "newState": _clone(new_state),
        }
        event["eventDigest"] = _sha(event)
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(reels.canonical_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.events.append(event)
        self.by_key[event_key] = event
        self.state = _clone(new_state)
        return "committed", _clone(event)

    @property
    def digest(self) -> str:
        return _sha(self.events)


def _transition(
    ledger: DriverLedger,
    *,
    from_state: str,
    to_state: str,
    event_key: str,
    event_type: str,
    request: Mapping[str, Any],
    mutate: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    existing = ledger.by_key.get(event_key)
    if existing is not None:
        if existing["requestDigest"] != _sha(request):
            raise ReplayConflict(f"conflicting replay for {event_key}")
        return _clone(existing["newState"])
    if ledger.state["state"] != from_state:
        raise StateError(f"{event_type} forbidden from {ledger.state['state']}")
    new = _clone(ledger.state)
    new["state"] = to_state
    if mutate:
        mutate(new)
    ledger._append(
        event_key=event_key,
        event_type=event_type,
        request=request,
        new_state=new,
    )
    return _clone(new)


def verify_authorities(ledger: DriverLedger, *, require_accepted_media: bool) -> dict[str, Any]:
    validate_authority_envelope(
        ledger.state["authority"],
        require_accepted_media=require_accepted_media,
    )
    return _transition(
        ledger,
        from_state="INITIALIZED",
        to_state="AUTHORITIES_VERIFIED",
        event_key="authorities",
        event_type="AUTHORITIES_VERIFIED",
        request={
            "authorityDigest": ledger.state["authorityDigest"],
            "requireAcceptedMedia": require_accepted_media,
        },
    )


def _candidate(session_id: str, ordinal: int, source_sha: str) -> dict[str, Any]:
    cid = "r37c:" + _sha({"sessionId": session_id, "ordinal": ordinal})
    render_sha = _sha(
        {
            "candidateId": cid,
            "sourceSha256": source_sha,
            "fixtureEdit": ["clean", "aggressive", "hybrid"][ordinal],
        }
    )
    return {
        "candidateId": cid,
        "style": ["clean", "aggressive", "hybrid"][ordinal],
        "renderSha256": render_sha,
        "renderSize": 600000 + ordinal * 173,
        "fixtureOnly": True,
    }


def generate_fixture_candidates(ledger: DriverLedger) -> dict[str, Any]:
    if ledger.state["mode"] != "fixture":
        raise StateError("fixture candidate generator unavailable in local mode")
    candidates = [
        _candidate(ledger.state["sessionId"], ordinal, ledger.state["source"]["sha256"])
        for ordinal in range(3)
    ]
    if len({item["renderSha256"] for item in candidates}) != len(candidates):
        raise StateError("candidate bytes are not distinct")

    def mutate(new: dict[str, Any]) -> None:
        new["candidates"] = candidates
        new["round"] = 0

    return _transition(
        ledger,
        from_state="AUTHORITIES_VERIFIED",
        to_state="CANDIDATES_READY",
        event_key="candidates:r0",
        event_type="FIXTURE_CANDIDATES_GENERATED",
        request={
            "sourceSha256": ledger.state["source"]["sha256"],
            "authorityDigest": ledger.state["authorityDigest"],
            "candidateSetDigest": _sha(candidates),
        },
        mutate=mutate,
    )


def ingest_fixture_review(ledger: DriverLedger) -> dict[str, Any]:
    if ledger.state["mode"] != "fixture":
        raise StateError("fixture review unavailable in local mode")
    if not ledger.state["candidates"]:
        raise StateError("review requires candidates")
    selected = ledger.state["candidates"][1]
    review = {
        "contractVersion": "growth.fixture_review_decision.r37.v1",
        "authoritySha": GROWTH_AUTHORITY["producerSha"],
        "bridgeAuthoritySha": BRIDGE_AUTHORITY["producerSha"],
        "round": 0,
        "decision": "targeted_reedit",
        "selectedCandidateId": selected["candidateId"],
        "reviewedRenderSha256": selected["renderSha256"],
        "directive": {
            "operation": "trim_span",
            "startMs": 0,
            "endMs": 850,
            "reason": "fixture low-information lead-in",
        },
        "fixtureOnly": True,
        "decisionDigest": "",
    }
    review["decisionDigest"] = _sha({**review, "decisionDigest": ""})

    def mutate(new: dict[str, Any]) -> None:
        new["review"] = review

    return _transition(
        ledger,
        from_state="CANDIDATES_READY",
        to_state="REVIEW_DECISION_READY",
        event_key="review:r0",
        event_type="FIXTURE_REVIEW_INGESTED",
        request=review,
        mutate=mutate,
    )


def apply_fixture_reedit(ledger: DriverLedger) -> dict[str, Any]:
    review = ledger.state["review"]
    if review is None or review["decision"] != "targeted_reedit":
        raise StateError("targeted re-edit requires targeted review")
    if ledger.state["reeditRound"] >= MAX_REEDIT_ROUNDS:
        raise StateError("maximum re-edit rounds exceeded")
    selected = next(
        (c for c in ledger.state["candidates"] if c["candidateId"] == review["selectedCandidateId"]),
        None,
    )
    if selected is None or selected["renderSha256"] != review["reviewedRenderSha256"]:
        raise StateError("review/candidate lineage mismatch")
    directive = review["directive"]
    if directive["operation"] not in ALLOWED_DIRECTIVES:
        raise StateError("unsupported directive")
    output = {
        "parentCandidateId": selected["candidateId"],
        "parentRenderSha256": selected["renderSha256"],
        "outputCandidateId": selected["candidateId"] + ":r1",
        "outputRenderSha256": _sha(
            {
                "parentRenderSha256": selected["renderSha256"],
                "directive": directive,
                "round": 1,
            }
        ),
        "outputRenderSize": selected["renderSize"] - 941,
        "applicationContract": "media.editorial_reedit_application.v1",
        "fixtureOnly": True,
    }

    def mutate(new: dict[str, Any]) -> None:
        new["round"] = 1
        new["reeditRound"] = 1
        new["candidates"] = [output]
        new["review"] = {
            "contractVersion": "growth.fixture_review_decision.r37.v1",
            "authoritySha": GROWTH_AUTHORITY["producerSha"],
            "bridgeAuthoritySha": BRIDGE_AUTHORITY["producerSha"],
            "round": 1,
            "decision": "winner",
            "selectedCandidateId": output["outputCandidateId"],
            "reviewedRenderSha256": output["outputRenderSha256"],
            "directive": None,
            "fixtureOnly": True,
            "decisionDigest": "",
        }
        new["review"]["decisionDigest"] = _sha(
            {**new["review"], "decisionDigest": ""}
        )

    return _transition(
        ledger,
        from_state="REVIEW_DECISION_READY",
        to_state="TARGETED_REEDIT_APPLIED",
        event_key="reedit:r1",
        event_type="FIXTURE_TARGETED_REEDIT_APPLIED",
        request=output,
        mutate=mutate,
    )


def select_fixture_winner(ledger: DriverLedger) -> dict[str, Any]:
    review = ledger.state["review"]
    if review is None or review["decision"] != "winner":
        raise StateError("winner selection requires winner decision")
    candidate = ledger.state["candidates"][0]
    if (
        candidate["outputCandidateId"] != review["selectedCandidateId"]
        or candidate["outputRenderSha256"] != review["reviewedRenderSha256"]
    ):
        raise StateError("winner review lineage mismatch")
    winner = {
        "candidateId": candidate["outputCandidateId"],
        "renderSha256": candidate["outputRenderSha256"],
        "renderSize": candidate["outputRenderSize"],
        "reviewDecisionDigest": review["decisionDigest"],
        "round": 1,
        "fixtureOnly": True,
    }

    def mutate(new: dict[str, Any]) -> None:
        new["winner"] = winner

    return _transition(
        ledger,
        from_state="TARGETED_REEDIT_APPLIED",
        to_state="WINNER_SELECTED",
        event_key="winner:r1",
        event_type="FIXTURE_WINNER_SELECTED",
        request=winner,
        mutate=mutate,
    )


def build_and_verify_proof_graph(ledger: DriverLedger) -> dict[str, Any]:
    upstream_bundle = r36.build_bundle()
    verification = r36.verify_bundle(upstream_bundle)
    winner = ledger.state["winner"]
    nodes: list[dict[str, Any]] = []
    predecessor = ""
    evidence_rows = [
        (
            "SOURCE_BOUND",
            {
                "sourceSha256": ledger.state["source"]["sha256"],
                "briefDigest": ledger.state["briefDigest"],
            },
        ),
        (
            "AUTHORITIES_BOUND",
            {
                "authorityDigest": ledger.state["authorityDigest"],
                "growthSha": GROWTH_AUTHORITY["producerSha"],
                "bridgeSha": BRIDGE_AUTHORITY["producerSha"],
                "mediaStatus": MEDIA_REQUIRED_UNACCEPTED["status"],
            },
        ),
        (
            "WINNER_BOUND",
            {
                "winnerRenderSha256": winner["renderSha256"],
                "winnerRenderSize": winner["renderSize"],
                "decisionDigest": winner["reviewDecisionDigest"],
            },
        ),
        (
            "R36_PROOF_VERIFIED",
            {
                "r36BundleDigest": upstream_bundle["bundleDigest"],
                "r36FinalProofDigest": verification["finalProofDigest"],
                "providerEffects": verification["provider_effects"],
                "liveAuthorization": verification["live_authorization"],
            },
        ),
    ]
    for node_type, evidence in evidence_rows:
        node = {
            "nodeType": node_type,
            "predecessorDigest": predecessor,
            "evidence": evidence,
            "evidenceDigest": _sha(evidence),
            "nodeDigest": "",
        }
        node["nodeDigest"] = _sha({**node, "nodeDigest": ""})
        predecessor = node["nodeDigest"]
        nodes.append(node)
    proof = {
        "contractVersion": PROOF_VERSION,
        "nodes": nodes,
        "rootDigest": nodes[0]["nodeDigest"],
        "finalDigest": nodes[-1]["nodeDigest"],
        "r36BundleDigest": upstream_bundle["bundleDigest"],
    }
    verify_proof_graph(proof)

    def mutate(new: dict[str, Any]) -> None:
        new["proof"] = proof

    return _transition(
        ledger,
        from_state="WINNER_SELECTED",
        to_state="PROOF_GRAPH_VERIFIED",
        event_key="proof",
        event_type="CREATOR_PROOF_GRAPH_VERIFIED",
        request=proof,
        mutate=mutate,
    )


def verify_proof_graph(proof: Mapping[str, Any]) -> dict[str, Any]:
    if proof.get("contractVersion") != PROOF_VERSION:
        raise StateError("proof graph version mismatch")
    nodes = proof.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != 4:
        raise StateError("proof graph node count mismatch")
    predecessor = ""
    for node in nodes:
        if node.get("predecessorDigest") != predecessor:
            raise StateError("proof graph predecessor mismatch")
        if node.get("evidenceDigest") != _sha(node.get("evidence")):
            raise StateError("proof evidence digest mismatch")
        expected = _sha({**node, "nodeDigest": ""})
        if node.get("nodeDigest") != expected:
            raise StateError("proof node digest mismatch")
        predecessor = node["nodeDigest"]
    if proof.get("rootDigest") != nodes[0]["nodeDigest"]:
        raise StateError("proof root digest mismatch")
    if proof.get("finalDigest") != nodes[-1]["nodeDigest"]:
        raise StateError("proof final digest mismatch")
    if nodes[-1]["evidence"]["providerEffects"] != 0:
        raise StateError("proof provider effects must remain zero")
    if nodes[-1]["evidence"]["liveAuthorization"] is not False:
        raise StateError("proof live authorization must remain false")
    return {"valid": True, "finalDigest": proof["finalDigest"]}


def escrow_fixture_release(ledger: DriverLedger) -> dict[str, Any]:
    if ledger.state["proof"] is None:
        raise StateError("release escrow requires proof graph")
    winner = ledger.state["winner"]
    winner_event = ledger.by_key.get("winner:r1")
    if winner_event is None or winner_event["requestDigest"] != _sha(winner):
        raise StateError("winner changed after durable selection")
    escrow = {
        "contractVersion": "creator.release_escrow_canary.r35.v1",
        "mode": "fixture_rehearsal_only",
        "winnerRenderSha256": winner["renderSha256"],
        "winnerRenderSize": winner["renderSize"],
        "proofFinalDigest": ledger.state["proof"]["finalDigest"],
        "growthDecisionDigest": winner["reviewDecisionDigest"],
        "platforms": ["instagram_reels", "tiktok", "youtube_shorts"],
        "providerEffects": 0,
        "networkEffects": 0,
        "liveAuthorization": False,
        "escrowDigest": "",
    }
    escrow["escrowDigest"] = _sha({**escrow, "escrowDigest": ""})

    def mutate(new: dict[str, Any]) -> None:
        new["releaseEscrow"] = escrow

    return _transition(
        ledger,
        from_state="PROOF_GRAPH_VERIFIED",
        to_state="RELEASE_ESCROWED",
        event_key="escrow",
        event_type="FIXTURE_RELEASE_ESCROWED",
        request=escrow,
        mutate=mutate,
    )


def complete_fixture(ledger: DriverLedger) -> dict[str, Any]:
    if ledger.state["releaseEscrow"] is None:
        raise StateError("completion requires release escrow")

    def mutate(new: dict[str, Any]) -> None:
        new["providerEffects"] = 0
        new["networkEffects"] = 0
        new["liveAuthorization"] = False
        new["blockers"] = []

    return _transition(
        ledger,
        from_state="RELEASE_ESCROWED",
        to_state=FINAL_FIXTURE_STATE,
        event_key="complete",
        event_type="LOCAL_REHEARSAL_COMPLETED",
        request={
            "releaseEscrowDigest": ledger.state["releaseEscrow"]["escrowDigest"],
            "liveAuthorization": False,
        },
        mutate=mutate,
    )


def resume_fixture(ledger: DriverLedger) -> dict[str, Any]:
    while ledger.state["state"] != FINAL_FIXTURE_STATE:
        state = ledger.state["state"]
        if state == "INITIALIZED":
            verify_authorities(ledger, require_accepted_media=False)
        elif state == "AUTHORITIES_VERIFIED":
            generate_fixture_candidates(ledger)
        elif state == "CANDIDATES_READY":
            ingest_fixture_review(ledger)
        elif state == "REVIEW_DECISION_READY":
            apply_fixture_reedit(ledger)
        elif state == "TARGETED_REEDIT_APPLIED":
            select_fixture_winner(ledger)
        elif state == "WINNER_SELECTED":
            build_and_verify_proof_graph(ledger)
        elif state == "PROOF_GRAPH_VERIFIED":
            escrow_fixture_release(ledger)
        elif state == "RELEASE_ESCROWED":
            complete_fixture(ledger)
        else:
            raise StateError(f"unhandled fixture state {state}")
    return _clone(ledger.state)


def fixture_inputs() -> tuple[str, int, str]:
    source = b"r37 deterministic local integration source fixture\n"
    return (
        hashlib.sha256(source).hexdigest(),
        len(source),
        hashlib.sha256(b"R37 fixture brief").hexdigest(),
    )


def run_fixture_rehearsal(out_dir: str | os.PathLike[str]) -> dict[str, Any]:
    root = Path(out_dir)
    source_sha, source_size, brief_digest = fixture_inputs()
    authority = authority_envelope()
    validate_authority_envelope(authority, require_accepted_media=False)
    ledger = DriverLedger(
        root,
        source_sha256=source_sha,
        source_size=source_size,
        brief_digest=brief_digest,
        mode="fixture",
        authority=authority,
    )
    before = len(ledger.events)
    final = resume_fixture(ledger)
    event_count = len(ledger.events)
    restarted = DriverLedger(
        root,
        source_sha256=source_sha,
        source_size=source_size,
        brief_digest=brief_digest,
        mode="fixture",
        authority=authority,
    )
    replay_final = resume_fixture(restarted)
    if replay_final != final or len(restarted.events) != event_count:
        raise AssertionError("fixture replay changed durable evidence")
    report = {
        "reportVersion": REHEARSAL_VERSION,
        "state": final["state"],
        "mode": "fixture",
        "actualLocalPcE2EExecuted": False,
        "mediaAuthorityAccepted": False,
        "mediaAuthorityStatus": final["authority"]["media"]["status"],
        "growthAuthoritySha": GROWTH_AUTHORITY["producerSha"],
        "bridgeAuthoritySha": BRIDGE_AUTHORITY["producerSha"],
        "candidateCount": 3,
        "reviewRounds": 2,
        "targetedReeditRounds": final["reeditRound"],
        "winnerRenderSha256": final["winner"]["renderSha256"],
        "proofFinalDigest": final["proof"]["finalDigest"],
        "releaseEscrowDigest": final["releaseEscrow"]["escrowDigest"],
        "ledgerDigest": restarted.digest,
        "ledgerEventCount": event_count,
        "eventsAddedOnReplay": len(restarted.events) - event_count,
        "initialEventsObserved": before,
        "providerEffects": final["providerEffects"],
        "networkEffects": final["networkEffects"],
        "liveAuthorization": final["liveAuthorization"],
        "finalDisposition": "LOCAL_REHEARSAL_COMPLETE / LIVE_AUTHORIZATION_FALSE",
    }
    report["reportDigest"] = _sha(report)
    root.mkdir(parents=True, exist_ok=True)
    (root / "local-rehearsal.r37.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "final-state.r37.json").write_text(
        json.dumps(final, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    evidence = {
        "contractVersion": EVIDENCE_VERSION,
        "rehearsalDigest": report["reportDigest"],
        "authorityDigest": authority["authorityDigest"],
        "ledgerFileSha256": _canonical_file_sha(ledger.path),
        "ledgerSize": ledger.path.stat().st_size,
        "winnerRenderSha256": final["winner"]["renderSha256"],
        "proofFinalDigest": final["proof"]["finalDigest"],
        "releaseEscrowDigest": final["releaseEscrow"]["escrowDigest"],
        "mediaRequired": True,
        "mediaAccepted": False,
        "actualLocalPcE2EExecuted": False,
        "providerEffects": 0,
        "networkEffects": 0,
        "liveAuthorization": False,
    }
    evidence["evidenceDigest"] = _sha(evidence)
    (root / "evidence-manifest.r37.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def prepare_local_run(
    *,
    source_path: str | os.PathLike[str],
    brief: str,
    out_dir: str | os.PathLike[str],
    media_authority: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source = Path(source_path)
    if not source.is_file():
        raise DriverError("local source file does not exist")
    if not isinstance(brief, str) or not brief.strip():
        raise DriverError("brief must be non-empty")
    media = validate_media_authority(media_authority, require_accepted=True)
    authority = authority_envelope(media)
    validate_authority_envelope(authority, require_accepted_media=True)
    source_sha = _canonical_file_sha(source)
    source_size = source.stat().st_size
    brief_digest = hashlib.sha256(brief.encode("utf-8")).hexdigest()
    ledger = DriverLedger(
        out_dir,
        source_sha256=source_sha,
        source_size=source_size,
        brief_digest=brief_digest,
        mode="local",
        authority=authority,
    )
    verify_authorities(ledger, require_accepted_media=True)
    status = {
        "contractVersion": STATUS_VERSION,
        "state": "SOURCE_READY_ACCEPTED_MEDIA",
        "ledgerState": ledger.state["state"],
        "sourceSha256": source_sha,
        "sourceSize": source_size,
        "briefDigest": brief_digest,
        "authorityDigest": authority["authorityDigest"],
        "mediaProducerSha": media["producerSha"],
        "nextPermittedAction": "COORDINATOR_EXECUTE_REAL_MEDIA_GROWTH_BRIDGE_LOOP",
        "actualLocalPcE2EExecuted": False,
        "providerEffects": 0,
        "networkEffects": 0,
        "liveAuthorization": False,
    }
    status["statusDigest"] = _sha(status)
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "local-run-status.r37.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return status


def blocked_local_status() -> dict[str, Any]:
    value = {
        "contractVersion": STATUS_VERSION,
        "state": "BLOCKED_WAITING_ACCEPTED_MEDIA_AUTHORITY",
        "nextPermittedAction": "SUPPLY_INDEPENDENTLY_ACCEPTED_MEDIA_R25_TUPLE",
        "requiredMedia": _clone(MEDIA_REQUIRED_UNACCEPTED),
        "acceptedGrowth": _clone(GROWTH_AUTHORITY),
        "acceptedBridge": _clone(BRIDGE_AUTHORITY),
        "qaR6": _clone(QA_R6_AUTHORITY),
        "actualLocalPcE2EExecuted": False,
        "providerEffects": 0,
        "networkEffects": 0,
        "liveAuthorization": False,
    }
    value["statusDigest"] = _sha(value)
    return value


def readiness() -> dict[str, Any]:
    value = {
        "reportVersion": READINESS_VERSION,
        "state": "SOURCE_READY_WAITING_ACCEPTED_MEDIA",
        "SOURCE_READY": True,
        "LOCAL_FIXTURE_REHEARSAL_AVAILABLE": True,
        "ACTUAL_LOCAL_PC_E2E_EXECUTED": False,
        "media": {
            "required": True,
            "status": "UNACCEPTED",
            "consumption": "NOT_CONSUMED",
            "contract": REQUIRED_MEDIA_CONTRACT,
            "blocker": "INDEPENDENTLY_ACCEPTED_MEDIA_TUPLE_REQUIRED",
        },
        "growthAuthority": _clone(GROWTH_AUTHORITY),
        "bridgeAuthority": _clone(BRIDGE_AUTHORITY),
        "qaR6": _clone(QA_R6_AUTHORITY),
        "fixtureFinalState": FINAL_FIXTURE_STATE,
        "fixtureLiveAuthorization": False,
        "safety": {
            "providerEffects": 0,
            "networkEffects": 0,
            "liveAuthorization": False,
            "browserMutation": False,
            "providerMutation": False,
            "livePublish": False,
            "mergePerformed": False,
        },
    }
    value["reportDigest"] = _sha(value)
    return value


ADVERSARIAL_CASES = (
    "growth_sha_drift",
    "growth_ci_drift",
    "growth_artifact_drift",
    "growth_digest_drift",
    "growth_blob_drift",
    "bridge_sha_drift",
    "bridge_ci_drift",
    "bridge_ubuntu_artifact_drift",
    "bridge_windows_digest_drift",
    "bridge_blob_drift",
    "qa_r6_sha_drift",
    "qa_r6_disposition_drift",
    "media_missing",
    "media_wrong_repository",
    "media_wrong_contract",
    "media_not_accepted",
    "media_ci_not_success",
    "media_artifact_digest_invalid",
    "media_blob_set_incomplete",
    "media_qa_not_accepted",
    "media_qa_producer_mismatch",
    "media_qa_ci_mismatch",
    "media_qa_artifact_mismatch",
    "media_qa_digest_mismatch",
    "media_qa_contract_mismatch",
    "ledger_source_drift",
    "ledger_brief_drift",
    "ledger_event_corruption",
    "candidate_duplicate_bytes",
    "review_stale_render",
    "unsupported_directive",
    "reedit_round_overflow",
    "proof_predecessor_tamper",
    "proof_evidence_tamper",
    "proof_live_authorization_tamper",
    "escrow_winner_hash_tamper",
    "fixture_replay_conflict",
    "local_source_missing",
)


def accepted_media_fixture() -> dict[str, Any]:
    media = {
        "repository": REQUIRED_MEDIA_REPOSITORY,
        "contract": REQUIRED_MEDIA_CONTRACT,
        "status": "ACCEPTED",
        "producerSha": "1" * 40,
        "ciRunId": 40000000001,
        "ciConclusion": "success",
        "artifactId": 12000000001,
        "artifactName": "media-r25-independent-fixture",
        "artifactDigest": "sha256:" + "2" * 64,
        "blobs": {
            "contract": "3" * 40,
            "schema": "4" * 40,
            "manifest": "5" * 40,
            "runtime": "6" * 40,
        },
        "independentQa": {
            "repository": "foto6/boss",
            "producerSha": "7" * 40,
            "ciRunId": 40000000002,
            "ciConclusion": "success",
            "artifactId": 12000000002,
            "artifactDigest": "sha256:" + "8" * 64,
            "disposition": "ACCEPTED",
            "acceptedMediaProducerSha": "1" * 40,
            "acceptedMediaCiRunId": 40000000001,
            "acceptedMediaArtifactId": 12000000001,
            "acceptedMediaArtifactDigest": "sha256:" + "2" * 64,
            "acceptedMediaContract": REQUIRED_MEDIA_CONTRACT,
        },
    }
    return media


def _expect_failure(fn: Callable[[], Any]) -> bool:
    try:
        fn()
    except (DriverError, r36.ProofError):
        return True
    return False


def run_adversarial_cases(tmp_root: str | os.PathLike[str]) -> dict[str, Any]:
    root = Path(tmp_root)
    root.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, Any]] = {}

    def record(name: str, fn: Callable[[], Any]) -> None:
        results[name] = {"passed": _expect_failure(fn)}

    for name, key in [
        ("growth_sha_drift", "producerSha"),
        ("growth_ci_drift", "ciRunId"),
        ("growth_artifact_drift", "artifactId"),
        ("growth_digest_drift", "artifactDigest"),
    ]:
        def run(name=name, key=key):
            a = authority_envelope()
            a["growth"][key] = "0" * 40 if key == "producerSha" else (1 if key in {"ciRunId", "artifactId"} else "sha256:" + "0" * 64)
            a["authorityDigest"] = _sha({k: v for k, v in a.items() if k != "authorityDigest"})
            validate_authority_envelope(a, require_accepted_media=False)
        record(name, run)
    def growth_blob():
        a=authority_envelope(); a["growth"]["blobs"]["runtime"]="0"*40
        a["authorityDigest"]=_sha({k:v for k,v in a.items() if k!="authorityDigest"})
        validate_authority_envelope(a,require_accepted_media=False)
    record("growth_blob_drift", growth_blob)

    for name, mut in [
        ("bridge_sha_drift", lambda a: a["bridge"].__setitem__("producerSha","0"*40)),
        ("bridge_ci_drift", lambda a: a["bridge"].__setitem__("ciRunId",1)),
        ("bridge_ubuntu_artifact_drift", lambda a: a["bridge"]["artifacts"][0].__setitem__("id",1)),
        ("bridge_windows_digest_drift", lambda a: a["bridge"]["artifacts"][1].__setitem__("digest","sha256:"+"0"*64)),
        ("bridge_blob_drift", lambda a: a["bridge"]["blobs"].__setitem__("runtime","0"*40)),
        ("qa_r6_sha_drift", lambda a: a["qaR6"].__setitem__("producerSha","0"*40)),
        ("qa_r6_disposition_drift", lambda a: a["qaR6"]["disposition"].__setitem__("mediaR25","ACCEPTED")),
    ]:
        def run(mut=mut):
            a=authority_envelope(); mut(a)
            a["authorityDigest"]=_sha({k:v for k,v in a.items() if k!="authorityDigest"})
            validate_authority_envelope(a,require_accepted_media=False)
        record(name,run)

    record("media_missing", lambda: validate_media_authority(None, require_accepted=True))
    for name, mut in [
        ("media_wrong_repository", lambda m: m.__setitem__("repository","other/repo")),
        ("media_wrong_contract", lambda m: m.__setitem__("contract","media.other.v1")),
        ("media_not_accepted", lambda m: m.__setitem__("status","UNACCEPTED")),
        ("media_ci_not_success", lambda m: m.__setitem__("ciConclusion","failure")),
        ("media_artifact_digest_invalid", lambda m: m.__setitem__("artifactDigest","bad")),
        ("media_blob_set_incomplete", lambda m: m["blobs"].pop("runtime")),
        ("media_qa_not_accepted", lambda m: m["independentQa"].__setitem__("disposition","REJECTED")),
        ("media_qa_producer_mismatch", lambda m: m["independentQa"].__setitem__("acceptedMediaProducerSha","9"*40)),
        ("media_qa_ci_mismatch", lambda m: m["independentQa"].__setitem__("acceptedMediaCiRunId",1)),
        ("media_qa_artifact_mismatch", lambda m: m["independentQa"].__setitem__("acceptedMediaArtifactId",1)),
        ("media_qa_digest_mismatch", lambda m: m["independentQa"].__setitem__("acceptedMediaArtifactDigest","sha256:"+"9"*64)),
        ("media_qa_contract_mismatch", lambda m: m["independentQa"].__setitem__("acceptedMediaContract","media.other.v1")),
    ]:
        def run(mut=mut):
            m=accepted_media_fixture(); mut(m); validate_media_authority(m,require_accepted=True)
        record(name,run)

    source_sha, source_size, brief_digest=fixture_inputs()
    authority=authority_envelope()
    ledger=DriverLedger(root/"ledger",source_sha256=source_sha,source_size=source_size,brief_digest=brief_digest,mode="fixture",authority=authority)
    record("ledger_source_drift", lambda: DriverLedger(root/"ledger",source_sha256="0"*64,source_size=source_size,brief_digest=brief_digest,mode="fixture",authority=authority))
    record("ledger_brief_drift", lambda: DriverLedger(root/"ledger",source_sha256=source_sha,source_size=source_size,brief_digest="0"*64,mode="fixture",authority=authority))
    def corrupt():
        p=root/"ledger-corrupt"; l=DriverLedger(p,source_sha256=source_sha,source_size=source_size,brief_digest=brief_digest,mode="fixture",authority=authority)
        lines=l.path.read_text().splitlines(); e=json.loads(lines[0]); e["newState"]["state"]="BROKEN"; l.path.write_text(json.dumps(e)+"\n")
        DriverLedger(p)
    record("ledger_event_corruption",corrupt)

    def duplicate_candidates():
        p=root/"dup"; l=DriverLedger(p,source_sha256=source_sha,source_size=source_size,brief_digest=brief_digest,mode="fixture",authority=authority)
        verify_authorities(l,require_accepted_media=False)
        c=[_candidate(l.state["sessionId"],0,source_sha)]*3
        if len({x["renderSha256"] for x in c}) != len(c): raise StateError("candidate bytes are not distinct")
    record("candidate_duplicate_bytes",duplicate_candidates)

    def stale_review():
        p=root/"stale"; l=DriverLedger(p,source_sha256=source_sha,source_size=source_size,brief_digest=brief_digest,mode="fixture",authority=authority)
        verify_authorities(l,require_accepted_media=False); generate_fixture_candidates(l); ingest_fixture_review(l)
        l.state["review"]["reviewedRenderSha256"]="0"*64; apply_fixture_reedit(l)
    record("review_stale_render",stale_review)

    def unsupported():
        p=root/"unsupported"; l=DriverLedger(p,source_sha256=source_sha,source_size=source_size,brief_digest=brief_digest,mode="fixture",authority=authority)
        verify_authorities(l,require_accepted_media=False); generate_fixture_candidates(l); ingest_fixture_review(l)
        l.state["review"]["directive"]["operation"]="delete_everything"; apply_fixture_reedit(l)
    record("unsupported_directive",unsupported)

    def overflow():
        p=root/"overflow"; l=DriverLedger(p,source_sha256=source_sha,source_size=source_size,brief_digest=brief_digest,mode="fixture",authority=authority)
        verify_authorities(l,require_accepted_media=False); generate_fixture_candidates(l); ingest_fixture_review(l)
        l.state["reeditRound"]=MAX_REEDIT_ROUNDS; apply_fixture_reedit(l)
    record("reedit_round_overflow",overflow)

    proof_ledger=DriverLedger(root/"proof",source_sha256=source_sha,source_size=source_size,brief_digest=brief_digest,mode="fixture",authority=authority)
    resume_fixture(proof_ledger)
    proof=proof_ledger.state["proof"]
    def proof_pred():
        p=_clone(proof); p["nodes"][1]["predecessorDigest"]="0"*64; verify_proof_graph(p)
    record("proof_predecessor_tamper",proof_pred)
    def proof_ev():
        p=_clone(proof); p["nodes"][0]["evidence"]["briefDigest"]="0"*64; verify_proof_graph(p)
    record("proof_evidence_tamper",proof_ev)
    def proof_live():
        p=_clone(proof); p["nodes"][-1]["evidence"]["liveAuthorization"]=True
        p["nodes"][-1]["evidenceDigest"]=_sha(p["nodes"][-1]["evidence"])
        p["nodes"][-1]["nodeDigest"]=_sha({**p["nodes"][-1],"nodeDigest":""})
        p["finalDigest"]=p["nodes"][-1]["nodeDigest"]; verify_proof_graph(p)
    record("proof_live_authorization_tamper",proof_live)

    def escrow_hash():
        p=root/"escrow"; l=DriverLedger(p,source_sha256=source_sha,source_size=source_size,brief_digest=brief_digest,mode="fixture",authority=authority)
        verify_authorities(l,require_accepted_media=False); generate_fixture_candidates(l); ingest_fixture_review(l); apply_fixture_reedit(l); select_fixture_winner(l); build_and_verify_proof_graph(l)
        l.state["winner"]["renderSha256"]="0"*64
        escrow_fixture_release(l)
    record("escrow_winner_hash_tamper",escrow_hash)

    def replay_conflict():
        p=root/"replay"; l=DriverLedger(p,source_sha256=source_sha,source_size=source_size,brief_digest=brief_digest,mode="fixture",authority=authority)
        verify_authorities(l,require_accepted_media=False)
        l._append(event_key="authorities",event_type="AUTHORITIES_VERIFIED",request={"changed":True},new_state=l.state)
    record("fixture_replay_conflict",replay_conflict)
    record("local_source_missing",lambda: prepare_local_run(source_path=root/"missing.mp4",brief="x",out_dir=root/"local",media_authority=accepted_media_fixture()))

    missing=set(ADVERSARIAL_CASES)-set(results)
    if missing:
        raise AssertionError(f"missing adversarial cases: {sorted(missing)}")
    return {
        "caseCount": len(results),
        "allCasesPassed": all(item["passed"] for item in results.values()),
        "cases": results,
    }


def run_evidence(out_dir: str | os.PathLike[str]) -> dict[str, Any]:
    root=Path(out_dir); root.mkdir(parents=True,exist_ok=True)
    rehearsal=run_fixture_rehearsal(root/"fixture")
    adversarial=run_adversarial_cases(root/"adversarial")
    result={
        "contractVersion":"creator.local_integration_evidence.r37.v1",
        "state":"SOURCE_READY_WAITING_ACCEPTED_MEDIA",
        "fixtureState":rehearsal["state"],
        "fixtureDisposition":rehearsal["finalDisposition"],
        "actualLocalPcE2EExecuted":False,
        "mediaRequired":True,
        "mediaAccepted":False,
        "adversarialCaseCount":adversarial["caseCount"],
        "allAdversarialCasesPassed":adversarial["allCasesPassed"],
        "providerEffects":0,
        "networkEffects":0,
        "liveAuthorization":False,
        "rehearsalDigest":rehearsal["reportDigest"],
        "authorityDigest":authority_envelope()["authorityDigest"],
    }
    result["evidenceDigest"]=_sha(result)
    (root/"evidence-summary.r37.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    (root/"adversarial-cases.r37.json").write_text(json.dumps(adversarial,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return result


def _load_json(path: str | os.PathLike[str]) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(prog="creator-local-integration-r37")
    sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("readiness"); p.add_argument("--out")
    p=sub.add_parser("status"); p.add_argument("--out")
    p=sub.add_parser("fixture-rehearsal"); p.add_argument("--out",required=True)
    p=sub.add_parser("evidence"); p.add_argument("--out",required=True)
    p=sub.add_parser("run")
    p.add_argument("--source",required=True)
    p.add_argument("--brief",required=True)
    p.add_argument("--media-authority")
    p.add_argument("--out",required=True)
    return parser


def main(argv: Sequence[str] | None=None) -> int:
    args=_parser().parse_args(argv)
    if args.command=="readiness":
        value=readiness(); exit_code=0
    elif args.command=="status":
        value=blocked_local_status(); exit_code=0
    elif args.command=="fixture-rehearsal":
        value=run_fixture_rehearsal(args.out); exit_code=0
    elif args.command=="evidence":
        value=run_evidence(args.out); exit_code=0
    else:
        media=_load_json(args.media_authority) if args.media_authority else None
        try:
            value=prepare_local_run(source_path=args.source,brief=args.brief,out_dir=args.out,media_authority=media)
            exit_code=0
        except MediaAuthorityRequired as exc:
            value=blocked_local_status()
            value["error"]=str(exc)
            exit_code=3
    if getattr(args,"out",None) and args.command in {"readiness","status"}:
        Path(args.out).write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(value,sort_keys=True))
    return exit_code


if __name__=="__main__":
    raise SystemExit(main())
