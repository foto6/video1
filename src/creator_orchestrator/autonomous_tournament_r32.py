from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import autonomous_reels as reels

CONTRACT_VERSION = "creator.autonomous_tournament.r32.v1"
LEDGER_VERSION = "creator.autonomous_tournament_ledger.r32.v1"
STATUS_VERSION = "creator.autonomous_tournament_status.r32.v1"
REHEARSAL_VERSION = "creator.autonomous_tournament_chaos_rehearsal.r32.v1"
EVIDENCE_VERSION = "creator.autonomous_tournament_evidence.r32.v1"
CREATOR_BASE_SHA = "ed6959472ac958b4f5a8dcae5cee38e7430372d1"
CREATOR_BASE_CI = 37196521535
MAX_REEDIT_ROUNDS = 2
MAX_REVIEW_ROUNDS = 3
REVIEWER_COUNT = 3

CURRENT_AUTHORITIES = {
    "mediaR24": {
        "repository": "foto6/video2",
        "producerSha": "244acdf154741e669991b17df3ef2a47e2dfdfa9",
        "ciRunId": 37195239582,
        "contract": "media.canonical_live_review_export.r24.v1",
        "blobs": {
            "contract": "e63a7d712f85ad5335e89c9a23c617d178baf2ea",
            "schema": "79ab876b27143fe9939c90ea7e075b42243285ba",
            "manifest": "d2d22ca2fb9300053fe58fe5a7c56a517bd18aaa",
            "implementation": "6ac715d57cb5ec37792a84190ec481c0f7194a77",
            "exporter": "13552bc37ce752b3980396f49ed503c0c744c587",
            "verifier": "b01cfab99ffb6a39a6edcc3a29af491d7fb42e9c",
        },
    },
    "growthR29": {
        "repository": "foto6/video3",
        "producerSha": "3e4a8ad6d73b058c953abeadba7a60abe567adbc",
        "ciRunId": 37195373334,
        "contract": "growth.exact_session_ingest.r29.v1",
        "blobs": {
            "contract": "402ca7aed9b2d5a17ac9a1e79e751d3ccb376b5c",
            "authorityProfiles": "5f59d52d9768b0489ff7655bf90fe0982d7523d8",
            "implementation": "cfd3a3e8788775b754a2a94af37baa88e7957dc8",
            "fixture": "f019742318f4f368b6d1b60e9a82bcee90989e3a",
        },
    },
    "bridgeR34": {
        "repository": "foto6/WebAIBridge",
        "producerSha": "4e2a37545cc0cdd940cf6e86d40e0d620d6c94ae",
        "ciRunId": 37196102639,
        "contract": "bridge.r34_sticky_chat_exact_id.v1",
        "blobs": {
            "workflow": "1677f17e9c55be18b2b1bc8c1d4eb25431ecd906",
            "routing": "0e72ccb822f4e5fd9f29bc8ef17ccec70aeb78da",
            "rehearsal": "9a8cad3627a3d0d429897cf09d263dae97e8209e",
            "readiness": "e4cf0ba13e9b51a978f61ac9bac33b9d08ee3bcc",
        },
    },
}

NEXT_WAVE = {
    "mediaR25": {
        "expectedContract": "media.multicandidate_round.r25.v1",
        "observedProducerSha": "244acdf154741e669991b17df3ef2a47e2dfdfa9",
        "observedCiRunId": 37195239582,
        "contractPresent": False,
    },
    "growthR30": {
        "expectedContract": "growth.consensus_review.r30.v1",
        "observedProducerSha": "3e4a8ad6d73b058c953abeadba7a60abe567adbc",
        "observedCiRunId": 37195373334,
        "contractPresent": False,
    },
    "bridgeR35": {
        "expectedContract": "bridge.multiagent_dispatch.r35.v1",
        "observedProducerSha": "4e2a37545cc0cdd940cf6e86d40e0d620d6c94ae",
        "observedCiRunId": 37196102639,
        "contractPresent": False,
    },
}

FIXTURE_MEDIA_CONTRACT = "media.multicandidate_round.r25.v1"
FIXTURE_GROWTH_CONTRACT = "growth.consensus_review.r30.v1"
FIXTURE_BRIDGE_CONTRACT = "bridge.multiagent_dispatch.r35.v1"
ALLOWED_DIRECTIVES = {
    "trim_span",
    "move_cut",
    "reframe_subject",
    "caption_emphasis",
    "audio_mix",
}


class TournamentError(ValueError):
    pass


class AuthorityDrift(TournamentError):
    pass


class StateConflict(TournamentError):
    pass


class ReplayConflict(TournamentError):
    pass


class RoundOverflow(TournamentError):
    pass


class ReconciliationRequired(TournamentError):
    pass


class NonPublishable(TournamentError):
    pass


class LostAck(RuntimeError):
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
        raise TournamentError(f"{field} must be lowercase {size}-hex")
    return value


