from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import autonomous_reels as reels
from . import multiplatform_publish_saga_r34 as r34
from . import publish_transaction_r33 as r33

CONTRACT_VERSION = "creator.release_escrow_canary.r35.v1"
LEDGER_VERSION = "creator.release_escrow_canary_ledger.r35.v1"
STATUS_VERSION = "creator.release_escrow_canary_status.r35.v1"
READINESS_VERSION = "creator.release_escrow_canary_readiness.r35.v1"
CHAOS_VERSION = "creator.release_escrow_canary_chaos.r35.v1"
EVIDENCE_VERSION = "creator.release_escrow_canary_evidence.r35.v1"

STATES = (
    "PREPARED",
    "ESCROWED",
    "PREFLIGHT_GREEN",
    "CANARY_ELIGIBLE",
    "CANARY_COMMITTING",
    "CANARY_CONFIRMED",
    "EXPANSION_ELIGIBLE",
    "EXPANSION_COMMITTING",
    "FULLY_CONFIRMED",
    "HUMAN_REVIEW_REQUIRED",
    "RECONCILIATION_REQUIRED",
    "TERMINALLY_BLOCKED",
)

TERMINAL_STATES = {
    "FULLY_CONFIRMED",
    "HUMAN_REVIEW_REQUIRED",
    "TERMINALLY_BLOCKED",
}

R34_AUTHORITY = {
    "repository": "foto6/video1",
    "producerSha": "77dfe83d582eac98e60728974efc77345612b364",
    "ciRunId": 37209289425,
    "artifactId": 11305609870,
    "artifactName": "creator-r34-multiplatform-publish-saga-77dfe83d582eac98e60728974efc77345612b364",
    "artifactDigest": "sha256:366dc6b7f43982c23489f7119a04805b4be9b8eed2717f61a9db3a0e6ece1032",
    "contract": "creator.multiplatform_publish_saga.r34.v1",
    "contractBlobs": {
        "runtime": "7fa3ecedbefa95c068a7946cfb51a3999ccff32f",
        "tests": "48f3a4700354ca2022747c27f02fd70ebecd7c94",
        "schema": "b1df09e22fb648b4b9e6eb5672265fc31cdb2ce1",
        "manifest": "27ecee8d4e2e5de7c2724542b3bcb3e2005e8c27",
        "authority": "abbc022b913412205b956ca17fe6b851d62390f2",
        "parentQa": "6e0a96d302ee147af533262cefb3cf4b33f43eb6",
        "readiness": "9923169248301dae11b77322a1f2c1a7142448b9",
    },
    "qaR5": {
        "repository": "foto6/boss",
        "producerSha": "1583c853108b0fb88507448eb8b4c61f0f07b0bc",
        "ciRunId": 37211964139,
        "artifactId": 11306289580,
        "artifactName": "hard-wave-acceptance-r5-1583c853108b0fb88507448eb8b4c61f0f07b0bc",
        "artifactDigest": "sha256:846c97206fb332d0ffa1011f44b884b3148736ba9ca96a756b4ae585eab50bfa",
        "disposition": "ACCEPTED",
        "authorityTupleError": "E_AUTHORITY_TUPLE_MISMATCH",
        "blobPins": {
            "authorityFixture": "403abe30972348a2b93edd7aafaa1998e3c7af13",
            "acceptanceRuntime": "18facd0030c3039e874939e471922d37bac02a7d",
            "acceptanceTests": "9b541d6c9c41934bce9ea9a3f98b53d1fdce7273",
            "documentation": "1ee1dcfea654b05d3c011a208e805ff509de2808",
            "checkpoint": "e80fae9f8e20708ddd6f98b9741ff1dd5ec8245e",
            "compatibilityMatrix": "82c79639607a691eefe307591247ef376e8932cd",
            "rejectedFaults": "87c7d405e39c146bfb6de97ae741008ae778b23c",
        },
    },
}

GROWTH_R33_AUTHORITY = {
    "repository": "foto6/video3",
    "producerSha": "8bedb5ad79023006b87b17933863ff915ab5e046",
    "ciRunId": 37210963972,
    "artifactId": 11306727215,
    "artifactName": "growth-r33-adaptive-portfolio-governor",
    "artifactDigest": "sha256:132845c0aaa6d4fec5aaf60e1ade60d779183f2a637a9513e4176bd2ee569660",
    "contract": "growth.adaptive_portfolio_governor.r33.v1",
    "contractBlobs": {
        "authority": "35426e8f05f708d0a6db4356c4211458bf033c16",
        "campaignBundleSchema": "95b9e692deb136ed03afb3b6a44108632c32f7e5",
        "contract": "518f293756564ca9bf0f004a728d34201f491dfa",
        "decisionSchema": "7e96c9afb74670aa34874c98c8427d443ae80c9b",
        "policy": "0f4da630a87d08ccac2e22dfc307b1abb6120dd9",
        "portfolioSchema": "392ceb044fed02e4f1da5eb46155bb8342c4875d",
        "implementation": "a6fddc11e5c5014ff16a69fd7b6944d17a71e9f2",
        "tests": "f1a56b1ebd628356de8913d8112e806063f720f1",
        "docs": "ea23f9e287405c1d6e1845469e36fb0b2912974a",
    },
    "qaR5": {
        "repository": "foto6/boss",
        "producerSha": "1583c853108b0fb88507448eb8b4c61f0f07b0bc",
        "ciRunId": 37211964139,
        "artifactId": 11306289580,
        "artifactDigest": "sha256:846c97206fb332d0ffa1011f44b884b3148736ba9ca96a756b4ae585eab50bfa",
        "disposition": "ACCEPTED",
        "authorityTupleError": "E_AUTHORITY_TUPLE_MISMATCH",
        "authorityFixtureBlob": "403abe30972348a2b93edd7aafaa1998e3c7af13",
    },
    "evidenceBoundary": {
        "shadowOnly": True,
        "creatorMutation": False,
        "providerMutation": False,
        "trafficRouting": False,
        "budgetAllocation": False,
        "livePublish": False,
        "humanGroundTruth": False,
    },
}

DEFAULT_RELEASE_POLICY = {
    "contractVersion": "creator.release_policy.r35.v1",
    "mode": "all_required",
    "requiredPlatforms": ["instagram_reels", "tiktok", "youtube_shorts"],
    "canaryPlatform": "instagram_reels",
    "expansionOrder": ["tiktok", "youtube_shorts"],
    "configRevision": 1,
    "operatorAuthorizationDigest": "f" * 64,
    "growthAdvisoryMayAuthorizeMutation": False,
    "automaticDestructiveCompensation": False,
}


class ReleaseError(ValueError):
    pass


class AuthorityDrift(ReleaseError):
    pass


class ReleaseConflict(ReleaseError):
    pass


class IllegalTransition(ReleaseError):
    pass


class HumanReviewRequired(ReleaseError):
    pass


class ReconciliationRequired(ReleaseError):
    pass


class ScheduleBlocked(ReleaseError):
    pass


class LiveProviderForbidden(ReleaseError):
    pass


class CompensationForbidden(ReleaseError):
    pass


def _clone(value: Any) -> Any:
    return json.loads(reels.canonical_json(value))


def _sha(value: Any) -> str:
    return reels.sha256_json(value)


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hex(value: Any, field: str, length: int = 64) -> str:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ReleaseError(f"{field} must be lowercase {length}-hex")
    return value


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseError(f"{field} must be non-empty")
    return value


def _validate_authority(value: Mapping[str, Any], expected: Mapping[str, Any], name: str) -> dict[str, Any]:
    if value != expected:
        raise AuthorityDrift(f"{name} authority tuple mismatch")
    return _clone(value)


def validate_r34_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    authority = _validate_authority(value, R34_AUTHORITY, "Creator R34")
    qa = authority["qaR5"]
    if (
        qa["disposition"] != "ACCEPTED"
        or qa["producerSha"] != "1583c853108b0fb88507448eb8b4c61f0f07b0bc"
        or qa["ciRunId"] != 37211964139
        or qa["artifactId"] != 11306289580
    ):
        raise AuthorityDrift("Creator R34 independent QA-R5 acceptance drift")
    return authority


def validate_growth_r33_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    authority = _validate_authority(value, GROWTH_R33_AUTHORITY, "Growth R33")
    boundary = authority["evidenceBoundary"]
    if not boundary["shadowOnly"]:
        raise AuthorityDrift("Growth R33 must remain shadow-only")
    for key in ("creatorMutation", "providerMutation", "trafficRouting", "budgetAllocation", "livePublish"):
        if boundary[key] is not False:
            raise AuthorityDrift(f"Growth R33 unsafe evidence boundary: {key}")
    if authority["qaR5"]["disposition"] != "ACCEPTED":
        raise AuthorityDrift("Growth R33 lacks accepted QA-R5 disposition")
    return authority


def validate_growth_advisory(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "contractVersion",
        "decisionContract",
        "decisionDigest",
        "status",
        "shadowRecommendation",
        "policyDigest",
        "authorityDigest",
        "evidenceBoundary",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ReleaseError("Growth advisory fields mismatch")
    if value["contractVersion"] != "creator.growth_r33_advisory_input.r35.v1":
        raise ReleaseError("Growth advisory wrapper version mismatch")
    if value["decisionContract"] != "growth.adaptive_portfolio_decision.r33.v1":
        raise ReleaseError("Growth decision contract mismatch")
    _hex(value["decisionDigest"], "growth decision digest")
    _hex(value["policyDigest"], "growth policy digest")
    if value["authorityDigest"] != _sha(GROWTH_R33_AUTHORITY):
        raise AuthorityDrift("Growth advisory authority digest mismatch")
    if value["status"] != "SHADOW_SOURCE_READY":
        raise ReleaseError("Growth advisory is not shadow source-ready")
    if value["shadowRecommendation"] not in {
        "KEEP",
        "TEST_MORE",
        "SHADOW_PROMOTE",
        "SHADOW_ROLLBACK",
        "HUMAN_REVIEW_REQUIRED",
    }:
        raise ReleaseError("Growth advisory recommendation unsupported")
    boundary = value["evidenceBoundary"]
    expected = {
        "shadowOnly": True,
        "creatorMutation": False,
        "providerMutation": False,
        "livePublish": False,
        "humanGroundTruth": False,
    }
    if boundary != expected:
        raise ReleaseError("Growth advisory evidence boundary drift")
    return _clone(value)


def _validate_release_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "contractVersion",
        "mode",
        "requiredPlatforms",
        "canaryPlatform",
        "expansionOrder",
        "configRevision",
        "operatorAuthorizationDigest",
        "growthAdvisoryMayAuthorizeMutation",
        "automaticDestructiveCompensation",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ReleaseError("release policy fields mismatch")
    if value["contractVersion"] != "creator.release_policy.r35.v1":
        raise ReleaseError("release policy version mismatch")
    if value["mode"] != "all_required":
        raise ReleaseError("R35 source-ready policy requires all_required")
    required_platforms = list(r34.REQUIRED_PLATFORMS)
    if value["requiredPlatforms"] != required_platforms:
        raise ReleaseError("release platform set drift")
    if value["canaryPlatform"] not in required_platforms:
        raise ReleaseError("canary platform not declared")
    expected_expansion = [p for p in required_platforms if p != value["canaryPlatform"]]
    if sorted(value["expansionOrder"]) != sorted(expected_expansion):
        raise ReleaseError("expansion order must contain every non-canary required platform exactly once")
    revision = value["configRevision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ReleaseError("policy configRevision must be positive integer")
    _hex(value["operatorAuthorizationDigest"], "operator authorization digest")
    if value["growthAdvisoryMayAuthorizeMutation"] is not False:
        raise ReleaseError("Growth advisory cannot authorize provider mutation")
    if value["automaticDestructiveCompensation"] is not False:
        raise ReleaseError("automatic destructive compensation forbidden")
    return _clone(value)


def _validate_schedule(value: Mapping[str, Any]) -> dict[str, Any]:
    return r34._validate_window(value)


def _window_state(schedule: Mapping[str, Any], at_time: str) -> str:
    return r34._window_state(schedule, at_time)


def _validate_r34_saga_spec(spec: Mapping[str, Any], authority: Mapping[str, Any]) -> dict[str, Any]:
    validate_r34_authority(authority)
    if spec.get("contractVersion") != r34.CONTRACT_VERSION:
        raise ReleaseError("R34 saga contract mismatch")
    if spec.get("parentQaStatus") != "ACCEPTED_QA_R3":
        raise ReleaseError("R34 saga parent QA status mismatch")
    if set(spec.get("childSpecs", {})) != set(r34.REQUIRED_PLATFORMS):
        raise ReleaseError("R34 child platform set mismatch")
    if spec["releasePolicy"]["mode"] != "all_required":
        raise ReleaseError("R34 child release policy must remain all_required")
    return _clone(spec)


def build_release_spec(
    *,
    r34_saga_spec: Mapping[str, Any],
    growth_advisory: Mapping[str, Any],
    release_policy: Mapping[str, Any],
    schedule_window: Mapping[str, Any],
    revision_id: int,
    r34_authority: Mapping[str, Any] = R34_AUTHORITY,
    growth_authority: Mapping[str, Any] = GROWTH_R33_AUTHORITY,
    release_operation_id: str | None = None,
) -> dict[str, Any]:
    r34_authority = validate_r34_authority(r34_authority)
    growth_authority = validate_growth_r33_authority(growth_authority)
    saga = _validate_r34_saga_spec(r34_saga_spec, r34_authority)
    advisory = validate_growth_advisory(growth_advisory)
    policy = _validate_release_policy(release_policy)
    schedule = _validate_schedule(schedule_window)
    if isinstance(revision_id, bool) or not isinstance(revision_id, int) or revision_id < 1:
        raise ReleaseError("revision_id must be positive integer")
    if schedule["revision"] != revision_id:
        raise ReleaseConflict("schedule revision must equal release revision id")
    if saga["releaseWindow"] != schedule:
        raise ReleaseConflict("R34 saga schedule must exactly match R35 release schedule")
    if saga["releasePolicy"]["requiredPlatforms"] != policy["requiredPlatforms"]:
        raise ReleaseConflict("R34/R35 platform set mismatch")

    winner = _clone(saga["winner"])
    _hex(winner["sha256"], "winner sha256")
    if not isinstance(winner["size"], int) or winner["size"] < 1:
        raise ReleaseError("winner size invalid")
    lineage = _clone(saga["lineage"])
    copy_hashes = {
        platform: _clone(saga["childSpecs"][platform]["contentHashes"])
        for platform in policy["requiredPlatforms"]
    }
    accounts = {
        platform: {
            "providerAdapter": saga["childSpecs"][platform]["target"]["providerAdapter"],
            "accountRef": saga["childSpecs"][platform]["target"]["accountRef"],
            "destination": saga["childSpecs"][platform]["target"]["destination"],
            "configurationRef": saga["childSpecs"][platform]["target"]["configurationRef"],
        }
        for platform in policy["requiredPlatforms"]
    }
    immutable = {
        "contractVersion": CONTRACT_VERSION,
        "sourceSha256": lineage["sourceSha256"],
        "sessionId": lineage["sessionId"],
        "tournamentId": lineage["tournamentId"],
        "winnerCandidateId": lineage["winnerCandidateId"],
        "winner": winner,
        "r34Authority": r34_authority,
        "r34SagaId": saga["sagaId"],
        "r34ImmutableDigest": saga["immutableDigest"],
        "growthR33Authority": growth_authority,
        "growthDecisionDigest": advisory["decisionDigest"],
        "growthDecisionContract": advisory["decisionContract"],
        "releasePolicy": policy,
        "releasePolicyDigest": _sha(policy),
        "scheduleWindow": schedule,
        "revisionId": revision_id,
        "platformCopyHashes": copy_hashes,
        "platformAccounts": accounts,
    }
    derived_operation_id = "r35release:" + _sha(immutable)
    if release_operation_id is not None and release_operation_id != derived_operation_id:
        raise ReleaseConflict("explicit release operation id does not match immutable intent")
    return {
        "contractVersion": CONTRACT_VERSION,
        "releaseOperationId": derived_operation_id,
        "revisionId": revision_id,
        "sourceSha256": lineage["sourceSha256"],
        "sessionId": lineage["sessionId"],
        "tournamentId": lineage["tournamentId"],
        "winnerCandidateId": lineage["winnerCandidateId"],
        "winner": winner,
        "r34Authority": r34_authority,
        "r34SagaId": saga["sagaId"],
        "r34ImmutableDigest": saga["immutableDigest"],
        "r34SagaSpec": saga,
        "growthR33Authority": growth_authority,
        "growthAdvisory": advisory,
        "growthDecisionDigest": advisory["decisionDigest"],
        "releasePolicy": policy,
        "policyDigest": _sha(policy),
        "scheduleWindow": schedule,
        "platformCopyHashes": copy_hashes,
        "platformAccounts": accounts,
        "immutableDigest": _sha(immutable),
    }


class ReleaseLedger:
    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        release_spec: Mapping[str, Any] | None = None,
    ) -> None:
        self.root = Path(root)
        self.path = self.root / "release-escrow-canary-ledger.jsonl"
        self.events: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        self.state: dict[str, Any] = {}
        if self.path.exists():
            self._load()
            if release_spec is not None:
                self.assert_identity(release_spec)
                self._ensure_r34_saga(release_spec)
            return
        if release_spec is None:
            raise ReleaseError("new R35 ledger requires release_spec")
        self.root.mkdir(parents=True, exist_ok=True)
        self._ensure_r34_saga(release_spec)
        platforms = {}
        canary = release_spec["releasePolicy"]["canaryPlatform"]
        for platform in release_spec["releasePolicy"]["requiredPlatforms"]:
            child = self.r34_saga.child(platform)
            platforms[platform] = {
                "role": "canary" if platform == canary else "expansion",
                "accountIdentity": _clone(release_spec["platformAccounts"][platform]),
                "transactionId": child.state["transactionId"],
                "idempotencyKey": child.state["idempotencyKey"],
                "requestDigest": child.state["requestDigest"],
                "operationState": "PENDING",
                "attemptNumber": 0,
                "invocationIntentPersisted": False,
                "externalOperationId": None,
                "externalPostId": None,
                "outcomeProofDigest": None,
                "providerOutcome": None,
                "replayAuthorized": False,
            }
        initial = {
            "contractVersion": CONTRACT_VERSION,
            "releaseOperationId": release_spec["releaseOperationId"],
            "revisionId": release_spec["revisionId"],
            "state": "PREPARED",
            "immutableDigest": release_spec["immutableDigest"],
            "sourceSha256": release_spec["sourceSha256"],
            "sessionId": release_spec["sessionId"],
            "tournamentId": release_spec["tournamentId"],
            "winnerCandidateId": release_spec["winnerCandidateId"],
            "winner": _clone(release_spec["winner"]),
            "r34Authority": _clone(release_spec["r34Authority"]),
            "r34SagaId": release_spec["r34SagaId"],
            "r34ImmutableDigest": release_spec["r34ImmutableDigest"],
            "growthR33Authority": _clone(release_spec["growthR33Authority"]),
            "growthDecisionDigest": release_spec["growthDecisionDigest"],
            "growthAdvisoryDigest": _sha(release_spec["growthAdvisory"]),
            "releasePolicy": _clone(release_spec["releasePolicy"]),
            "policyDigest": release_spec["policyDigest"],
            "scheduleWindow": _clone(release_spec["scheduleWindow"]),
            "platformCopyHashes": _clone(release_spec["platformCopyHashes"]),
            "platformAccounts": _clone(release_spec["platformAccounts"]),
            "platforms": platforms,
            "escrow": None,
            "preflight": None,
            "unresolvedOperations": [],
            "compensations": {},
            "blockers": [],
            "fakeProviderEffects": 0,
            "providerNetworkEffects": 0,
            "realProviderEffectAuthorized": False,
            "livePublish": False,
        }
        self._append(
            event_key="release-prepared",
            event_type="RELEASE_PREPARED",
            operation_id="r35prepare:" + _sha(
                {
                    "releaseOperationId": initial["releaseOperationId"],
                    "immutableDigest": initial["immutableDigest"],
                }
            ),
            request={
                "releaseOperationId": initial["releaseOperationId"],
                "immutableDigest": initial["immutableDigest"],
            },
            new_state=initial,
            timestamp_metadata="2026-10-05T00:00:00Z",
            previous_state={},
        )

    @property
    def r34_root(self) -> Path:
        return self.root / "r34-saga"

    @property
    def r34_saga(self) -> r34.SagaLedger:
        return r34.SagaLedger(self.r34_root)

    def _ensure_r34_saga(self, spec: Mapping[str, Any]) -> None:
        r34.SagaLedger(self.r34_root, saga_spec=spec["r34SagaSpec"])

    def _load(self) -> None:
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(),
            1,
        ):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReleaseConflict(f"invalid R35 ledger JSON line {line_number}") from exc
            required = {
                "ledgerVersion",
                "sequence",
                "eventKey",
                "eventType",
                "operationId",
                "requestDigest",
                "previousStateDigest",
                "newStateDigest",
                "timestampMetadata",
                "newState",
                "eventDigest",
            }
            if set(event) != required or event["ledgerVersion"] != LEDGER_VERSION:
                raise ReleaseConflict("R35 ledger event shape/version mismatch")
            if event["sequence"] != len(self.events) + 1:
                raise ReleaseConflict("R35 ledger sequence mismatch")
            if event["eventKey"] in self.by_key:
                raise ReleaseConflict("duplicate R35 ledger event key")
            if event["previousStateDigest"] != _sha(self.state):
                raise ReleaseConflict("R35 ledger previous-state chain mismatch")
            if event["newStateDigest"] != _sha(event["newState"]):
                raise ReleaseConflict("R35 ledger new-state digest mismatch")
            identity = {
                key: value
                for key, value in event.items()
                if key not in {"timestampMetadata", "eventDigest"}
            }
            if event["eventDigest"] != _sha(identity):
                raise ReleaseConflict("R35 ledger event digest mismatch")
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
                or existing["newStateDigest"] != _sha(new_state)
            ):
                raise ReleaseConflict(f"conflicting R35 replay for {event_key}")
            return "duplicate", _clone(existing)
        old = self.state if previous_state is None else _clone(previous_state)
        event = {
            "ledgerVersion": LEDGER_VERSION,
            "sequence": len(self.events) + 1,
            "eventKey": event_key,
            "eventType": event_type,
            "operationId": operation_id,
            "requestDigest": request_digest,
            "previousStateDigest": _sha(old),
            "newStateDigest": _sha(new_state),
            "timestampMetadata": timestamp_metadata,
            "newState": _clone(new_state),
        }
        identity = {
            key: value
            for key, value in event.items()
            if key not in {"timestampMetadata", "eventDigest"}
        }
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

    def assert_identity(self, spec: Mapping[str, Any]) -> None:
        checks = {
            "releaseOperationId": spec["releaseOperationId"],
            "revisionId": spec["revisionId"],
            "immutableDigest": spec["immutableDigest"],
            "sourceSha256": spec["sourceSha256"],
            "winner": spec["winner"],
            "r34Authority": spec["r34Authority"],
            "growthR33Authority": spec["growthR33Authority"],
            "growthDecisionDigest": spec["growthDecisionDigest"],
            "policyDigest": spec["policyDigest"],
            "scheduleWindow": spec["scheduleWindow"],
            "platformAccounts": spec["platformAccounts"],
            "platformCopyHashes": spec["platformCopyHashes"],
        }
        for key, expected in checks.items():
            if self.state.get(key) != expected:
                raise ReleaseConflict(f"release identity drift: {key}")

    @property
    def digest(self) -> str:
        return _sha(self.events)