def _positive(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TournamentError(f"{field} must be positive integer")
    return value


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TournamentError(f"{field} must be non-empty")
    return value


def authority_profiles() -> dict[str, Any]:
    value = {
        "contractVersion": "creator.autonomous_tournament_authorities.r32.v1",
        "current": _clone(CURRENT_AUTHORITIES),
        "nextWave": _clone(NEXT_WAVE),
    }
    value["authorityDigest"] = _sha(value)
    return value


AUTHORITY_DIGEST = authority_profiles()["authorityDigest"]


def next_wave_status() -> str:
    return (
        "FULL_NEXT_WAVE_PINNED"
        if all(item["contractPresent"] for item in NEXT_WAVE.values())
        else "AUTONOMOUS_LOOP_SOURCE_READY"
    )


def readiness() -> dict[str, Any]:
    missing = [
        {
            "authority": name,
            "expectedContract": value["expectedContract"],
            "observedProducerSha": value["observedProducerSha"],
            "observedCiRunId": value["observedCiRunId"],
        }
        for name, value in NEXT_WAVE.items()
        if not value["contractPresent"]
    ]
    value = {
        "reportVersion": "creator.autonomous_tournament.r32.readiness.v1",
        "creatorBaseSha": CREATOR_BASE_SHA,
        "creatorBaseCiRunId": CREATOR_BASE_CI,
        "status": next_wave_status(),
        "SOURCE_READY": True,
        "FULL_NEXT_WAVE_PINNED": not missing,
        "blockers": (
            []
            if not missing
            else [{"code": "WAITING_UPSTREAM_GREEN", "missing": missing}]
        ),
        "currentAuthorities": _clone(CURRENT_AUTHORITIES),
        "nextWave": _clone(NEXT_WAVE),
        "authorityDigest": AUTHORITY_DIGEST,
        "bounds": {
            "candidateCount": {"minimum": 2, "maximum": 4},
            "reviewersPerRound": REVIEWER_COUNT,
            "reviewRounds": {"minimum": 0, "maximum": 2},
            "maxTargetedReedits": MAX_REEDIT_ROUNDS,
        },
        "safety": {
            "browserMutation": False,
            "providerMutation": False,
            "livePublish": False,
            "humanGroundTruthClaimed": False,
            "blindRetryAfterUnknownSend": False,
            "branchAuthorityTrusted": False,
        },
    }
    value["reportDigest"] = _sha(value)
    return value


def _state_digest(state: Mapping[str, Any]) -> str:
    return _sha(state)


class TournamentLedger:
    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        source_sha256: str | None = None,
        source_size: int | None = None,
        source_duration_ms: int | None = None,
        brief_digest: str | None = None,
        authorities: Mapping[str, Any] | None = None,
    ) -> None:
        self.path = Path(path)
        self.events: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        self.state: dict[str, Any] = {}
        if self.path.exists():
            self._load()
            if authorities is not None:
                if _sha(authorities) != self.state["authorityDigest"]:
                    raise AuthorityDrift("frozen session authority changed")
            if source_sha256 is not None and source_sha256 != self.state["source"]["sha256"]:
                raise StateConflict("session source SHA changed")
            if brief_digest is not None and brief_digest != self.state["briefDigest"]:
                raise StateConflict("session brief digest changed")
            return
        if source_sha256 is None or source_size is None or source_duration_ms is None or brief_digest is None:
            raise TournamentError("new ledger requires immutable source and brief identity")
        _hex(source_sha256, 64, "source_sha256")
        _positive(source_size, "source_size")
        _positive(source_duration_ms, "source_duration_ms")
        _hex(brief_digest, 64, "brief_digest")
        frozen = authority_profiles() if authorities is None else _clone(authorities)
        authority_digest = _sha(frozen)
        session_id = "r32s:" + _sha(
            {
                "sourceSha256": source_sha256,
                "briefDigest": brief_digest,
                "authorityDigest": authority_digest,
            }
        )
        tournament_id = "r32t:" + _sha({"sessionId": session_id, "kind": "autonomous_tournament"})
        initial = {
            "contractVersion": CONTRACT_VERSION,
            "sessionId": session_id,
            "tournamentId": tournament_id,
            "state": "SOURCE_READY",
            "source": {
                "sha256": source_sha256,
                "size": source_size,
                "durationMs": source_duration_ms,
            },
            "briefDigest": brief_digest,
            "authorityDigest": authority_digest,
            "reviewRound": 0,
            "reeditRound": 0,
            "candidatePackageDigest": None,
            "candidateIds": [],
            "dispatches": {},
            "consensusDigest": None,
            "selectedCandidateId": None,
            "selectedRender": None,
            "reeditApplicationDigest": None,
            "publishHandoffDigest": None,
            "reconciliationRequired": False,
            "blockers": [],
        }
        self._append(
            event_key="session:create",
            event_type="SESSION_CREATED",
            operation_id="op:" + _sha({"sessionId": session_id, "action": "create"}),
            request={"initialState": initial, "authorities": frozen},
            new_state=initial,
            input_artifacts={"sourceSha256": source_sha256, "briefDigest": brief_digest},
            output_artifacts={"sessionIdDigest": _sha(session_id)},
            timestamp_metadata="2026-10-04T00:00:00Z",
            previous_state={},
        )

    def _load(self) -> None:
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise StateConflict(f"invalid ledger JSON at line {line_number}") from exc
            required = {
                "ledgerVersion",
                "sequence",
                "eventKey",
                "eventType",
                "operationId",
                "requestDigest",
                "previousStateDigest",
                "newStateDigest",
                "inputArtifactDigests",
                "outputArtifactDigests",
                "timestampMetadata",
                "newState",
                "eventDigest",
            }
            if set(event) != required:
                raise StateConflict("ledger event fields mismatch")
            if event["ledgerVersion"] != LEDGER_VERSION:
                raise StateConflict("ledger version mismatch")
            if event["sequence"] != len(self.events) + 1:
                raise StateConflict("ledger sequence mismatch")
            if event["eventKey"] in self.by_key:
                raise StateConflict("duplicate durable event key")
            expected_previous = _state_digest(self.state)
            if event["previousStateDigest"] != expected_previous:
                raise StateConflict("previous state digest chain mismatch")
            if event["newStateDigest"] != _state_digest(event["newState"]):
                raise StateConflict("new state digest mismatch")
            identity = {k: v for k, v in event.items() if k not in {"timestampMetadata", "eventDigest"}}
            if event["eventDigest"] != _sha(identity):
                raise StateConflict("event digest mismatch")
            self.events.append(event)
            self.by_key[event["eventKey"]] = event
            self.state = _clone(event["newState"])

    def _append(
        self,
        *,
        event_key: str,
        event_type: str,
        operation_id: str,
        request: Mapping[str, Any],
        new_state: Mapping[str, Any],
        input_artifacts: Mapping[str, Any],
        output_artifacts: Mapping[str, Any],
        timestamp_metadata: str,
        previous_state: Mapping[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        request_digest = _sha(request)
        existing = self.by_key.get(event_key)
        if existing is not None:
            if (
                existing["eventType"] != event_type
                or existing["operationId"] != operation_id
                or existing["requestDigest"] != request_digest
                or existing["inputArtifactDigests"] != _clone(input_artifacts)
                or existing["outputArtifactDigests"] != _clone(output_artifacts)
            ):
                raise ReplayConflict(f"conflicting replay for {event_key}")
            return "duplicate", _clone(existing)
        old = self.state if previous_state is None else _clone(previous_state)
        event = {
            "ledgerVersion": LEDGER_VERSION,
            "sequence": len(self.events) + 1,
            "eventKey": event_key,
            "eventType": event_type,
            "operationId": operation_id,
            "requestDigest": request_digest,
            "previousStateDigest": _state_digest(old),
            "newStateDigest": _state_digest(new_state),
            "inputArtifactDigests": _clone(input_artifacts),
            "outputArtifactDigests": _clone(output_artifacts),
            "timestampMetadata": timestamp_metadata,
            "newState": _clone(new_state),
        }
        identity = {k: v for k, v in event.items() if k != "timestampMetadata"}
        event["eventDigest"] = _sha(identity)
        self.path.parent.mkdir(parents=True, exist_ok=True)
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

    def status(self) -> dict[str, Any]:
        state = _clone(self.state)
        next_action = {
            "SOURCE_READY": "INGEST_CANDIDATE_PACKAGE",
            "CANDIDATES_READY": "DISPATCH_THREE_REVIEWS",
            "DISPATCHING": "CONTINUE_REVIEW_DISPATCH",
            "RECONCILIATION_REQUIRED": "RECONCILE_UNKNOWN_SEND",
            "REVIEWS_COMPLETE": "INGEST_CONSENSUS",
            "CONSENSUS_ACCEPTED": "EXECUTE_TARGETED_REEDIT",
            "REEDIT_APPLIED": "INGEST_NEXT_CANDIDATE_PACKAGE",
            "WINNER_READY": "EMIT_PUBLISH_HANDOFF",
            "PUBLISH_HANDOFF_READY": "STOP_NO_LIVE_PUBLISH",
            "HUMAN_REVIEW_REQUIRED": "STOP_HUMAN_REVIEW",
        }.get(state["state"], "BLOCKED")
        result = {
            "contractVersion": STATUS_VERSION,
            "sessionId": state["sessionId"],
            "tournamentId": state["tournamentId"],
            "state": state["state"],
            "reviewRound": state["reviewRound"],
            "reeditRound": state["reeditRound"],
            "blockers": state["blockers"],
            "reconciliationRequired": state["reconciliationRequired"],
            "nextPermittedAction": next_action,
            "requiredAuthorityEvidence": _clone(NEXT_WAVE),
            "overallAuthorityStatus": next_wave_status(),
            "authorityDigest": state["authorityDigest"],
            "stateDigest": _state_digest(state),
            "ledgerDigest": self.digest,
        }
        result["statusDigest"] = _sha(result)
        return result


def _candidate_material(
    *,
    session_id: str,
    review_round: int,
    ordinal: int,
    source_sha: str,
    base_sha: str | None,
) -> dict[str, Any]:
    candidate_id = "r32c:" + _sha(
        {
            "sessionId": session_id,
            "round": review_round,
            "ordinal": ordinal,
            "baseSha": base_sha,
        }
    )
    render_sha = _sha(
        {
            "candidateId": candidate_id,
            "sourceSha": source_sha,
            "round": review_round,
            "ordinal": ordinal,
        }
    )
    nodes = [
        {"nodeId": "hook", "digest": _sha({"candidateId": candidate_id, "node": "hook"})},
        {"nodeId": "body", "digest": _sha({"candidateId": candidate_id, "node": "body"})},
        {"nodeId": "captions", "digest": _sha({"candidateId": candidate_id, "node": "captions"})},
        {"nodeId": "audio", "digest": _sha({"candidateId": candidate_id, "node": "audio"})},
    ]
    graph_digest = _sha(nodes)
    return {
        "candidateId": candidate_id,
        "renderSha256": render_sha,
        "renderSize": 100000 + review_round * 1000 + ordinal * 137,
        "editGraphDeclared": True,
        "editGraphDigest": graph_digest,
        "editGraphNodes": nodes,
        "sealedToken": _sha(
            {"candidateId": candidate_id, "renderSha256": render_sha, "editGraphDigest": graph_digest}
        ),
    }


def build_fixture_candidate_package(
    ledger: TournamentLedger,
    *,
    candidate_count: int = 4,
    base_render_sha: str | None = None,
) -> dict[str, Any]:
    if not 2 <= candidate_count <= 4:
        raise TournamentError("candidate_count must be 2..4")
    state = ledger.state
    if state["reviewRound"] > 2:
        raise RoundOverflow("review round exceeds 2")
    candidates = [
        _candidate_material(
            session_id=state["sessionId"],
            review_round=state["reviewRound"],
            ordinal=i,
            source_sha=state["source"]["sha256"],
            base_sha=base_render_sha,
        )
        for i in range(candidate_count)
    ]
    mapping = [
        {
            "candidateId": item["candidateId"],
            "sealedToken": item["sealedToken"],
            "renderSha256": item["renderSha256"],
        }
        for item in candidates
    ]
    package = {
        "contractVersion": FIXTURE_MEDIA_CONTRACT,
        "sourceClass": "frozen_contract_fixture",
        "targetAuthority": "mediaR25",
        "upstreamAuthority": _clone(CURRENT_AUTHORITIES["mediaR24"]),
        "sessionId": state["sessionId"],
        "tournamentId": state["tournamentId"],
        "reviewRound": state["reviewRound"],
        "sourceSha256": state["source"]["sha256"],
        "briefDigest": state["briefDigest"],
        "baseRenderSha256": base_render_sha,
        "candidates": candidates,
        "sealedMappingDigest": _sha(mapping),
        "candidateSetDigest": _sha(candidates),
        "packageDigest": "",
        "humanGroundTruth": False,
    }
    material = copy.deepcopy(package)
    material["packageDigest"] = ""
    package["packageDigest"] = _sha(material)
    return package


def validate_candidate_package(ledger: TournamentLedger, package: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "contractVersion",
        "sourceClass",
        "targetAuthority",
        "upstreamAuthority",
        "sessionId",
        "tournamentId",
        "reviewRound",
        "sourceSha256",
        "briefDigest",
        "baseRenderSha256",
        "candidates",
        "sealedMappingDigest",
        "candidateSetDigest",
        "packageDigest",
        "humanGroundTruth",
    }
    if not isinstance(package, Mapping) or set(package) != required:
        raise TournamentError("candidate package fields mismatch")
    if package["contractVersion"] != FIXTURE_MEDIA_CONTRACT:
        raise AuthorityDrift("candidate package contract drift")
    if package["sourceClass"] != "frozen_contract_fixture":
        if not NEXT_WAVE["mediaR25"]["contractPresent"]:
            raise AuthorityDrift("Media R25 is not authoritative")
    if package["upstreamAuthority"] != CURRENT_AUTHORITIES["mediaR24"]:
        raise AuthorityDrift("candidate package upstream authority drift")
    state = ledger.state
    if package["sessionId"] != state["sessionId"] or package["tournamentId"] != state["tournamentId"]:
        raise StateConflict("candidate package session drift")
    if package["reviewRound"] != state["reviewRound"]:
        raise RoundOverflow("candidate package round drift")
    if package["sourceSha256"] != state["source"]["sha256"]:
        raise StateConflict("candidate package stale source")
    if package["briefDigest"] != state["briefDigest"]:
        raise StateConflict("candidate package brief drift")
    candidates = package["candidates"]
    if not isinstance(candidates, list) or not 2 <= len(candidates) <= 4:
        raise TournamentError("candidate package count must be 2..4")
    ids: set[str] = set()
    renders: set[str] = set()
    mapping = []
    for item in candidates:
        if not isinstance(item, Mapping) or set(item) != {
            "candidateId",
            "renderSha256",
            "renderSize",
            "editGraphDeclared",
            "editGraphDigest",
            "editGraphNodes",
            "sealedToken",
        }:
            raise TournamentError("candidate fields mismatch")
        cid = _nonempty(item["candidateId"], "candidateId")
        render_sha = _hex(item["renderSha256"], 64, "candidate.renderSha256")
        if cid in ids:
            raise StateConflict("duplicate candidate id")
        if render_sha in renders:
            raise StateConflict("duplicate candidate bytes")
        ids.add(cid)
        renders.add(render_sha)
        _positive(item["renderSize"], "candidate.renderSize")
        if item["editGraphDeclared"] is not True:
            raise StateConflict("undeclared edit graph")
        if not isinstance(item["editGraphNodes"], list) or not item["editGraphNodes"]:
            raise StateConflict("edit graph nodes missing")
        if item["editGraphDigest"] != _sha(item["editGraphNodes"]):
            raise StateConflict("edit graph digest drift")
        expected_token = _sha(
            {
                "candidateId": cid,
                "renderSha256": render_sha,
                "editGraphDigest": item["editGraphDigest"],
            }
        )
        if item["sealedToken"] != expected_token:
            raise StateConflict("tampered sealed mapping token")
        mapping.append(
            {"candidateId": cid, "sealedToken": expected_token, "renderSha256": render_sha}
        )
    if package["sealedMappingDigest"] != _sha(mapping):
        raise StateConflict("swapped/tampered sealed mapping")
    if package["candidateSetDigest"] != _sha(candidates):
        raise StateConflict("candidate set digest drift")
    material = copy.deepcopy(package)
    digest = material["packageDigest"]
    material["packageDigest"] = ""
    _hex(digest, 64, "packageDigest")
    if _sha(material) != digest:
        raise StateConflict("candidate package digest mismatch")
    if package["humanGroundTruth"] is not False:
        raise TournamentError("candidate package cannot claim human ground truth")
    return _clone(package)


def ingest_candidate_package(ledger: TournamentLedger, package: Mapping[str, Any]) -> dict[str, Any]:
    package = validate_candidate_package(ledger, package)
    state = ledger.state
    allowed = "SOURCE_READY" if state["reviewRound"] == 0 else "REEDIT_APPLIED"
    if state["state"] != allowed:
        key = f"candidate-package:r{package['reviewRound']}"
        existing = ledger.by_key.get(key)
        if existing and existing["requestDigest"] == _sha(package):
            return _clone(existing["newState"])
        raise StateConflict(f"candidate package illegal from {state['state']}")
    new = _clone(state)
    new.update(
        {
            "state": "CANDIDATES_READY",
            "candidatePackageDigest": package["packageDigest"],
            "candidateIds": [item["candidateId"] for item in package["candidates"]],
            "dispatches": {},
            "consensusDigest": None,
            "selectedCandidateId": None,
            "selectedRender": None,
            "reconciliationRequired": False,
            "blockers": [],
        }
    )
    key = f"candidate-package:r{package['reviewRound']}"
    ledger._append(
        event_key=key,
        event_type="CANDIDATE_PACKAGE_PERSISTED",
        operation_id="op:" + _sha({"key": key, "packageDigest": package["packageDigest"]}),
        request=package,
        new_state=new,
        input_artifacts={
            "sourceSha256": package["sourceSha256"],
            "briefDigest": package["briefDigest"],
        },
        output_artifacts={
            "packageDigest": package["packageDigest"],
            "candidateSetDigest": package["candidateSetDigest"],
            "sealedMappingDigest": package["sealedMappingDigest"],
        },
        timestamp_metadata="2026-10-04T00:00:01Z",
    )
    return _clone(new)


class FixtureDispatchAdapter:
    def __init__(self) -> None:
        self.effects: dict[str, dict[str, Any]] = {}
        self.effect_count = 0

    def recover(self, operation_id: str) -> dict[str, Any] | None:
        value = self.effects.get(operation_id)
        return None if value is None else _clone(value)

    def send(
        self,
        *,
        operation_id: str,
        conversation_id: str,
        prompt_digest: str,
        package_digest: str,
        lose_ack: bool = False,
    ) -> dict[str, Any]:
        payload_identity = {
            "conversationId": conversation_id,
            "promptDigest": prompt_digest,
            "packageDigest": package_digest,
        }
        existing = self.effects.get(operation_id)
        if existing is not None:
            if existing["requestIdentity"] != payload_identity:
                raise ReplayConflict("same operation id changed prompt/package")
            return _clone(existing)
        capture = {
            "contractVersion": FIXTURE_BRIDGE_CONTRACT,
            "sourceClass": "frozen_contract_fixture",
            "upstreamAuthority": _clone(CURRENT_AUTHORITIES["bridgeR34"]),
            "operationId": operation_id,
            "conversationId": conversation_id,
            "requestIdentity": payload_identity,
            "captureDigest": _sha(
                {"operationId": operation_id, "requestIdentity": payload_identity, "capture": "model-response"}
            ),
            "assistantResponseDigest": _sha(
                {"operationId": operation_id, "response": "review-fixture"}
            ),
            "modelEvidence": False,
            "humanGroundTruth": False,
        }
        self.effects[operation_id] = _clone(capture)
        self.effect_count += 1
        if lose_ack:
            raise LostAck("fixture Send accepted before acknowledgement")
        return _clone(capture)


def _dispatch_identity(ledger: TournamentLedger, reviewer_index: int, conversation_id: str) -> dict[str, Any]:
    state = ledger.state
    if not 0 <= reviewer_index < REVIEWER_COUNT:
        raise TournamentError("reviewer index must be 0..2")
    _nonempty(conversation_id, "conversation_id")
    prompt_digest = _sha(
        {
            "sessionId": state["sessionId"],
            "round": state["reviewRound"],
            "reviewerIndex": reviewer_index,
            "candidatePackageDigest": state["candidatePackageDigest"],
            "instruction": "independent blinded review",
        }
    )
    operation_id = "r32send:" + _sha(
        {
            "sessionId": state["sessionId"],
            "round": state["reviewRound"],
            "reviewerIndex": reviewer_index,
            "conversationId": conversation_id,
            "packageDigest": state["candidatePackageDigest"],
        }
    )
    return {
        "reviewerIndex": reviewer_index,
        "conversationId": conversation_id,
        "promptDigest": prompt_digest,
        "operationId": operation_id,
        "packageDigest": state["candidatePackageDigest"],
    }


def _record_dispatch_ack(
    ledger: TournamentLedger,
    identity: Mapping[str, Any],
    capture: Mapping[str, Any],
) -> dict[str, Any]:
    state = ledger.state
    if capture["operationId"] != identity["operationId"]:
        raise StateConflict("capture operation mismatch")
    if capture["conversationId"] != identity["conversationId"]:
        raise StateConflict("capture conversation mismatch")
    if capture["requestIdentity"] != {
        "conversationId": identity["conversationId"],
        "promptDigest": identity["promptDigest"],
        "packageDigest": identity["packageDigest"],
    }:
        raise StateConflict("capture request identity drift")
    new = _clone(state)
    dispatches = _clone(new["dispatches"])
    dispatches[str(identity["reviewerIndex"])] = {
        **_clone(identity),
        "captureDigest": capture["captureDigest"],
        "assistantResponseDigest": capture["assistantResponseDigest"],
        "state": "ACKNOWLEDGED",
    }
    new["dispatches"] = dispatches
    new["reconciliationRequired"] = False
    new["blockers"] = []
    new["state"] = (
        "REVIEWS_COMPLETE"
        if len(dispatches) == REVIEWER_COUNT
        and all(item["state"] == "ACKNOWLEDGED" for item in dispatches.values())
        else "DISPATCHING"
    )
    key = f"dispatch-ack:r{state['reviewRound']}:i{identity['reviewerIndex']}"
    ledger._append(
        event_key=key,
        event_type="REVIEW_DISPATCH_ACKNOWLEDGED",
        operation_id=identity["operationId"],
        request={"identity": identity, "capture": capture},
        new_state=new,
        input_artifacts={
            "packageDigest": identity["packageDigest"],
            "promptDigest": identity["promptDigest"],
        },
        output_artifacts={
            "captureDigest": capture["captureDigest"],
            "assistantResponseDigest": capture["assistantResponseDigest"],
        },
        timestamp_metadata="2026-10-04T00:00:03Z",
    )
    return _clone(new)


def dispatch_review(
    ledger: TournamentLedger,
    *,
    reviewer_index: int,
    conversation_id: str,
    adapter: FixtureDispatchAdapter,
    lose_ack: bool = False,
) -> dict[str, Any]:
    state = ledger.state
    if state["reconciliationRequired"]:
        raise ReconciliationRequired("unresolved Send blocks new dispatch")
    if state["state"] not in {"CANDIDATES_READY", "DISPATCHING"}:
        ack_key = f"dispatch-ack:r{state['reviewRound']}:i{reviewer_index}"
        if ack_key in ledger.by_key:
            return _clone(ledger.by_key[ack_key]["newState"])
        raise StateConflict(f"review dispatch illegal from {state['state']}")
    identity = _dispatch_identity(ledger, reviewer_index, conversation_id)
    ack_key = f"dispatch-ack:r{state['reviewRound']}:i{reviewer_index}"
    if ack_key in ledger.by_key:
        existing = ledger.by_key[ack_key]
        if existing["operationId"] != identity["operationId"]:
            raise ReplayConflict("dispatch replay identity changed")
        return _clone(existing["newState"])
    intent_key = f"dispatch-intent:r{state['reviewRound']}:i{reviewer_index}"
    intent_state = _clone(state)
    intent_state["state"] = "DISPATCHING"
    ledger._append(
        event_key=intent_key,
        event_type="REVIEW_DISPATCH_INTENT",
        operation_id=identity["operationId"],
        request=identity,
        new_state=intent_state,
        input_artifacts={
            "packageDigest": identity["packageDigest"],
            "promptDigest": identity["promptDigest"],
        },
        output_artifacts={},
        timestamp_metadata="2026-10-04T00:00:02Z",
    )
    recovered = adapter.recover(identity["operationId"])
    if recovered is not None:
        return _record_dispatch_ack(ledger, identity, recovered)
    try:
        capture = adapter.send(
            operation_id=identity["operationId"],
            conversation_id=identity["conversationId"],
            prompt_digest=identity["promptDigest"],
            package_digest=identity["packageDigest"],
            lose_ack=lose_ack,
        )
    except LostAck:
        unknown = _clone(ledger.state)
        unknown["state"] = "RECONCILIATION_REQUIRED"
        unknown["reconciliationRequired"] = True
        unknown["blockers"] = [
            {
                "code": "RECONCILIATION_REQUIRED",
                "operationId": identity["operationId"],
                "reviewerIndex": reviewer_index,
            }
        ]
        ledger._append(
            event_key=f"dispatch-unknown:r{state['reviewRound']}:i{reviewer_index}",
            event_type="REVIEW_DISPATCH_UNKNOWN",
            operation_id=identity["operationId"],
            request=identity,
            new_state=unknown,
            input_artifacts={
                "packageDigest": identity["packageDigest"],
                "promptDigest": identity["promptDigest"],
            },
            output_artifacts={},
            timestamp_metadata="2026-10-04T00:00:03Z",
        )
        return _clone(unknown)
    return _record_dispatch_ack(ledger, identity, capture)


def reconcile_dispatch(
    ledger: TournamentLedger,
    *,
    reviewer_index: int,
    conversation_id: str,
    adapter: FixtureDispatchAdapter,
) -> dict[str, Any]:
    state = ledger.state
    if state["state"] != "RECONCILIATION_REQUIRED":
        raise StateConflict("reconciliation is not required")
    identity = _dispatch_identity(ledger, reviewer_index, conversation_id)
    blocker = state["blockers"][0] if state["blockers"] else {}
    if blocker.get("operationId") != identity["operationId"]:
        raise ReplayConflict("reconciliation operation changed")
    capture = adapter.recover(identity["operationId"])
    if capture is None:
        raise ReconciliationRequired("authoritative recovery has no result yet")
    return _record_dispatch_ack(ledger, identity, capture)


def build_fixture_consensus(
    ledger: TournamentLedger,
    *,
    decision: str,
    selected_candidate_id: str | None,
    directives: Sequence[Mapping[str, Any]] = (),
    consensus_state: str = "CONSENSUS_ACCEPTED",
) -> dict[str, Any]:
    state = ledger.state
    captures = [
        state["dispatches"][str(i)]["captureDigest"] for i in range(REVIEWER_COUNT)
    ]
    result = {
        "contractVersion": FIXTURE_GROWTH_CONTRACT,
        "sourceClass": "frozen_contract_fixture",
        "targetAuthority": "growthR30",
        "upstreamAuthority": _clone(CURRENT_AUTHORITIES["growthR29"]),
        "sessionId": state["sessionId"],
        "tournamentId": state["tournamentId"],
        "reviewRound": state["reviewRound"],
        "candidatePackageDigest": state["candidatePackageDigest"],
        "captureDigests": captures,
        "captureSetDigest": _sha(captures),
        "consensusState": consensus_state,
        "decision": decision,
        "selectedCandidateId": selected_candidate_id,
        "directives": [_clone(item) for item in directives],
        "humanGroundTruth": False,
        "consensusDigest": "",
    }
    material = copy.deepcopy(result)
    material["consensusDigest"] = ""
    result["consensusDigest"] = _sha(material)
    return result


def validate_consensus(ledger: TournamentLedger, result: Mapping[str, Any]) -> dict[str, Any]:
    if ledger.state["reconciliationRequired"]:
        raise ReconciliationRequired("consensus blocked by unresolved Send")
    if ledger.state["state"] != "REVIEWS_COMPLETE":
        raise StateConflict("consensus requires three acknowledged reviews")
    required = {
        "contractVersion",
        "sourceClass",
        "targetAuthority",
        "upstreamAuthority",
        "sessionId",
        "tournamentId",
        "reviewRound",
        "candidatePackageDigest",
        "captureDigests",
        "captureSetDigest",
        "consensusState",
        "decision",
        "selectedCandidateId",
        "directives",
        "humanGroundTruth",
        "consensusDigest",
    }
    if not isinstance(result, Mapping) or set(result) != required:
        raise TournamentError("consensus fields mismatch")
    if result["contractVersion"] != FIXTURE_GROWTH_CONTRACT:
        raise AuthorityDrift("consensus contract drift")
    if result["sourceClass"] != "frozen_contract_fixture" and not NEXT_WAVE["growthR30"]["contractPresent"]:
        raise AuthorityDrift("Growth R30 is not authoritative")
    if result["upstreamAuthority"] != CURRENT_AUTHORITIES["growthR29"]:
        raise AuthorityDrift("Growth consensus authority drift")
    state = ledger.state
    if (
        result["sessionId"] != state["sessionId"]
        or result["tournamentId"] != state["tournamentId"]
        or result["reviewRound"] != state["reviewRound"]
        or result["candidatePackageDigest"] != state["candidatePackageDigest"]
    ):
        raise StateConflict("consensus session/round/package drift")
    expected = [state["dispatches"][str(i)]["captureDigest"] for i in range(REVIEWER_COUNT)]
    if len(set(result["captureDigests"])) != REVIEWER_COUNT:
        raise StateConflict("duplicate review capture")
    if result["captureDigests"] != expected or result["captureSetDigest"] != _sha(expected):
        raise StateConflict("consensus capture set mismatch")
    if result["humanGroundTruth"] is not False:
        raise TournamentError("consensus cannot claim human ground truth")
    material = copy.deepcopy(result)
    digest = material["consensusDigest"]
    material["consensusDigest"] = ""
    if _sha(material) != digest:
        raise StateConflict("consensus digest mismatch")
    if result["consensusState"] not in {"CONSENSUS_ACCEPTED", "HUMAN_REVIEW_REQUIRED"}:
        raise TournamentError("consensus state invalid")
    if result["consensusState"] != "CONSENSUS_ACCEPTED":
        if result["decision"] not in {"human_review", "tie", "insufficient_evidence"}:
            raise NonPublishable("non-accepted consensus cannot execute")
        return _clone(result)
    if result["decision"] not in {"targeted_reedit", "winner"}:
        raise TournamentError("accepted consensus decision invalid")
    if result["selectedCandidateId"] not in state["candidateIds"]:
        raise StateConflict("selected candidate not in current package")
    if result["decision"] == "targeted_reedit":
        if not result["directives"]:
            raise TournamentError("targeted re-edit requires directives")
        if state["reeditRound"] >= MAX_REEDIT_ROUNDS:
            raise RoundOverflow("third targeted re-edit forbidden")
        for directive in result["directives"]:
            _validate_directive(directive, state["source"]["durationMs"])
    elif result["directives"]:
        raise TournamentError("winner consensus must not carry edit directives")
    return _clone(result)


def _validate_directive(value: Mapping[str, Any], duration_ms: int) -> dict[str, Any]:
    required = {"directiveId", "operation", "startMs", "endMs", "targetNode", "parameters"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise TournamentError("directive fields mismatch")
    _nonempty(value["directiveId"], "directiveId")
    if value["operation"] not in ALLOWED_DIRECTIVES:
        raise TournamentError("unsupported re-edit directive")
    start = value["startMs"]
    end = value["endMs"]
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or start < 0
        or end <= start
        or end > duration_ms
    ):
        raise TournamentError("directive timestamp out of bounds")
    _nonempty(value["targetNode"], "targetNode")
    if not isinstance(value["parameters"], Mapping):
        raise TournamentError("directive parameters must be object")
    return _clone(value)


def ingest_consensus(ledger: TournamentLedger, result: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise TournamentError("consensus must be object")
    round_index = result.get("reviewRound")
    key = f"consensus:r{round_index}"
    existing = ledger.by_key.get(key)
    if existing is not None:
        if existing["requestDigest"] != _sha(result):
            raise ReplayConflict("conflicting consensus replay")
        return _clone(existing["newState"])
    result = validate_consensus(ledger, result)
    state = ledger.state
    new = _clone(state)
    new["consensusDigest"] = result["consensusDigest"]
    new["selectedCandidateId"] = result["selectedCandidateId"]
    if result["consensusState"] != "CONSENSUS_ACCEPTED":
        new["state"] = "HUMAN_REVIEW_REQUIRED"
        new["blockers"] = [{"code": result["decision"].upper()}]
    elif result["decision"] == "targeted_reedit":
        new["state"] = "CONSENSUS_ACCEPTED"
        new["blockers"] = []
    else:
        selected_dispatch = None
        new["state"] = "WINNER_READY"
        new["blockers"] = []
        new["selectedRender"] = {"candidateId": result["selectedCandidateId"]}
    ledger._append(
        event_key=key,
        event_type="CONSENSUS_INGESTED",
        operation_id="op:" + _sha({"key": key, "consensusDigest": result["consensusDigest"]}),
        request=result,
        new_state=new,
        input_artifacts={
            "candidatePackageDigest": state["candidatePackageDigest"],
            "captureSetDigest": result["captureSetDigest"],
        },
        output_artifacts={"consensusDigest": result["consensusDigest"]},
        timestamp_metadata="2026-10-04T00:00:05Z",
    )
    return _clone(new)


class FixtureMediaReeditAdapter:
    def __init__(self) -> None:
        self.effects: dict[str, dict[str, Any]] = {}
        self.effect_count = 0

    def recover(self, operation_id: str) -> dict[str, Any] | None:
        value = self.effects.get(operation_id)
        return None if value is None else _clone(value)

    def apply(
        self,
        *,
        operation_id: str,
        selected_candidate: Mapping[str, Any],
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        existing = self.effects.get(operation_id)
        if existing is not None:
            if existing["requestDigest"] != request["requestDigest"]:
                raise ReplayConflict("same re-edit operation changed request")
            return _clone(existing)
        output_sha = _sha(
            {
                "parentRenderSha256": selected_candidate["renderSha256"],
                "requestDigest": _sha(request),
                "effect": "fixture-real-edit-compatible",
            }
        )
        value = {
            "contractVersion": "media.editorial_reedit_application.v1",
            "sourceClass": "frozen_contract_fixture",
            "upstreamAuthority": _clone(CURRENT_AUTHORITIES["mediaR24"]),
            "operationId": operation_id,
            "requestDigest": request["requestDigest"],
            "parentRenderSha256": selected_candidate["renderSha256"],
            "outputRenderSha256": output_sha,
            "outputRenderSize": selected_candidate["renderSize"] + 271,
            "applicationDigest": _sha(
                {
                    "operationId": operation_id,
                    "parent": selected_candidate["renderSha256"],
                    "output": output_sha,
                    "requestDigest": request["requestDigest"],
                }
            ),
            "humanGroundTruth": False,
        }
        self.effects[operation_id] = _clone(value)
        self.effect_count += 1
        return _clone(value)


def build_reedit_request(
    *,
    ledger: TournamentLedger,
    selected_candidate: Mapping[str, Any],
    directives: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    nodes = {item["nodeId"]: item["digest"] for item in selected_candidate["editGraphNodes"]}
    touched = set()
    normalized = []
    for item in directives:
        directive = _validate_directive(item, ledger.state["source"]["durationMs"])
        if directive["targetNode"] not in nodes:
            raise TournamentError("directive targets undeclared edit graph node")
        touched.add(directive["targetNode"])
        normalized.append(directive)
    unaffected = [
        {"nodeId": node_id, "digest": digest}
        for node_id, digest in sorted(nodes.items())
        if node_id not in touched
    ]
    request = {
        "contractVersion": "creator.autonomous_tournament_reedit_request.r32.v1",
        "sessionId": ledger.state["sessionId"],
        "tournamentId": ledger.state["tournamentId"],
        "fromReviewRound": ledger.state["reviewRound"],
        "toReviewRound": ledger.state["reviewRound"] + 1,
        "reeditRound": ledger.state["reeditRound"] + 1,
        "selectedCandidateId": selected_candidate["candidateId"],
        "parentRenderSha256": selected_candidate["renderSha256"],
        "parentEditGraphDigest": selected_candidate["editGraphDigest"],
        "directives": normalized,
        "unaffectedGraphLineage": unaffected,
        "unaffectedGraphDigest": _sha(unaffected),
        "requestDigest": "",
    }
    material = copy.deepcopy(request)
    material["requestDigest"] = ""
    request["requestDigest"] = _sha(material)
    return request


def apply_targeted_reedit(
    ledger: TournamentLedger,
    *,
    package: Mapping[str, Any],
    consensus: Mapping[str, Any],
    adapter: FixtureMediaReeditAdapter,
) -> dict[str, Any]:
    consensus_round = consensus.get("reviewRound")
    if isinstance(consensus_round, bool) or not isinstance(consensus_round, int):
        raise TournamentError("consensus reviewRound invalid")
    key = f"reedit:r{consensus_round + 1}"
    existing = ledger.by_key.get(key)
    if existing is not None:
        if existing["inputArtifactDigests"].get("consensusDigest") != consensus.get("consensusDigest"):
            raise ReplayConflict("conflicting targeted re-edit replay")
        return _clone(existing["newState"])
    state = ledger.state
    if state["state"] != "CONSENSUS_ACCEPTED":
        raise StateConflict("targeted re-edit requires accepted consensus")
    if state["reeditRound"] >= MAX_REEDIT_ROUNDS or state["reviewRound"] >= 2:
        raise RoundOverflow("targeted re-edit bound exceeded")
    selected = next(
        (
            item
            for item in package["candidates"]
            if item["candidateId"] == consensus["selectedCandidateId"]
        ),
        None,
    )
    if selected is None:
        raise StateConflict("selected candidate missing from package")
    request = build_reedit_request(
        ledger=ledger,
        selected_candidate=selected,
        directives=consensus["directives"],
    )
    operation_id = "r32edit:" + _sha(
        {
            "sessionId": state["sessionId"],
            "reeditRound": request["reeditRound"],
            "requestDigest": request["requestDigest"],
        }
    )
    recovered = adapter.recover(operation_id)
    result = (
        recovered
        if recovered is not None
        else adapter.apply(operation_id=operation_id, selected_candidate=selected, request=request)
    )
    if result["requestDigest"] != request["requestDigest"]:
        raise ReplayConflict("re-edit application request digest drift")
    if result["parentRenderSha256"] != selected["renderSha256"]:
        raise StateConflict("re-edit application parent render drift")
    if result["humanGroundTruth"] is not False:
        raise TournamentError("re-edit application human ground truth drift")
    new = _clone(state)
    new.update(
        {
            "state": "REEDIT_APPLIED",
            "reviewRound": state["reviewRound"] + 1,
            "reeditRound": state["reeditRound"] + 1,
            "reeditApplicationDigest": result["applicationDigest"],
            "selectedRender": {
                "candidateId": selected["candidateId"],
                "parentRenderSha256": selected["renderSha256"],
                "outputRenderSha256": result["outputRenderSha256"],
                "outputRenderSize": result["outputRenderSize"],
            },
            "candidatePackageDigest": None,
            "candidateIds": [],
            "dispatches": {},
            "consensusDigest": None,
            "selectedCandidateId": None,
            "blockers": [],
        }
    )
    ledger._append(
        event_key=key,
        event_type="TARGETED_REEDIT_APPLIED",
        operation_id=operation_id,
        request={"request": request, "result": result},
        new_state=new,
        input_artifacts={
            "parentRenderSha256": selected["renderSha256"],
            "consensusDigest": consensus["consensusDigest"],
            "unaffectedGraphDigest": request["unaffectedGraphDigest"],
        },
        output_artifacts={
            "applicationDigest": result["applicationDigest"],
            "outputRenderSha256": result["outputRenderSha256"],
        },
        timestamp_metadata="2026-10-04T00:00:06Z",
    )
    return _clone(new)


def emit_publish_handoff(
    ledger: TournamentLedger,
    *,
    package: Mapping[str, Any],
) -> dict[str, Any]:
    state = ledger.state
    key = f"publish-handoff:r{state['reviewRound']}"
    existing = ledger.by_key.get(key)
    if existing is not None:
        return _clone(existing["outputArtifactDigests"]["handoff"])
    if state["reconciliationRequired"]:
        raise ReconciliationRequired("publish blocked by unresolved reconciliation")
    if state["state"] != "WINNER_READY":
        raise NonPublishable(f"publish handoff forbidden from {state['state']}")
    winner_id = state["selectedCandidateId"]
    winner = next((item for item in package["candidates"] if item["candidateId"] == winner_id), None)
    if winner is None:
        raise StateConflict("winner candidate missing from package")
    handoff = {
        "contractVersion": "creator.editor_publish_handoff.v1",
        "handoffClass": "frozen_contract_fixture",
        "sessionId": state["sessionId"],
        "tournamentId": state["tournamentId"],
        "winnerCandidateId": winner_id,
        "finalArtifact": {
            "fileName": "final.mp4",
            "sha256": winner["renderSha256"],
            "size": winner["renderSize"],
        },
        "sourceSha256": state["source"]["sha256"],
        "consensusDigest": state["consensusDigest"],
        "livePublish": False,
        "providerMutation": False,
        "humanGroundTruth": False,
        "handoffDigest": "",
    }
    material = copy.deepcopy(handoff)
    material["handoffDigest"] = ""
    handoff["handoffDigest"] = _sha(material)
    new = _clone(state)
    new["state"] = "PUBLISH_HANDOFF_READY"
    new["publishHandoffDigest"] = handoff["handoffDigest"]
    ledger._append(
        event_key=key,
        event_type="PUBLISH_HANDOFF_PERSISTED",
        operation_id="r32publish:" + _sha({"sessionId": state["sessionId"], "handoffDigest": handoff["handoffDigest"]}),
        request=handoff,
        new_state=new,
        input_artifacts={
            "winnerRenderSha256": winner["renderSha256"],
            "consensusDigest": state["consensusDigest"],
        },
        output_artifacts={"handoff": handoff},
        timestamp_metadata="2026-10-04T00:00:08Z",
    )
    return _clone(handoff)


def _directive_fixture(round_index: int) -> list[dict[str, Any]]:
    return [
        {
            "directiveId": f"defect-{round_index}-hook",
            "operation": "trim_span",
            "startMs": 0,
            "endMs": 900,
            "targetNode": "hook",
            "parameters": {"removeLeadInMs": 250},
        },
        {
            "directiveId": f"defect-{round_index}-caption",
            "operation": "caption_emphasis",
            "startMs": 1100,
            "endMs": 2600,
            "targetNode": "captions",
            "parameters": {"emphasis": "proof_phrase"},
        },
    ]


def run_chaos_rehearsal(work_dir: str | os.PathLike[str]) -> dict[str, Any]:
    root = Path(work_dir)
    root.mkdir(parents=True, exist_ok=True)
    ledger_path = root / "autonomous-tournament-ledger.jsonl"
    source_sha = "a" * 64
    brief_digest = "b" * 64
    ledger = TournamentLedger(
        ledger_path,
        source_sha256=source_sha,
        source_size=790819,
        source_duration_ms=30000,
        brief_digest=brief_digest,
    )
    package0 = build_fixture_candidate_package(ledger, candidate_count=4)
    ingest_candidate_package(ledger, package0)

    # Crash after candidate package persisted, before any dispatch.
    ledger = TournamentLedger(ledger_path)
    dispatch = FixtureDispatchAdapter()
    media = FixtureMediaReeditAdapter()

    dispatch_review(
        ledger,
        reviewer_index=0,
        conversation_id="conv-r0-reviewer-0",
        adapter=dispatch,
    )
    # Crash after 1/3 dispatches.
    ledger = TournamentLedger(ledger_path)

    state = dispatch_review(
        ledger,
        reviewer_index=1,
        conversation_id="conv-r0-reviewer-1",
        adapter=dispatch,
        lose_ack=True,
    )
    if state["state"] != "RECONCILIATION_REQUIRED":
        raise AssertionError("lost acknowledgement did not halt the loop")
    blocked_consensus = False
    try:
        build = build_fixture_consensus(
            ledger,
            decision="targeted_reedit",
            selected_candidate_id=package0["candidates"][0]["candidateId"],
            directives=_directive_fixture(0),
        )
        ingest_consensus(ledger, build)
    except (ReconciliationRequired, KeyError):
        blocked_consensus = True
    if not blocked_consensus:
        raise AssertionError("consensus advanced under reconciliation")

    # Restart and recover unknown Send authoritatively; no second Send effect.
    ledger = TournamentLedger(ledger_path)
    reconcile_dispatch(
        ledger,
        reviewer_index=1,
        conversation_id="conv-r0-reviewer-1",
        adapter=dispatch,
    )
    dispatch_review(
        ledger,
        reviewer_index=2,
        conversation_id="conv-r0-reviewer-2",
        adapter=dispatch,
    )
    if dispatch.effect_count != 3:
        raise AssertionError("round-0 dispatch duplicated an effect")

    # Crash after all three reviews, before consensus ingest.
    ledger = TournamentLedger(ledger_path)
    consensus0 = build_fixture_consensus(
        ledger,
        decision="targeted_reedit",
        selected_candidate_id=package0["candidates"][0]["candidateId"],
        directives=_directive_fixture(0),
    )
    ingest_consensus(ledger, consensus0)
    apply_targeted_reedit(ledger, package=package0, consensus=consensus0, adapter=media)
    if media.effect_count != 1:
        raise AssertionError("re-edit effect count mismatch")

    # Crash after edit persisted but before next package.
    ledger = TournamentLedger(ledger_path)
    base_sha = ledger.state["selectedRender"]["outputRenderSha256"]
    package1 = build_fixture_candidate_package(
        ledger,
        candidate_count=4,
        base_render_sha=base_sha,
    )
    ingest_candidate_package(ledger, package1)

    for reviewer_index in range(REVIEWER_COUNT):
        dispatch_review(
            ledger,
            reviewer_index=reviewer_index,
            conversation_id=f"conv-r1-reviewer-{reviewer_index}",
            adapter=dispatch,
        )
    if dispatch.effect_count != 6:
        raise AssertionError("second-round dispatch effect count mismatch")

    ledger = TournamentLedger(ledger_path)
    consensus1 = build_fixture_consensus(
        ledger,
        decision="winner",
        selected_candidate_id=package1["candidates"][2]["candidateId"],
    )
    ingest_consensus(ledger, consensus1)
    handoff = emit_publish_handoff(ledger, package=package1)

    # Crash after winner handoff; replay must be byte-stable and side-effect free.
    before_digest = ledger.digest
    ledger = TournamentLedger(ledger_path)
    replay_handoff = emit_publish_handoff(ledger, package=package1)
    if replay_handoff != handoff or ledger.digest != before_digest:
        raise AssertionError("winner handoff replay was not byte-stable")

    status = ledger.status()
    report = {
        "reportVersion": REHEARSAL_VERSION,
        "overallAuthorityStatus": next_wave_status(),
        "state": status["state"],
        "source": ledger.state["source"],
        "briefDigest": ledger.state["briefDigest"],
        "sessionId": ledger.state["sessionId"],
        "tournamentId": ledger.state["tournamentId"],
        "reviewRoundsCompleted": 2,
        "reeditRoundsExecuted": ledger.state["reeditRound"],
        "initialCandidateCount": len(package0["candidates"]),
        "secondRoundCandidateCount": len(package1["candidates"]),
        "independentReviewerCount": REVIEWER_COUNT,
        "dispatchLogicalEffects": dispatch.effect_count,
        "mediaReeditLogicalEffects": media.effect_count,
        "reconciliationEvents": 1,
        "lostAckConsensusBlocked": blocked_consensus,
        "winnerCandidateId": handoff["winnerCandidateId"],
        "finalRenderSha256": handoff["finalArtifact"]["sha256"],
        "publishHandoffDigest": handoff["handoffDigest"],
        "ledgerDigest": ledger.digest,
        "authorityDigest": ledger.state["authorityDigest"],
        "nextWave": _clone(NEXT_WAVE),
        "humanGroundTruthClaimed": False,
        "browserMutation": False,
        "providerMutation": False,
        "livePublish": False,
    }
    report["reportDigest"] = _sha(report)
    (root / "chaos-rehearsal.r32.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (root / "coordinator-status.r32.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (root / "publish-handoff.fixture.json").write_text(
        json.dumps(handoff, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    evidence = {
        "contractVersion": EVIDENCE_VERSION,
        "creatorBaseSha": CREATOR_BASE_SHA,
        "authorityProfiles": authority_profiles(),
        "chaosRehearsalDigest": report["reportDigest"],
        "ledgerFileSha256": hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
        "ledgerSizeBytes": ledger_path.stat().st_size,
        "publishHandoffDigest": handoff["handoffDigest"],
        "statusDigest": status["statusDigest"],
        "effects": {
            "reviewDispatch": dispatch.effect_count,
            "targetedReedit": media.effect_count,
            "publishProvider": 0,
        },
        "humanGroundTruthClaimed": False,
        "livePublish": False,
    }
    evidence["evidenceDigest"] = _sha(evidence)
    (root / "evidence-manifest.r32.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="creator-autonomous-tournament-r32")
    sub = parser.add_subparsers(dest="command", required=True)
    readiness_cmd = sub.add_parser("readiness")
    readiness_cmd.add_argument("--out")
    status_cmd = sub.add_parser("status")
    status_cmd.add_argument("--ledger")
    status_cmd.add_argument("--out")
    rehearsal_cmd = sub.add_parser("chaos-rehearsal")
    rehearsal_cmd.add_argument("--out", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "readiness":
        value = readiness()
        if args.out:
            Path(args.out).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(value, sort_keys=True))
        return 0
    if args.command == "status":
        if args.ledger:
            value = TournamentLedger(args.ledger).status()
        else:
            ready = readiness()
            value = {
                "contractVersion": STATUS_VERSION,
                "state": ready["status"],
                "blockers": ready["blockers"],
                "nextPermittedAction": (
                    "WAIT_FOR_R25_R30_R35_EXACT_GREEN"
                    if not ready["FULL_NEXT_WAVE_PINNED"]
                    else "START_AUTONOMOUS_TOURNAMENT"
                ),
                "requiredAuthorityEvidence": ready["nextWave"],
                "authorityDigest": ready["authorityDigest"],
            }
            value["statusDigest"] = _sha(value)
        if args.out:
            Path(args.out).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(value, sort_keys=True))
        return 0
    report = run_chaos_rehearsal(args.out)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