def prepare_release(root: str | os.PathLike[str], **kwargs: Any) -> ReleaseLedger:
    spec = build_release_spec(**kwargs)
    return ReleaseLedger(root, release_spec=spec)


def _transition(
    ledger: ReleaseLedger,
    *,
    allowed_from: set[str],
    to_state: str,
    event_key: str,
    event_type: str,
    request: Mapping[str, Any],
    mutate: Callable[[dict[str, Any]], None] | None = None,
    timestamp: str = "2026-10-05T00:00:01Z",
) -> dict[str, Any]:
    if ledger.state["state"] not in allowed_from:
        raise IllegalTransition(
            f"{event_type} forbidden from {ledger.state['state']}"
        )
    new = _clone(ledger.state)
    if mutate is not None:
        mutate(new)
    new["state"] = to_state
    operation_id = "r35op:" + _sha(
        {
            "releaseOperationId": new["releaseOperationId"],
            "eventType": event_type,
            "request": request,
            "sequence": len(ledger.events) + 1,
        }
    )
    ledger._append(
        event_key=event_key,
        event_type=event_type,
        operation_id=operation_id,
        request=request,
        new_state=new,
        timestamp_metadata=timestamp,
    )
    return _clone(new)


def escrow_release(
    ledger: ReleaseLedger,
    *,
    observed_render_sha256: str,
    observed_render_size: int,
    metadata_digest: str,
) -> dict[str, Any]:
    if ledger.state["state"] == "ESCROWED":
        expected = ledger.state["escrow"]
        actual = {
            "renderSha256": observed_render_sha256,
            "renderSize": observed_render_size,
            "metadataDigest": metadata_digest,
            "r34SagaDigest": ledger.state["r34ImmutableDigest"],
            "growthDecisionDigest": ledger.state["growthDecisionDigest"],
        }
        if expected != actual:
            raise ReleaseConflict("escrow replay changed frozen render/metadata")
        return _clone(ledger.state)
    _hex(observed_render_sha256, "observed render sha256")
    _hex(metadata_digest, "metadata digest")
    if observed_render_sha256 != ledger.state["winner"]["sha256"]:
        raise ReleaseConflict("escrow render SHA mismatch")
    if observed_render_size != ledger.state["winner"]["size"]:
        raise ReleaseConflict("escrow render size mismatch")
    escrow = {
        "renderSha256": observed_render_sha256,
        "renderSize": observed_render_size,
        "metadataDigest": metadata_digest,
        "r34SagaDigest": ledger.state["r34ImmutableDigest"],
        "growthDecisionDigest": ledger.state["growthDecisionDigest"],
    }

    def mutate(new: dict[str, Any]) -> None:
        new["escrow"] = escrow
        new["blockers"] = []

    return _transition(
        ledger,
        allowed_from={"PREPARED"},
        to_state="ESCROWED",
        event_key="escrow",
        event_type="RELEASE_ESCROWED",
        request=escrow,
        mutate=mutate,
    )


def verify_frozen_identity(
    ledger: ReleaseLedger,
    *,
    render_sha256: str | None = None,
    render_size: int | None = None,
    metadata_digest: str | None = None,
    growth_decision_digest: str | None = None,
    policy_digest: str | None = None,
    platform_accounts: Mapping[str, Any] | None = None,
) -> None:
    state = ledger.state
    if render_sha256 is not None and render_sha256 != state["winner"]["sha256"]:
        raise ReleaseConflict("winner render hash drift")
    if render_size is not None and render_size != state["winner"]["size"]:
        raise ReleaseConflict("winner render size drift")
    if metadata_digest is not None:
        if state["escrow"] is None or metadata_digest != state["escrow"]["metadataDigest"]:
            raise ReleaseConflict("escrow metadata drift")
    if growth_decision_digest is not None and growth_decision_digest != state["growthDecisionDigest"]:
        raise ReleaseConflict("Growth decision drift")
    if policy_digest is not None and policy_digest != state["policyDigest"]:
        raise ReleaseConflict("release policy revision/digest drift")
    if platform_accounts is not None and _clone(platform_accounts) != state["platformAccounts"]:
        raise ReleaseConflict("platform account identity drift")


def _block_for_human_review(
    ledger: ReleaseLedger,
    *,
    code: str,
    detail: str,
    timestamp: str,
) -> dict[str, Any]:
    if ledger.state["state"] in {"FULLY_CONFIRMED", "TERMINALLY_BLOCKED"}:
        raise IllegalTransition("human review cannot rewrite terminal confirmation/block")
    new = _clone(ledger.state)
    new["state"] = "HUMAN_REVIEW_REQUIRED"
    new["blockers"] = [{"code": code, "detail": detail}]
    ledger._append(
        event_key=f"human-review:{code}",
        event_type="HUMAN_REVIEW_REQUIRED",
        operation_id="r35human:" + _sha(
            {
                "releaseOperationId": new["releaseOperationId"],
                "code": code,
                "detail": detail,
            }
        ),
        request={"code": code, "detail": detail},
        new_state=new,
        timestamp_metadata=timestamp,
    )
    return _clone(new)


def _terminal_block(
    ledger: ReleaseLedger,
    *,
    code: str,
    detail: str,
    timestamp: str,
) -> dict[str, Any]:
    new = _clone(ledger.state)
    new["state"] = "TERMINALLY_BLOCKED"
    new["blockers"] = [{"code": code, "detail": detail}]
    ledger._append(
        event_key=f"terminal-block:{code}",
        event_type="TERMINALLY_BLOCKED",
        operation_id="r35blocked:" + _sha(
            {
                "releaseOperationId": new["releaseOperationId"],
                "code": code,
                "detail": detail,
            }
        ),
        request={"code": code, "detail": detail},
        new_state=new,
        timestamp_metadata=timestamp,
    )
    return _clone(new)


def preflight_release(
    ledger: ReleaseLedger,
    *,
    started_at: str,
    completed_at: str,
    observed_policy_digest: str,
    observed_growth_decision_digest: str,
) -> dict[str, Any]:
    if ledger.state["state"] != "ESCROWED":
        raise IllegalTransition(f"preflight forbidden from {ledger.state['state']}")
    verify_frozen_identity(
        ledger,
        policy_digest=observed_policy_digest,
        growth_decision_digest=observed_growth_decision_digest,
    )
    if _window_state(ledger.state["scheduleWindow"], completed_at) == "AFTER_DEADLINE":
        return _terminal_block(
            ledger,
            code="PREFLIGHT_CROSSED_RELEASE_DEADLINE",
            detail=f"preflight {started_at}..{completed_at} completed after release deadline",
            timestamp=completed_at,
        )
    validate_r34_authority(ledger.state["r34Authority"])
    validate_growth_r33_authority(ledger.state["growthR33Authority"])
    r34_saga = ledger.r34_saga
    validation_digests: dict[str, str] = {}
    try:
        for platform in ledger.state["releasePolicy"]["requiredPlatforms"]:
            child = r34.validate_platform(r34_saga, platform)
            validation_digests[platform] = child["validationDigest"]
    except Exception as exc:
        return _terminal_block(
            ledger,
            code="R34_CHILD_PREFLIGHT_REJECTED",
            detail=type(exc).__name__,
            timestamp=completed_at,
        )
    preflight = {
        "startedAt": started_at,
        "completedAt": completed_at,
        "policyDigest": ledger.state["policyDigest"],
        "growthDecisionDigest": ledger.state["growthDecisionDigest"],
        "validationDigests": validation_digests,
        "growthAdvisoryAuthorizesMutation": False,
        "realProviderEffectAuthorized": False,
    }

    def mutate(new: dict[str, Any]) -> None:
        new["preflight"] = preflight
        new["blockers"] = []

    return _transition(
        ledger,
        allowed_from={"ESCROWED"},
        to_state="PREFLIGHT_GREEN",
        event_key="preflight-green",
        event_type="PREFLIGHT_GREEN",
        request=preflight,
        mutate=mutate,
        timestamp=completed_at,
    )


def mark_canary_eligible(
    ledger: ReleaseLedger,
    *,
    at_time: str,
    operator_authorization_digest: str,
) -> dict[str, Any]:
    if ledger.state["state"] != "PREFLIGHT_GREEN":
        raise IllegalTransition(f"canary eligibility forbidden from {ledger.state['state']}")
    if operator_authorization_digest != ledger.state["releasePolicy"]["operatorAuthorizationDigest"]:
        return _block_for_human_review(
            ledger,
            code="OPERATOR_AUTHORIZATION_MISMATCH",
            detail="Growth advisory cannot replace explicit release authorization",
            timestamp=at_time,
        )
    if _window_state(ledger.state["scheduleWindow"], at_time) != "OPEN":
        return _terminal_block(
            ledger,
            code="CANARY_OUTSIDE_RELEASE_WINDOW",
            detail="canary authorization attempted outside release window",
            timestamp=at_time,
        )
    canary = ledger.state["releasePolicy"]["canaryPlatform"]
    r34.mark_platform_commit_eligible(ledger.r34_saga, canary)

    def mutate(new: dict[str, Any]) -> None:
        new["platforms"][canary]["operationState"] = "ELIGIBLE"
        new["platforms"][canary]["replayAuthorized"] = True
        new["blockers"] = []

    return _transition(
        ledger,
        allowed_from={"PREFLIGHT_GREEN"},
        to_state="CANARY_ELIGIBLE",
        event_key="canary-eligible",
        event_type="CANARY_ELIGIBLE",
        request={
            "canaryPlatform": canary,
            "operatorAuthorizationDigest": operator_authorization_digest,
        },
        mutate=mutate,
        timestamp=at_time,
    )


def _sync_platform_from_child(
    ledger: ReleaseLedger,
    platform: str,
    *,
    target_state: str,
    blockers: list[dict[str, Any]] | None = None,
    increment_fake_effects: int = 0,
) -> dict[str, Any]:
    child = ledger.r34_saga.child(platform)
    status = r33.transaction_status(child)
    new = _clone(ledger.state)
    item = new["platforms"][platform]
    item["operationState"] = status["state"]
    item["attemptNumber"] = child.state["commit"]["attemptNumber"]
    item["invocationIntentPersisted"] = child.state["commit"]["invocationStarted"]
    item["externalOperationId"] = child.state["commit"]["externalOperationId"]
    item["externalPostId"] = child.state["commit"]["externalPostId"]
    item["outcomeProofDigest"] = child.state["commit"]["outcomeProofDigest"]
    item["providerOutcome"] = child.state["commit"]["providerOutcome"]
    item["replayAuthorized"] = status["blindRetryPermitted"]
    new["state"] = target_state
    new["blockers"] = blockers or []
    new["fakeProviderEffects"] += increment_fake_effects
    unresolved = []
    for p, op in new["platforms"].items():
        if op["operationState"] == "RECONCILIATION_REQUIRED" or (
            op["operationState"] == "COMMITTING" and op["invocationIntentPersisted"]
        ):
            unresolved.append(
                {
                    "platform": p,
                    "transactionId": op["transactionId"],
                    "requestDigest": op["requestDigest"],
                    "nextSafeAction": "READ_ONLY_RECONCILE_ONLY",
                    "replayAuthorized": False,
                }
            )
    new["unresolvedOperations"] = unresolved
    return new


def _persist_effect_boundary(
    ledger: ReleaseLedger,
    platform: str,
    phase_state: str,
    *,
    at_time: str,
) -> None:
    child = ledger.r34_saga.child(platform)
    new = _clone(ledger.state)
    item = new["platforms"][platform]
    item["operationState"] = "COMMITTING"
    item["attemptNumber"] = child.state["commit"]["attemptNumber"] + 1
    item["invocationIntentPersisted"] = False
    item["replayAuthorized"] = True
    new["state"] = phase_state
    new["blockers"] = []
    ledger._append(
        event_key=f"effect-boundary:{platform}:{item['attemptNumber']}",
        event_type=f"{phase_state}_EFFECT_BOUNDARY",
        operation_id="r35effect:" + _sha(
            {
                "releaseOperationId": new["releaseOperationId"],
                "platform": platform,
                "attemptNumber": item["attemptNumber"],
                "requestDigest": item["requestDigest"],
            }
        ),
        request={
            "platform": platform,
            "transactionId": item["transactionId"],
            "requestDigest": item["requestDigest"],
            "realProviderEffectAuthorized": False,
        },
        new_state=new,
        timestamp_metadata=at_time,
    )


def _account_guard(
    ledger: ReleaseLedger,
    platform: str,
    observed_account_ref: str,
    *,
    at_time: str,
) -> bool:
    expected = ledger.state["platformAccounts"][platform]["accountRef"]
    if observed_account_ref != expected:
        _block_for_human_review(
            ledger,
            code=f"ACCOUNT_IDENTITY_CHANGED:{platform}",
            detail="observed account differs from frozen release intent",
            timestamp=at_time,
        )
        return False
    return True


def _deadline_guard(ledger: ReleaseLedger, *, at_time: str, code: str) -> bool:
    if _window_state(ledger.state["scheduleWindow"], at_time) != "OPEN":
        _terminal_block(
            ledger,
            code=code,
            detail="provider commit attempted outside frozen release window",
            timestamp=at_time,
        )
        return False
    return True


def _commit_one(
    ledger: ReleaseLedger,
    platform: str,
    adapter: Any,
    *,
    at_time: str,
    phase_state: str,
    confirmed_state: str,
    observed_account_ref: str,
) -> dict[str, Any]:
    if getattr(adapter, "is_fake", False) is not True:
        raise LiveProviderForbidden("R35 permits fake provider harness only")
    if not _account_guard(ledger, platform, observed_account_ref, at_time=at_time):
        return _clone(ledger.state)
    if not _deadline_guard(ledger, at_time=at_time, code=f"{platform}:RELEASE_WINDOW_CLOSED"):
        return _clone(ledger.state)
    _persist_effect_boundary(ledger, platform, phase_state, at_time=at_time)
    calls_before = getattr(adapter, "commit_calls", 0)
    effects_before = getattr(adapter, "effect_count", 0)
    try:
        child_state = r34.commit_platform(
            ledger.r34_saga,
            platform,
            adapter,
            at_time=at_time,
        )
    except r33.OutcomeProofError:
        child = ledger.r34_saga.child(platform)
        if child.state["state"] == "COMMITTING":
            r33._mark_reconciliation_required(
                child,
                reason="provider_outcome_proof_invalid",
                event_key=f"r35-invalid-proof:{child.state['commit']['attemptNumber']}",
            )
        child_state = child.state
    calls_after = getattr(adapter, "commit_calls", calls_before)
    effects_after = getattr(adapter, "effect_count", effects_before)
    effect_delta = max(0, effects_after - effects_before)
    if child_state["state"] == "COMMITTED":
        target = confirmed_state
        blockers: list[dict[str, Any]] = []
    elif child_state["state"] == "COMMIT_ELIGIBLE":
        target = "CANARY_ELIGIBLE" if phase_state == "CANARY_COMMITTING" else "EXPANSION_COMMITTING"
        blockers = [{
            "code": "KNOWN_NO_PROVIDER_DISPATCH",
            "platform": platform,
            "safeToRetry": True,
        }]
    else:
        target = "RECONCILIATION_REQUIRED"
        blockers = [{
            "code": "PROVIDER_OUTCOME_UNKNOWN",
            "platform": platform,
            "blindRetryForbidden": True,
        }]
    new = _sync_platform_from_child(
        ledger,
        platform,
        target_state=target,
        blockers=blockers,
        increment_fake_effects=effect_delta,
    )
    ledger._append(
        event_key=f"effect-result:{platform}:{new['platforms'][platform]['attemptNumber']}:{target}",
        event_type=f"{phase_state}_RESULT",
        operation_id="r35result:" + _sha(
            {
                "releaseOperationId": new["releaseOperationId"],
                "platform": platform,
                "state": child_state["state"],
                "callsDelta": calls_after - calls_before,
                "effectsDelta": effect_delta,
            }
        ),
        request={
            "platform": platform,
            "childState": child_state["state"],
            "fakeProviderCallsDelta": calls_after - calls_before,
            "fakeProviderEffectsDelta": effect_delta,
        },
        new_state=new,
        timestamp_metadata=at_time,
    )
    return _clone(new)


def commit_canary(
    ledger: ReleaseLedger,
    adapter: Any,
    *,
    at_time: str,
    observed_account_ref: str,
) -> dict[str, Any]:
    if ledger.state["state"] == "RECONCILIATION_REQUIRED":
        raise ReconciliationRequired("canary outcome unresolved; read-only reconcile only")
    if ledger.state["state"] != "CANARY_ELIGIBLE":
        raise IllegalTransition(f"canary commit forbidden from {ledger.state['state']}")
    canary = ledger.state["releasePolicy"]["canaryPlatform"]
    return _commit_one(
        ledger,
        canary,
        adapter,
        at_time=at_time,
        phase_state="CANARY_COMMITTING",
        confirmed_state="CANARY_CONFIRMED",
        observed_account_ref=observed_account_ref,
    )


def reconcile_operation(
    ledger: ReleaseLedger,
    platform: str,
    adapter: Any,
    *,
    at_time: str,
) -> dict[str, Any]:
    if ledger.state["state"] != "RECONCILIATION_REQUIRED":
        raise IllegalTransition("reconciliation allowed only from RECONCILIATION_REQUIRED")
    if getattr(adapter, "is_fake", False) is not True:
        raise LiveProviderForbidden("R35 permits fake read-only reconciliation only")
    child = ledger.r34_saga.child(platform)
    calls_before = getattr(adapter, "commit_calls", 0)
    child_state = r34.reconcile_platform(ledger.r34_saga, platform, adapter)
    if getattr(adapter, "commit_calls", 0) != calls_before:
        raise AssertionError("read-only reconciliation invoked commit")
    canary = ledger.state["releasePolicy"]["canaryPlatform"]
    if child_state["state"] == "COMMITTED":
        if platform == canary:
            target = "CANARY_CONFIRMED"
        else:
            remaining = [
                p
                for p in ledger.state["releasePolicy"]["expansionOrder"]
                if ledger.r34_saga.child(p).state["state"] != "COMMITTED"
            ]
            target = "FULLY_CONFIRMED" if not remaining else "EXPANSION_COMMITTING"
        blockers: list[dict[str, Any]] = []
    else:
        target = "RECONCILIATION_REQUIRED"
        blockers = [{
            "code": "PROVIDER_OUTCOME_STILL_UNKNOWN",
            "platform": platform,
            "blindRetryForbidden": True,
        }]
    new = _sync_platform_from_child(
        ledger,
        platform,
        target_state=target,
        blockers=blockers,
    )
    ledger._append(
        event_key=f"reconcile:{platform}:{child.state['commit']['attemptNumber']}:{target}:{len(ledger.events)+1}",
        event_type="READ_ONLY_RECONCILIATION",
        operation_id="r35reconcile:" + _sha(
            {
                "releaseOperationId": new["releaseOperationId"],
                "platform": platform,
                "childState": child_state["state"],
                "proof": child_state["commit"]["outcomeProofDigest"],
            }
        ),
        request={
            "platform": platform,
            "childState": child_state["state"],
            "outcomeProofDigest": child_state["commit"]["outcomeProofDigest"],
        },
        new_state=new,
        timestamp_metadata=at_time,
    )
    return _clone(new)


def mark_expansion_eligible(
    ledger: ReleaseLedger,
    *,
    at_time: str,
) -> dict[str, Any]:
    if ledger.state["state"] != "CANARY_CONFIRMED":
        raise IllegalTransition(
            f"expansion eligibility requires durable canary confirmation, got {ledger.state['state']}"
        )
    if not _deadline_guard(ledger, at_time=at_time, code="EXPANSION_WINDOW_CLOSED"):
        return _clone(ledger.state)
    saga = ledger.r34_saga
    for platform in ledger.state["releasePolicy"]["expansionOrder"]:
        child = saga.child(platform)
        if child.state["state"] == "VALIDATED":
            r34.mark_platform_commit_eligible(saga, platform)

    def mutate(new: dict[str, Any]) -> None:
        for platform in new["releasePolicy"]["expansionOrder"]:
            new["platforms"][platform]["operationState"] = "ELIGIBLE"
            new["platforms"][platform]["replayAuthorized"] = True
        new["blockers"] = []

    return _transition(
        ledger,
        allowed_from={"CANARY_CONFIRMED"},
        to_state="EXPANSION_ELIGIBLE",
        event_key="expansion-eligible",
        event_type="EXPANSION_ELIGIBLE",
        request={
            "canaryPlatform": ledger.state["releasePolicy"]["canaryPlatform"],
            "canaryConfirmed": True,
            "expansionOrder": ledger.state["releasePolicy"]["expansionOrder"],
        },
        mutate=mutate,
        timestamp=at_time,
    )


def commit_expansion_platform(
    ledger: ReleaseLedger,
    platform: str,
    adapter: Any,
    *,
    at_time: str,
    observed_account_ref: str,
) -> dict[str, Any]:
    if platform == ledger.state["releasePolicy"]["canaryPlatform"]:
        raise ReleaseError("canary platform cannot be committed through expansion")
    if platform not in ledger.state["releasePolicy"]["expansionOrder"]:
        raise ReleaseError("platform is not declared in expansion policy")
    if ledger.state["state"] == "RECONCILIATION_REQUIRED":
        raise ReconciliationRequired("expansion outcome unresolved; read-only reconcile only")
    if ledger.state["state"] not in {"EXPANSION_ELIGIBLE", "EXPANSION_COMMITTING"}:
        raise IllegalTransition(f"expansion commit forbidden from {ledger.state['state']}")
    child = ledger.r34_saga.child(platform)
    if child.state["state"] == "COMMITTED":
        return _clone(ledger.state)
    if child.state["state"] != "COMMIT_ELIGIBLE":
        raise IllegalTransition(f"{platform} child not commit eligible")
    result = _commit_one(
        ledger,
        platform,
        adapter,
        at_time=at_time,
        phase_state="EXPANSION_COMMITTING",
        confirmed_state="EXPANSION_COMMITTING",
        observed_account_ref=observed_account_ref,
    )
    if result["state"] == "EXPANSION_COMMITTING":
        remaining = [
            p
            for p in result["releasePolicy"]["expansionOrder"]
            if ledger.r34_saga.child(p).state["state"] != "COMMITTED"
        ]
        if not remaining:
            final = _clone(ledger.state)
            final["state"] = "FULLY_CONFIRMED"
            final["blockers"] = []
            ledger._append(
                event_key="fully-confirmed",
                event_type="FULLY_CONFIRMED",
                operation_id="r35full:" + _sha(
                    {
                        "releaseOperationId": final["releaseOperationId"],
                        "platformProofs": {
                            p: ledger.r34_saga.child(p).state["commit"]["outcomeProofDigest"]
                            for p in final["releasePolicy"]["requiredPlatforms"]
                        },
                    }
                ),
                request={
                    "requiredPlatforms": final["releasePolicy"]["requiredPlatforms"],
                    "allConfirmed": True,
                },
                new_state=final,
                timestamp_metadata=at_time,
            )
            result = final
    return _clone(result)


def record_compensation_metadata(
    ledger: ReleaseLedger,
    platform: str,
    *,
    reason: str,
    provider_contract_proves_reversible_metadata: bool,
) -> dict[str, Any]:
    _nonempty(reason, "compensation reason")
    child = ledger.r34_saga.child(platform)
    if child.state["state"] != "COMMITTED":
        raise CompensationForbidden("compensation metadata applies only to confirmed posts")
    if not provider_contract_proves_reversible_metadata:
        raise CompensationForbidden(
            "destructive delete/repost is out of scope; reversible metadata proof required"
        )
    new = _clone(ledger.state)
    entry = {
        "platform": platform,
        "reasonDigest": _sha_text(reason),
        "metadataOnly": True,
        "providerDeleteExecuted": False,
        "repostExecuted": False,
        "externalPostStillCommitted": True,
    }
    existing = new["compensations"].get(platform)
    if existing is not None and existing != entry:
        raise ReleaseConflict("compensation metadata conflict")
    new["compensations"][platform] = entry
    ledger._append(
        event_key=f"compensation:{platform}",
        event_type="COMPENSATION_METADATA_RECORDED",
        operation_id="r35comp:" + _sha(
            {
                "releaseOperationId": new["releaseOperationId"],
                "platform": platform,
                "entry": entry,
            }
        ),
        request=entry,
        new_state=new,
        timestamp_metadata="2026-10-05T00:00:09Z",
    )
    return _clone(new)


def release_status(ledger: ReleaseLedger) -> dict[str, Any]:
    state = ledger.state
    next_action = {
        "PREPARED": "ESCROW_RENDER_AND_METADATA",
        "ESCROWED": "RUN_READ_ONLY_PREFLIGHT",
        "PREFLIGHT_GREEN": "VERIFY_OPERATOR_AUTHORIZATION_AND_MARK_CANARY_ELIGIBLE",
        "CANARY_ELIGIBLE": "FAKE_CANARY_COMMIT_ONLY",
        "CANARY_COMMITTING": "RESUME_FROM_DURABLE_CHILD_STATE",
        "CANARY_CONFIRMED": "MARK_EXPANSION_ELIGIBLE",
        "EXPANSION_ELIGIBLE": "FAKE_EXPANSION_COMMIT_NEXT_DECLARED_PLATFORM",
        "EXPANSION_COMMITTING": "CONTINUE_OR_RECONCILE_DECLARED_EXPANSION",
        "FULLY_CONFIRMED": "NONE_ALL_REQUIRED_PLATFORMS_CONFIRMED",
        "HUMAN_REVIEW_REQUIRED": "HUMAN_REVIEW_ONLY",
        "RECONCILIATION_REQUIRED": "READ_ONLY_RECONCILE_ONLY",
        "TERMINALLY_BLOCKED": "NONE_BLOCKED",
    }[state["state"]]
    platforms = {}
    for platform, item in state["platforms"].items():
        child = ledger.r34_saga.child(platform)
        child_status = r33.transaction_status(child)
        platforms[platform] = {
            **_clone(item),
            "durableChildState": child_status["state"],
            "durableChildLedgerDigest": child_status["ledgerDigest"],
            "nextSafeAction": child_status["allowedNextAction"],
            "replayAuthorized": (
                child_status["blindRetryPermitted"]
                and state["state"] != "RECONCILIATION_REQUIRED"
            ),
        }
    value = {
        "contractVersion": STATUS_VERSION,
        "releaseOperationId": state["releaseOperationId"],
        "revisionId": state["revisionId"],
        "state": state["state"],
        "immutableDigest": state["immutableDigest"],
        "winnerSha256": state["winner"]["sha256"],
        "winnerSize": state["winner"]["size"],
        "growthDecisionDigest": state["growthDecisionDigest"],
        "policyDigest": state["policyDigest"],
        "scheduleWindow": _clone(state["scheduleWindow"]),
        "canaryPlatform": state["releasePolicy"]["canaryPlatform"],
        "platforms": platforms,
        "durableEvidence": {
            "r35LedgerDigest": ledger.digest,
            "r34SagaLedgerDigest": ledger.r34_saga.digest,
            "r34AuthorityDigest": _sha(state["r34Authority"]),
            "growthAuthorityDigest": _sha(state["growthR33Authority"]),
            "escrowDigest": None if state["escrow"] is None else _sha(state["escrow"]),
            "preflightDigest": None if state["preflight"] is None else _sha(state["preflight"]),
        },
        "unresolvedOperations": _clone(state["unresolvedOperations"]),
        "blockers": _clone(state["blockers"]),
        "nextPermittedAction": next_action,
        "realProviderEffectAuthorized": False,
        "providerNetworkEffects": 0,
        "livePublish": False,
        "fakeProviderEffects": state["fakeProviderEffects"],
    }
    value["statusDigest"] = _sha(value)
    return value


class DelayedConfirmationProvider(r33.FakeProviderHarness):
    def __init__(self) -> None:
        super().__init__("timeout_after_dispatch")
        self.delayed_lookups = 0

    def lookup(self, state: Mapping[str, Any]) -> dict[str, Any]:
        self.lookup_calls += 1
        self.delayed_lookups += 1
        if self.delayed_lookups == 1:
            return {
                "outcome": "unknown",
                "authoritative": False,
                "reason": "delayed_provider_index",
            }
        existing = self.effects.get(state["idempotencyKey"])
        if existing is None:
            return {
                "outcome": "absent",
                "authoritative": True,
                "requestDigest": state["requestDigest"],
            }
        return _clone(existing)


class ConflictingProviderId(r33.FakeProviderHarness):
    def __init__(self) -> None:
        super().__init__("clean_success")

    def commit(self, state: Mapping[str, Any]) -> dict[str, Any]:
        value = super().commit(state)
        forged = _clone(value)
        forged["externalPostId"] = "fakepost:conflicting-provider-id"
        return forged


def _fixture_growth_advisory() -> dict[str, Any]:
    decision_material = {
        "portfolio": "r35-read-only-advisory-fixture",
        "recommendation": "KEEP",
        "sourceClass": "deterministic_conformance_fixture",
        "liveEvidence": False,
    }
    return {
        "contractVersion": "creator.growth_r33_advisory_input.r35.v1",
        "decisionContract": "growth.adaptive_portfolio_decision.r33.v1",
        "decisionDigest": _sha(decision_material),
        "status": "SHADOW_SOURCE_READY",
        "shadowRecommendation": "KEEP",
        "policyDigest": _sha({"growthPolicyBlob": "0f4da630a87d08ccac2e22dfc307b1abb6120dd9"}),
        "authorityDigest": _sha(GROWTH_R33_AUTHORITY),
        "evidenceBoundary": {
            "shadowOnly": True,
            "creatorMutation": False,
            "providerMutation": False,
            "livePublish": False,
            "humanGroundTruth": False,
        },
    }


def _fixture_release_kwargs() -> dict[str, Any]:
    r34_kwargs = r34._fixture_kwargs()
    r34_spec = r34.build_saga_spec(**r34_kwargs)
    return {
        "r34_saga_spec": r34_spec,
        "growth_advisory": _fixture_growth_advisory(),
        "release_policy": _clone(DEFAULT_RELEASE_POLICY),
        "schedule_window": _clone(r34_spec["releaseWindow"]),
        "revision_id": r34_spec["releaseWindow"]["revision"],
    }


def _fixture_metadata_digest(spec: Mapping[str, Any]) -> str:
    return _sha(
        {
            "platformCopyHashes": spec["platformCopyHashes"],
            "platformAccounts": spec["platformAccounts"],
            "policyDigest": spec["policyDigest"],
        }
    )


def _prepare_escrowed(root: Path) -> tuple[ReleaseLedger, dict[str, Any]]:
    kwargs = _fixture_release_kwargs()
    spec = build_release_spec(**kwargs)
    ledger = ReleaseLedger(root, release_spec=spec)
    escrow_release(
        ledger,
        observed_render_sha256=spec["winner"]["sha256"],
        observed_render_size=spec["winner"]["size"],
        metadata_digest=_fixture_metadata_digest(spec),
    )
    return ledger, spec


def _prepare_preflight(root: Path) -> tuple[ReleaseLedger, dict[str, Any]]:
    ledger, spec = _prepare_escrowed(root)
    preflight_release(
        ledger,
        started_at="2026-10-05T11:30:00Z",
        completed_at="2026-10-05T11:45:00Z",
        observed_policy_digest=spec["policyDigest"],
        observed_growth_decision_digest=spec["growthDecisionDigest"],
    )
    return ledger, spec


def _prepare_canary_eligible(root: Path) -> tuple[ReleaseLedger, dict[str, Any]]:
    ledger, spec = _prepare_preflight(root)
    mark_canary_eligible(
        ledger,
        at_time="2026-10-05T12:01:00Z",
        operator_authorization_digest=spec["releasePolicy"]["operatorAuthorizationDigest"],
    )
    return ledger, spec


def _confirm_canary(root: Path) -> tuple[ReleaseLedger, dict[str, Any], r33.FakeProviderHarness]:
    ledger, spec = _prepare_canary_eligible(root)
    canary = spec["releasePolicy"]["canaryPlatform"]
    provider = r33.FakeProviderHarness("clean_success")
    commit_canary(
        ledger,
        provider,
        at_time="2026-10-05T12:02:00Z",
        observed_account_ref=spec["platformAccounts"][canary]["accountRef"],
    )
    return ledger, spec, provider


def _record_case(results: dict[str, Any], name: str, passed: bool, detail: str) -> None:
    results[name] = {"passed": bool(passed), "detail": detail}


def run_chaos_rehearsal(work_dir: str | os.PathLike[str]) -> dict[str, Any]:
    root = Path(work_dir)
    root.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}

    clean_root = root / "clean-full-confirmation"
    clean, clean_spec, canary_provider = _confirm_canary(clean_root)
    mark_expansion_eligible(clean, at_time="2026-10-05T12:03:00Z")
    expansion_effects = 0
    for index, platform in enumerate(clean_spec["releasePolicy"]["expansionOrder"], 1):
        provider = r33.FakeProviderHarness("clean_success")
        commit_expansion_platform(
            clean,
            platform,
            provider,
            at_time=f"2026-10-05T12:0{3+index}:00Z",
            observed_account_ref=clean_spec["platformAccounts"][platform]["accountRef"],
        )
        expansion_effects += provider.effect_count
    _record_case(results, "clean_full_confirmation", clean.state["state"] == "FULLY_CONFIRMED", clean.state["state"])

    exact = ReleaseLedger(clean_root, release_spec=build_release_spec(**_fixture_release_kwargs()))
    _record_case(results, "exact_replay_byte_stable", exact.digest == clean.digest, exact.state["state"])

    before_root = root / "canary-timeout-before"
    before, before_spec = _prepare_canary_eligible(before_root)
    before_provider = r33.FakeProviderHarness("timeout_before_dispatch")
    state = commit_canary(
        before,
        before_provider,
        at_time="2026-10-05T12:02:00Z",
        observed_account_ref=before_spec["platformAccounts"]["instagram_reels"]["accountRef"],
    )
    _record_case(results, "canary_timeout_before_dispatch", state["state"] == "CANARY_ELIGIBLE" and before_provider.effect_count == 0, state["state"])

    after_root = root / "canary-timeout-after"
    after, after_spec = _prepare_canary_eligible(after_root)
    after_provider = r33.FakeProviderHarness("timeout_after_dispatch")
    state = commit_canary(
        after,
        after_provider,
        at_time="2026-10-05T12:02:00Z",
        observed_account_ref=after_spec["platformAccounts"]["instagram_reels"]["accountRef"],
    )
    _record_case(results, "canary_timeout_after_dispatch", state["state"] == "RECONCILIATION_REQUIRED", state["state"])
    calls = after_provider.commit_calls
    after = ReleaseLedger(after_root)
    _record_case(
        results,
        "restart_after_canary_send_before_ack",
        after.state["state"] == "RECONCILIATION_REQUIRED"
        and after_provider.commit_calls == calls,
        after.state["state"],
    )
    try:
        commit_canary(
            after,
            after_provider,
            at_time="2026-10-05T12:03:00Z",
            observed_account_ref=after_spec["platformAccounts"]["instagram_reels"]["accountRef"],
        )
    except ReconciliationRequired:
        blind_blocked = after_provider.commit_calls == calls
    else:
        blind_blocked = False
    _record_case(results, "unknown_canary_never_blind_retried", blind_blocked, f"calls={after_provider.commit_calls}")

    reconcile_operation(after, "instagram_reels", after_provider, at_time="2026-10-05T12:04:00Z")
    _record_case(results, "canary_read_only_reconcile_confirms", after.state["state"] == "CANARY_CONFIRMED", after.state["state"])

    unknown_root = root / "unknown-no-lookup"
    unknown, unknown_spec = _prepare_canary_eligible(unknown_root)
    unknown_provider = r33.FakeProviderHarness("unknown_no_lookup")
    commit_canary(
        unknown,
        unknown_provider,
        at_time="2026-10-05T12:02:00Z",
        observed_account_ref=unknown_spec["platformAccounts"]["instagram_reels"]["accountRef"],
    )
    reconcile_operation(unknown, "instagram_reels", unknown_provider, at_time="2026-10-05T12:03:00Z")
    _record_case(results, "unknown_lookup_unavailable_stays_reconciliation", unknown.state["state"] == "RECONCILIATION_REQUIRED", unknown.state["state"])

    delayed_root = root / "delayed-confirmation"
    delayed, delayed_spec = _prepare_canary_eligible(delayed_root)
    delayed_provider = DelayedConfirmationProvider()
    commit_canary(
        delayed,
        delayed_provider,
        at_time="2026-10-05T12:02:00Z",
        observed_account_ref=delayed_spec["platformAccounts"]["instagram_reels"]["accountRef"],
    )
    reconcile_operation(delayed, "instagram_reels", delayed_provider, at_time="2026-10-05T12:03:00Z")
    first_delayed = delayed.state["state"] == "RECONCILIATION_REQUIRED"
    reconcile_operation(delayed, "instagram_reels", delayed_provider, at_time="2026-10-05T12:04:00Z")
    _record_case(results, "delayed_confirmation_requires_second_lookup", first_delayed and delayed.state["state"] == "CANARY_CONFIRMED", delayed.state["state"])

    duplicate_root = root / "duplicate-confirmed"
    duplicate, duplicate_spec = _prepare_canary_eligible(duplicate_root)
    duplicate_provider = r34.DuplicateConfirmedAfterDispatch()
    commit_canary(
        duplicate,
        duplicate_provider,
        at_time="2026-10-05T12:02:00Z",
        observed_account_ref=duplicate_spec["platformAccounts"]["instagram_reels"]["accountRef"],
    )
    reconcile_operation(duplicate, "instagram_reels", duplicate_provider, at_time="2026-10-05T12:03:00Z")
    _record_case(results, "duplicate_provider_confirmation", duplicate.state["state"] == "CANARY_CONFIRMED", duplicate.state["state"])

    forged_root = root / "conflicting-provider-id"
    forged, forged_spec = _prepare_canary_eligible(forged_root)
    forged_provider = ConflictingProviderId()
    commit_canary(
        forged,
        forged_provider,
        at_time="2026-10-05T12:02:00Z",
        observed_account_ref=forged_spec["platformAccounts"]["instagram_reels"]["accountRef"],
    )
    _record_case(results, "conflicting_provider_id_requires_reconciliation", forged.state["state"] == "RECONCILIATION_REQUIRED", forged.state["state"])

    wrong_account_root = root / "wrong-canary-account"
    wrong_account, wrong_spec = _prepare_canary_eligible(wrong_account_root)
    wrong_provider = r33.FakeProviderHarness("clean_success")
    commit_canary(
        wrong_account,
        wrong_provider,
        at_time="2026-10-05T12:02:00Z",
        observed_account_ref="wrong-account",
    )
    _record_case(results, "wrong_canary_account_human_review", wrong_account.state["state"] == "HUMAN_REVIEW_REQUIRED" and wrong_provider.commit_calls == 0, wrong_account.state["state"])

    expansion_unknown_root = root / "expansion-unknown"
    expu, expu_spec, _ = _confirm_canary(expansion_unknown_root)
    mark_expansion_eligible(expu, at_time="2026-10-05T12:03:00Z")
    ttp = r33.FakeProviderHarness("timeout_after_dispatch")
    commit_expansion_platform(
        expu,
        "tiktok",
        ttp,
        at_time="2026-10-05T12:04:00Z",
        observed_account_ref=expu_spec["platformAccounts"]["tiktok"]["accountRef"],
    )
    _record_case(results, "expansion_partial_unknown_requires_reconciliation", expu.state["state"] == "RECONCILIATION_REQUIRED", expu.state["state"])
    ttcalls = ttp.commit_calls
    try:
        commit_expansion_platform(
            expu,
            "youtube_shorts",
            r33.FakeProviderHarness("clean_success"),
            at_time="2026-10-05T12:05:00Z",
            observed_account_ref=expu_spec["platformAccounts"]["youtube_shorts"]["accountRef"],
        )
    except ReconciliationRequired:
        isolation = ttp.commit_calls == ttcalls
    else:
        isolation = False
    _record_case(results, "unknown_expansion_blocks_other_expansion", isolation, f"tiktok_calls={ttp.commit_calls}")

    expdup_root = root / "expansion-duplicate"
    expdup, expdup_spec, _ = _confirm_canary(expdup_root)
    mark_expansion_eligible(expdup, at_time="2026-10-05T12:03:00Z")
    ttd = r34.DuplicateConfirmedAfterDispatch()
    commit_expansion_platform(
        expdup,
        "tiktok",
        ttd,
        at_time="2026-10-05T12:04:00Z",
        observed_account_ref=expdup_spec["platformAccounts"]["tiktok"]["accountRef"],
    )
    reconcile_operation(expdup, "tiktok", ttd, at_time="2026-10-05T12:05:00Z")
    _record_case(results, "expansion_duplicate_confirmed", expdup.r34_saga.child("tiktok").state["state"] == "COMMITTED", expdup.state["state"])

    wrong_exp_root = root / "wrong-expansion-account"
    wrong_exp, wrong_exp_spec, _ = _confirm_canary(wrong_exp_root)
    mark_expansion_eligible(wrong_exp, at_time="2026-10-05T12:03:00Z")
    wrong_exp_provider = r33.FakeProviderHarness("clean_success")
    commit_expansion_platform(
        wrong_exp,
        "tiktok",
        wrong_exp_provider,
        at_time="2026-10-05T12:04:00Z",
        observed_account_ref="wrong-expansion-account",
    )
    _record_case(results, "wrong_expansion_account_human_review", wrong_exp.state["state"] == "HUMAN_REVIEW_REQUIRED" and wrong_exp_provider.commit_calls == 0, wrong_exp.state["state"])

    drift_root = root / "drift"
    drift, drift_spec = _prepare_escrowed(drift_root)
    drift_cases = [
        ("changed_render_hash", dict(render_sha256="0" * 64)),
        ("changed_render_size", dict(render_size=drift_spec["winner"]["size"] + 1)),
        ("changed_metadata_digest", dict(metadata_digest="1" * 64)),
        ("stale_growth_decision", dict(growth_decision_digest="2" * 64)),
        ("policy_revision_changed_after_escrow", dict(policy_digest="3" * 64)),
    ]
    for name, kwargs in drift_cases:
        try:
            verify_frozen_identity(drift, **kwargs)
        except ReleaseConflict:
            passed = True
        else:
            passed = False
        _record_case(results, name, passed, "conflict" if passed else "unexpected_accept")

    changed_platforms = _fixture_release_kwargs()
    changed_platforms["release_policy"] = _clone(DEFAULT_RELEASE_POLICY)
    changed_platforms["release_policy"]["requiredPlatforms"] = ["instagram_reels", "tiktok"]
    try:
        build_release_spec(**changed_platforms)
    except ReleaseError:
        changed_platform_ok = True
    else:
        changed_platform_ok = False
    _record_case(results, "changed_platform_set", changed_platform_ok, "fail_closed")

    stale_r34 = _fixture_release_kwargs()
    stale_r34["r34_authority"] = _clone(R34_AUTHORITY)
    stale_r34["r34_authority"]["producerSha"] = "0" * 40
    try:
        build_release_spec(**stale_r34)
    except AuthorityDrift:
        stale_r34_ok = True
    else:
        stale_r34_ok = False
    _record_case(results, "downgraded_r34_authority", stale_r34_ok, "fail_closed")

    stale_growth_auth = _fixture_release_kwargs()
    stale_growth_auth["growth_authority"] = _clone(GROWTH_R33_AUTHORITY)
    stale_growth_auth["growth_authority"]["ciRunId"] = 1
    try:
        build_release_spec(**stale_growth_auth)
    except AuthorityDrift:
        stale_growth_auth_ok = True
    else:
        stale_growth_auth_ok = False
    _record_case(results, "stale_growth_authority", stale_growth_auth_ok, "fail_closed")

    replay_root = root / "replayed-release-id"
    replay_kwargs = _fixture_release_kwargs()
    replay_spec = build_release_spec(**replay_kwargs)
    ReleaseLedger(replay_root, release_spec=replay_spec)
    changed = _clone(replay_spec)
    changed["winner"]["sha256"] = "4" * 64
    try:
        ReleaseLedger(replay_root, release_spec=changed)
    except ReleaseConflict:
        replay_changed_ok = True
    else:
        replay_changed_ok = False
    _record_case(results, "replayed_release_id_changed_bytes", replay_changed_ok, "conflict")

    wrong_release_id = _fixture_release_kwargs()
    wrong_release_id["release_operation_id"] = "r35release:" + "5" * 64
    try:
        build_release_spec(**wrong_release_id)
    except ReleaseConflict:
        wrong_release_ok = True
    else:
        wrong_release_ok = False
    _record_case(results, "changed_release_operation_id", wrong_release_ok, "conflict")

    cross_root = root / "preflight-cross-deadline"
    cross, cross_spec = _prepare_escrowed(cross_root)
    preflight_release(
        cross,
        started_at="2026-10-05T12:59:59Z",
        completed_at="2026-10-05T13:00:01Z",
        observed_policy_digest=cross_spec["policyDigest"],
        observed_growth_decision_digest=cross_spec["growthDecisionDigest"],
    )
    _record_case(results, "clock_crosses_deadline_during_preflight", cross.state["state"] == "TERMINALLY_BLOCKED", cross.state["state"])

    stale_window_root = root / "stale-window-restart"
    stale_window, stale_window_spec = _prepare_canary_eligible(stale_window_root)
    stale_window = ReleaseLedger(stale_window_root)
    stale_provider = r33.FakeProviderHarness("clean_success")
    commit_canary(
        stale_window,
        stale_provider,
        at_time="2026-10-05T13:00:01Z",
        observed_account_ref=stale_window_spec["platformAccounts"]["instagram_reels"]["accountRef"],
    )
    _record_case(results, "stale_window_after_restart", stale_window.state["state"] == "TERMINALLY_BLOCKED" and stale_provider.commit_calls == 0, stale_window.state["state"])

    escrow_restart_root = root / "restart-after-escrow"
    escrow_restart, escrow_restart_spec = _prepare_escrowed(escrow_restart_root)
    escrow_digest = escrow_restart.digest
    escrow_restart = ReleaseLedger(escrow_restart_root)
    preflight_release(
        escrow_restart,
        started_at="2026-10-05T11:30:00Z",
        completed_at="2026-10-05T11:45:00Z",
        observed_policy_digest=escrow_restart_spec["policyDigest"],
        observed_growth_decision_digest=escrow_restart_spec["growthDecisionDigest"],
    )
    _record_case(results, "restart_after_escrow", escrow_restart.digest != escrow_digest and escrow_restart.state["state"] == "PREFLIGHT_GREEN", escrow_restart.state["state"])

    after_confirm_root = root / "restart-after-canary-confirm"
    after_confirm, after_confirm_spec, confirm_provider = _confirm_canary(after_confirm_root)
    calls_before_restart = confirm_provider.commit_calls
    after_confirm = ReleaseLedger(after_confirm_root)
    mark_expansion_eligible(after_confirm, at_time="2026-10-05T12:03:00Z")
    _record_case(results, "restart_after_canary_confirmation", confirm_provider.commit_calls == calls_before_restart and after_confirm.state["state"] == "EXPANSION_ELIGIBLE", after_confirm.state["state"])

    mid_root = root / "restart-mid-expansion"
    mid, mid_spec, _ = _confirm_canary(mid_root)
    mark_expansion_eligible(mid, at_time="2026-10-05T12:03:00Z")
    ttclean = r33.FakeProviderHarness("clean_success")
    commit_expansion_platform(
        mid,
        "tiktok",
        ttclean,
        at_time="2026-10-05T12:04:00Z",
        observed_account_ref=mid_spec["platformAccounts"]["tiktok"]["accountRef"],
    )
    tt_effects = ttclean.effect_count
    mid = ReleaseLedger(mid_root)
    ytclean = r33.FakeProviderHarness("clean_success")
    commit_expansion_platform(
        mid,
        "youtube_shorts",
        ytclean,
        at_time="2026-10-05T12:05:00Z",
        observed_account_ref=mid_spec["platformAccounts"]["youtube_shorts"]["accountRef"],
    )
    _record_case(results, "restart_midway_expansion_no_duplicate", mid.state["state"] == "FULLY_CONFIRMED" and ttclean.effect_count == tt_effects and ytclean.effect_count == 1, mid.state["state"])

    guard_root = root / "growth-cannot-authorize"
    guard, guard_spec = _prepare_preflight(guard_root)
    state = mark_canary_eligible(
        guard,
        at_time="2026-10-05T12:01:00Z",
        operator_authorization_digest=guard_spec["growthDecisionDigest"],
    )
    _record_case(results, "growth_advisory_cannot_authorize", state["state"] == "HUMAN_REVIEW_REQUIRED", state["state"])

    comp_root = root / "compensation"
    comp, comp_spec, _ = _confirm_canary(comp_root)
    try:
        record_compensation_metadata(
            comp,
            "instagram_reels",
            reason="unsafe destructive cleanup request",
            provider_contract_proves_reversible_metadata=False,
        )
    except CompensationForbidden:
        comp_blocked = True
    else:
        comp_blocked = False
    _record_case(results, "destructive_compensation_forbidden", comp_blocked, "blocked")

    comp_ok = record_compensation_metadata(
        comp,
        "instagram_reels",
        reason="reversible metadata workflow marker",
        provider_contract_proves_reversible_metadata=True,
    )
    _record_case(results, "metadata_only_compensation_recorded", comp_ok["compensations"]["instagram_reels"]["externalPostStillCommitted"] is True, "metadata_only")

    policy_bad = _fixture_release_kwargs()
    policy_bad["release_policy"] = _clone(DEFAULT_RELEASE_POLICY)
    policy_bad["release_policy"]["canaryPlatform"] = "unlisted_platform"
    try:
        build_release_spec(**policy_bad)
    except ReleaseError:
        bad_canary_ok = True
    else:
        bad_canary_ok = False
    _record_case(results, "undeclared_canary_platform_rejected", bad_canary_ok, "fail_closed")

    account_config = _fixture_release_kwargs()
    account_spec = build_release_spec(**account_config)
    account_root = root / "changed-account-config"
    ReleaseLedger(account_root, release_spec=account_spec)
    changed_account = _clone(account_spec)
    changed_account["platformAccounts"]["tiktok"]["accountRef"] = "changed"
    try:
        ReleaseLedger(account_root, release_spec=changed_account)
    except ReleaseConflict:
        account_changed_ok = True
    else:
        account_changed_ok = False
    _record_case(results, "same_release_changed_account_config", account_changed_ok, "conflict")

    if len(results) < 25:
        raise AssertionError("R35 chaos harness must execute at least 25 cases")
    failed = sorted(name for name, result in results.items() if not result["passed"])
    if failed:
        raise AssertionError("R35 chaos case failure: " + ", ".join(failed))

    final_status = release_status(clean)
    report = {
        "reportVersion": CHAOS_VERSION,
        "state": "SOURCE_READY_NO_LIVE_PROVIDER",
        "caseCount": len(results),
        "allCasesPassed": not failed,
        "cases": results,
        "r34Authority": _clone(R34_AUTHORITY),
        "growthR33Authority": _clone(GROWTH_R33_AUTHORITY),
        "fullConfirmationStatus": final_status,
        "unknownEffectReconciliationProof": {
            "case": "unknown_canary_never_blind_retried",
            "unknownState": "RECONCILIATION_REQUIRED",
            "blindRetry": False,
            "nextPermittedAction": "READ_ONLY_RECONCILE_ONLY",
        },
        "fakeProviderEffects": 1 + expansion_effects,
        "providerNetworkEffects": 0,
        "realProviderEffects": 0,
        "realProviderEffectAuthorized": False,
        "livePublish": False,
        "credentialsAccessed": False,
    }
    report["reportDigest"] = _sha(report)
    (root / "chaos-rehearsal.r35.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    evidence = {
        "contractVersion": EVIDENCE_VERSION,
        "r34Authority": _clone(R34_AUTHORITY),
        "growthR33Authority": _clone(GROWTH_R33_AUTHORITY),
        "releaseOperationId": clean.state["releaseOperationId"],
        "winnerSha256": clean.state["winner"]["sha256"],
        "winnerSize": clean.state["winner"]["size"],
        "growthDecisionDigest": clean.state["growthDecisionDigest"],
        "policyDigest": clean.state["policyDigest"],
        "r35LedgerDigest": clean.digest,
        "r34SagaLedgerDigest": clean.r34_saga.digest,
        "finalStatusDigest": final_status["statusDigest"],
        "chaosReportDigest": report["reportDigest"],
        "caseCount": len(results),
        "allCasesPassed": True,
        "unknownEffectNeverBlindRetried": True,
        "providerNetworkEffects": 0,
        "realProviderEffects": 0,
        "realProviderEffectAuthorized": False,
        "livePublish": False,
    }
    evidence["evidenceDigest"] = _sha(evidence)
    (root / "evidence-manifest.r35.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "final-status.r35.json").write_text(
        json.dumps(final_status, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def readiness() -> dict[str, Any]:
    validate_r34_authority(R34_AUTHORITY)
    validate_growth_r33_authority(GROWTH_R33_AUTHORITY)
    value = {
        "reportVersion": READINESS_VERSION,
        "state": "SOURCE_READY_NO_LIVE_PROVIDER",
        "SOURCE_READY": True,
        "LIVE_PROVIDER_ENABLED": False,
        "contract": CONTRACT_VERSION,
        "r34Authority": _clone(R34_AUTHORITY),
        "growthR33Authority": _clone(GROWTH_R33_AUTHORITY),
        "phases": list(STATES),
        "defaultReleasePolicy": _clone(DEFAULT_RELEASE_POLICY),
        "safety": {
            "fakeProviderOnly": True,
            "providerNetworkEffects": 0,
            "realProviderEffects": 0,
            "realProviderEffectAuthorized": False,
            "livePublish": False,
            "credentialsAccessed": False,
            "blindRetryAfterUnknown": False,
            "automaticDestructiveCompensation": False,
            "growthAdvisoryCanAuthorizeMutation": False,
            "mergePerformed": False,
        },
        "blockers": [
            {
                "code": "LIVE_PROVIDER_OUT_OF_SCOPE_R35",
                "detail": "R35 is source-ready fake-provider escrow/canary control only",
            }
        ],
    }
    value["reportDigest"] = _sha(value)
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="creator-release-escrow-r35")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("readiness")
    p.add_argument("--out")
    p = sub.add_parser("status")
    p.add_argument("--release-dir", required=True)
    p.add_argument("--out")
    p = sub.add_parser("chaos-rehearsal")
    p.add_argument("--out", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "readiness":
        value = readiness()
    elif args.command == "status":
        value = release_status(ReleaseLedger(args.release_dir))
    else:
        value = run_chaos_rehearsal(args.out)
    if getattr(args, "out", None) and args.command != "chaos-rehearsal":
        Path(args.out).write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
