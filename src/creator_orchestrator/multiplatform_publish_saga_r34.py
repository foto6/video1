from __future__ import annotations

import argparse
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import autonomous_reels as reels
from . import publish_transaction_r33 as r33

CONTRACT_VERSION = "creator.multiplatform_publish_saga.r34.v1"
LEDGER_VERSION = "creator.multiplatform_publish_saga_ledger.r34.v1"
STATUS_VERSION = "creator.multiplatform_publish_saga_status.r34.v1"
READINESS_VERSION = "creator.multiplatform_publish_saga_readiness.r34.v1"
REHEARSAL_VERSION = "creator.multiplatform_publish_saga_rehearsal.r34.v1"
EVIDENCE_VERSION = "creator.multiplatform_publish_saga_evidence.r34.v1"

REQUIRED_PLATFORMS = ("instagram_reels", "tiktok", "youtube_shorts")
SAGA_STATES = {
    "ALL_PENDING",
    "PARTIALLY_COMMITTED",
    "RECONCILIATION_REQUIRED",
    "ALL_COMMITTED",
    "TERMINAL_BLOCKED",
}

QA_R3_ACCEPTANCE = {
    "contractVersion": "creator.r34_parent_qa_r3_acceptance.v1",
    "qaAuthority": {
        "repository": "foto6/boss",
        "branch": "agent/video-hardwave-acceptance-r3-20261004",
        "exactSha": "2a48c909bfb5785409b591253f6085642b962d0d",
        "ciRunId": 37207701514,
        "ciConclusion": "success",
        "artifactId": 11305557095,
        "artifactName": "hard-wave-acceptance-r3-2a48c909bfb5785409b591253f6085642b962d0d",
        "artifactDigest": "sha256:4c5cb2c476643a03865ec37c084650db4c98c84c3aed04aafeb35b81b4e9fba0",
        "blobPins": {
            "status": "4e71a7a46ddb71031b7a6aa622efaa63209fef02",
            "authorityFixture": "68f304b786df348d72a44be5baced1c1f3aa3d8c",
            "acceptanceRuntime": "34f8be83d8c9e50ee2e4127d04aba66b8c943fd2",
            "acceptanceTests": "b9e329132bc68616874e5d43cb8a81da261ba7b9",
            "documentation": "aaa0463b9a4cbe16e8ea6f75b7efaf6397652a3c",
            "checkpoint": "75874e2d6a4f5c13320439ddb9b87ce660f25894",
        },
    },
    "acceptedParent": {
        "repository": "foto6/video1",
        "producerSha": "9556108f423a15a40614a8bc9d590e6dc2e49746",
        "ciRunId": 37203622591,
        "artifactId": 11304071297,
        "artifactName": "creator-r33-publish-transaction-9556108f423a15a40614a8bc9d590e6dc2e49746",
        "artifactDigest": "sha256:adbfb6d257332220e2be2f9d8f134a87f8bcc6b6e064dfac7f469fd95d690d6d",
        "contract": r33.CONTRACT_VERSION,
        "manifestBlob": "503c0eb63efaeb540ce15407c662c2192b956c87",
        "schemaBlob": "ea1646b8ecd7114ae7d9878c9db09835c7e88a88",
        "runtimeBlob": "7ea1d1f23d28cc8e349d308ec18dd960c2721d6a",
        "readinessBlob": "5453ab9ef197be45d1b67d4b7aea09a277981c6f",
    },
    "disposition": "ACCEPTED",
    "publishTransactionStatus": "PUBLISH_TRANSACTION_SOURCE_READY",
    "r34IndependentQa": {
        "status": "PENDING",
        "accepted": False,
        "liveReady": False,
    },
    "safety": {
        "fakeProviderOnly": True,
        "providerNetworkEffects": 0,
        "livePublish": False,
        "blindRetryAfterUnknown": False,
    },
}

PARENT_R33_AUTHORITY = {
    "repository": "foto6/video1",
    "producerSha": "9556108f423a15a40614a8bc9d590e6dc2e49746",
    "ciRunId": 37203622591,
    "artifactId": 11304071297,
    "artifactName": "creator-r33-publish-transaction-9556108f423a15a40614a8bc9d590e6dc2e49746",
    "artifactDigest": "sha256:adbfb6d257332220e2be2f9d8f134a87f8bcc6b6e064dfac7f469fd95d690d6d",
    "contract": r33.CONTRACT_VERSION,
    "contractBlobs": {
        "runtime": "7ea1d1f23d28cc8e349d308ec18dd960c2721d6a",
        "schema": "ea1646b8ecd7114ae7d9878c9db09835c7e88a88",
        "manifest": "503c0eb63efaeb540ce15407c662c2192b956c87",
        "r32Authority": "09f6ef3a0dafce34f934a5d807a4cd109a08e24b",
        "readinessReport": "5453ab9ef197be45d1b67d4b7aea09a277981c6f",
    },
    "qaR3": {
        "status": "ACCEPTED",
        "accepted": True,
        "disposition": "PUBLISH_TRANSACTION_SOURCE_READY",
        "acceptanceEvidence": QA_R3_ACCEPTANCE,
    },
}


class SagaError(ValueError):
    pass


class SagaAuthorityDrift(SagaError):
    pass


class SagaConflict(SagaError):
    pass


class SagaTransitionError(SagaError):
    pass


class SagaScheduleError(SagaError):
    pass


class SagaParentQaPending(SagaError):
    pass


def _clone(value: Any) -> Any:
    return json.loads(reels.canonical_json(value))


def _sha(value: Any) -> str:
    return reels.sha256_json(value)


def _sha_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _parse_utc(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise SagaScheduleError(f"{field} must be non-empty ISO-8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SagaScheduleError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise SagaScheduleError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def _validate_window(window: Mapping[str, Any]) -> dict[str, Any]:
    required = {"start", "deadline", "revision"}
    if not isinstance(window, Mapping) or set(window) != required:
        raise SagaScheduleError("release window fields mismatch")
    start = _parse_utc(window["start"], "releaseWindow.start")
    deadline = _parse_utc(window["deadline"], "releaseWindow.deadline")
    if start >= deadline:
        raise SagaScheduleError("release window start must precede deadline")
    revision = window["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise SagaScheduleError("release window revision must be nonnegative integer")
    return {
        "start": window["start"],
        "deadline": window["deadline"],
        "revision": revision,
    }


def _window_state(window: Mapping[str, Any], at_time: str) -> str:
    now = _parse_utc(at_time, "at_time")
    start = _parse_utc(window["start"], "releaseWindow.start")
    deadline = _parse_utc(window["deadline"], "releaseWindow.deadline")
    if now < start:
        return "BEFORE_WINDOW"
    if now > deadline:
        return "AFTER_DEADLINE"
    return "OPEN"


def validate_parent_qa_r3_acceptance(
    value: Mapping[str, Any],
    *,
    parent_r33_authority: Mapping[str, Any],
) -> dict[str, Any]:
    if value != QA_R3_ACCEPTANCE:
        raise SagaAuthorityDrift("QA-R3 acceptance evidence drift")
    accepted = value["acceptedParent"]
    exact_parent = {
        "repository": parent_r33_authority["repository"],
        "producerSha": parent_r33_authority["producerSha"],
        "ciRunId": parent_r33_authority["ciRunId"],
        "artifactId": parent_r33_authority["artifactId"],
        "artifactName": parent_r33_authority["artifactName"],
        "artifactDigest": parent_r33_authority["artifactDigest"],
        "contract": parent_r33_authority["contract"],
        "manifestBlob": parent_r33_authority["contractBlobs"]["manifest"],
        "schemaBlob": parent_r33_authority["contractBlobs"]["schema"],
        "runtimeBlob": parent_r33_authority["contractBlobs"]["runtime"],
        "readinessBlob": parent_r33_authority["contractBlobs"]["readinessReport"],
    }
    if accepted != exact_parent:
        raise SagaAuthorityDrift("QA-R3 accepted a different R33 authority")
    if (
        value["disposition"] != "ACCEPTED"
        or value["publishTransactionStatus"] != "PUBLISH_TRANSACTION_SOURCE_READY"
        or value["r34IndependentQa"] != {
            "status": "PENDING",
            "accepted": False,
            "liveReady": False,
        }
    ):
        raise SagaAuthorityDrift("QA-R3 disposition drift")
    return _clone(value)


def validate_parent_r33_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    if value != PARENT_R33_AUTHORITY:
        raise SagaAuthorityDrift("Creator R33 parent authority drift")
    qa = value.get("qaR3")
    if (
        not isinstance(qa, Mapping)
        or qa.get("status") != "ACCEPTED"
        or qa.get("accepted") is not True
        or qa.get("disposition") != "PUBLISH_TRANSACTION_SOURCE_READY"
    ):
        raise SagaAuthorityDrift("Creator R33 parent QA-R3 status drift")
    validate_parent_qa_r3_acceptance(
        qa.get("acceptanceEvidence"),
        parent_r33_authority=value,
    )
    return _clone(value)


def _validate_release_policy(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {
            "mode": "all_required",
            "requiredPlatforms": list(REQUIRED_PLATFORMS),
            "minimumCommittedPlatforms": 3,
        }
    if not isinstance(value, Mapping):
        raise SagaError("release policy must be an object")
    mode = value.get("mode")
    required = value.get("requiredPlatforms")
    minimum = value.get("minimumCommittedPlatforms")
    if mode not in {"all_required", "explicit_partial"}:
        raise SagaError("unsupported release policy mode")
    if required != list(REQUIRED_PLATFORMS):
        raise SagaError("R34 requires exact Instagram/TikTok/YouTube platform set")
    if isinstance(minimum, bool) or not isinstance(minimum, int):
        raise SagaError("minimumCommittedPlatforms must be integer")
    if mode == "all_required" and minimum != 3:
        raise SagaError("all_required policy requires all three platforms")
    if mode == "explicit_partial" and not 1 <= minimum <= 3:
        raise SagaError("explicit partial threshold must be 1..3")
    return {
        "mode": mode,
        "requiredPlatforms": list(REQUIRED_PLATFORMS),
        "minimumCommittedPlatforms": minimum,
    }


def _validate_platform_configs(configs: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(configs, Mapping) or set(configs) != set(REQUIRED_PLATFORMS):
        raise SagaError("platform configs must contain exactly Instagram, TikTok and YouTube")
    normalized: dict[str, dict[str, Any]] = {}
    required = {
        "providerAdapter",
        "accountRef",
        "destination",
        "credentialRef",
        "authorizationRef",
        "configurationRef",
        "configRevision",
        "caption",
        "title",
        "thumbnailSha256",
        "mediaMetadata",
    }
    for platform in REQUIRED_PLATFORMS:
        value = configs[platform]
        if not isinstance(value, Mapping) or set(value) != required:
            raise SagaError(f"{platform} config fields mismatch")
        revision = value["configRevision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise SagaError(f"{platform} configRevision invalid")
        # Reuse R33's exact local target/media validation through a full spec later.
        normalized[platform] = _clone(value)
    return normalized


def _child_idempotency_key(
    *,
    platform: str,
    winner: Mapping[str, Any],
    config: Mapping[str, Any],
    release_window: Mapping[str, Any],
    release_policy: Mapping[str, Any],
) -> str:
    material = {
        "contractVersion": CONTRACT_VERSION,
        "platform": platform,
        "winnerSha256": winner["sha256"],
        "winnerSize": winner["size"],
        "captionSha256": _sha_text(config["caption"]),
        "titleSha256": _sha_text(config["title"]),
        "thumbnailSha256": config["thumbnailSha256"],
        "releaseWindow": _clone(release_window),
        "providerAdapter": config["providerAdapter"],
        "accountRef": config["accountRef"],
        "destination": config["destination"],
        "configurationRef": config["configurationRef"],
        "configRevision": config["configRevision"],
        "releasePolicy": _clone(release_policy),
    }
    return f"r34idem:{platform}:" + _sha(material)


def build_saga_spec(
    *,
    upstream_state: Mapping[str, Any],
    handoff: Mapping[str, Any],
    upstream_outcome: str,
    platform_configs: Mapping[str, Any],
    release_window: Mapping[str, Any],
    release_policy: Mapping[str, Any] | None = None,
    parent_r33_authority: Mapping[str, Any] = PARENT_R33_AUTHORITY,
) -> dict[str, Any]:
    parent = validate_parent_r33_authority(parent_r33_authority)
    window = _validate_window(release_window)
    policy = _validate_release_policy(release_policy)
    configs = _validate_platform_configs(platform_configs)

    child_specs: dict[str, dict[str, Any]] = {}
    for platform in REQUIRED_PLATFORMS:
        config = configs[platform]
        key = _child_idempotency_key(
            platform=platform,
            winner=handoff["finalArtifact"],
            config=config,
            release_window=window,
            release_policy=policy,
        )
        publish_policy = {
            "r34SagaContract": CONTRACT_VERSION,
            "releaseWindow": window,
            "releasePolicy": policy,
            "configRevision": config["configRevision"],
        }
        child_specs[platform] = r33.build_prepare_spec(
            upstream_state=upstream_state,
            handoff=handoff,
            upstream_outcome=upstream_outcome,
            platform=platform,
            provider_adapter=config["providerAdapter"],
            account_ref=config["accountRef"],
            destination=config["destination"],
            credential_ref=config["credentialRef"],
            authorization_ref=config["authorizationRef"],
            configuration_ref=config["configurationRef"],
            media_metadata=config["mediaMetadata"],
            caption=config["caption"],
            title=config["title"],
            thumbnail_sha256=config["thumbnailSha256"],
            publish_policy=publish_policy,
            planned_publish_at=window["start"],
            revision=window["revision"],
            explicit_idempotency_key=key,
        )

    first = child_specs[REQUIRED_PLATFORMS[0]]
    winner = _clone(first["winner"])
    lineage = _clone(first["lineage"])
    for platform in REQUIRED_PLATFORMS[1:]:
        child = child_specs[platform]
        if child["winner"] != winner or child["lineage"] != lineage:
            raise SagaConflict("child transaction winner/lineage divergence")

    immutable = {
        "contractVersion": CONTRACT_VERSION,
        "parentR33Authority": parent,
        "r32Authority": _clone(first["r32Authority"]),
        "winner": winner,
        "lineage": lineage,
        "releaseWindow": window,
        "releasePolicy": policy,
        "platforms": {
            platform: {
                "transactionId": child_specs[platform]["transactionId"],
                "idempotencyKey": child_specs[platform]["idempotencyKey"],
                "requestDigest": child_specs[platform]["requestDigest"],
                "target": _clone(child_specs[platform]["target"]),
                "contentHashes": _clone(child_specs[platform]["contentHashes"]),
                "publishPolicyHash": child_specs[platform]["publishPolicyHash"],
                "configRevision": configs[platform]["configRevision"],
            }
            for platform in REQUIRED_PLATFORMS
        },
    }
    saga_id = "r34saga:" + _sha(immutable)
    return {
        "contractVersion": CONTRACT_VERSION,
        "sagaId": saga_id,
        "parentR33Authority": parent,
        "parentQaStatus": "ACCEPTED_QA_R3",
        "r32Authority": _clone(first["r32Authority"]),
        "winner": winner,
        "lineage": lineage,
        "releaseWindow": window,
        "releasePolicy": policy,
        "childSpecs": child_specs,
        "configRevisions": {
            platform: configs[platform]["configRevision"]
            for platform in REQUIRED_PLATFORMS
        },
        "immutableDigest": _sha(immutable),
    }


class SagaLedger:
    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        saga_spec: Mapping[str, Any] | None = None,
    ) -> None:
        self.root = Path(root)
        self.path = self.root / "multiplatform-publish-saga-ledger.jsonl"
        self.events: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        self.state: dict[str, Any] = {}
        if self.path.exists():
            self._load()
            if saga_spec is not None:
                self.assert_identity(saga_spec)
                self._ensure_children(saga_spec)
            return
        if saga_spec is None:
            raise SagaError("new saga ledger requires saga_spec")
        self.root.mkdir(parents=True, exist_ok=True)
        self._ensure_children(saga_spec)
        initial = {
            "contractVersion": CONTRACT_VERSION,
            "sagaId": saga_spec["sagaId"],
            "immutableDigest": saga_spec["immutableDigest"],
            "parentR33Authority": _clone(saga_spec["parentR33Authority"]),
            "parentQaStatus": saga_spec["parentQaStatus"],
            "r32Authority": _clone(saga_spec["r32Authority"]),
            "winner": _clone(saga_spec["winner"]),
            "lineage": _clone(saga_spec["lineage"]),
            "releaseWindow": _clone(saga_spec["releaseWindow"]),
            "releasePolicy": _clone(saga_spec["releasePolicy"]),
            "platformIdentity": {
                platform: {
                    "transactionId": saga_spec["childSpecs"][platform]["transactionId"],
                    "idempotencyKey": saga_spec["childSpecs"][platform]["idempotencyKey"],
                    "requestDigest": saga_spec["childSpecs"][platform]["requestDigest"],
                    "target": _clone(saga_spec["childSpecs"][platform]["target"]),
                    "contentHashes": _clone(saga_spec["childSpecs"][platform]["contentHashes"]),
                    "publishPolicyHash": saga_spec["childSpecs"][platform]["publishPolicyHash"],
                    "configRevision": saga_spec["configRevisions"][platform],
                    "ledgerFile": f"transactions/{platform}.jsonl",
                }
                for platform in REQUIRED_PLATFORMS
            },
            "validationBlocks": {},
            "compensations": {},
            "sagaState": "ALL_PENDING",
            "platformStates": {},
            "globalSuccess": False,
            "blockers": [],
            "livePublish": False,
            "providerNetworkEffects": 0,
        }
        initial = self._snapshot(initial)
        self._append(
            event_key="saga-prepared",
            event_type="SAGA_PREPARED",
            operation_id="r34prepare:" + _sha(
                {
                    "sagaId": initial["sagaId"],
                    "immutableDigest": initial["immutableDigest"],
                }
            ),
            request={
                "sagaId": initial["sagaId"],
                "immutableDigest": initial["immutableDigest"],
            },
            new_state=initial,
            timestamp_metadata="2026-10-04T00:00:00Z",
            previous_state={},
        )

    def child_path(self, platform: str) -> Path:
        if platform not in REQUIRED_PLATFORMS:
            raise SagaError("unknown platform")
        return self.root / "transactions" / f"{platform}.jsonl"

    def child(self, platform: str) -> r33.TransactionLedger:
        return r33.TransactionLedger(self.child_path(platform))

    def _ensure_children(self, spec: Mapping[str, Any]) -> None:
        tx_dir = self.root / "transactions"
        tx_dir.mkdir(parents=True, exist_ok=True)
        for platform in REQUIRED_PLATFORMS:
            r33.TransactionLedger(
                tx_dir / f"{platform}.jsonl",
                prepared_spec=spec["childSpecs"][platform],
            )

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
                raise SagaConflict(f"invalid saga ledger JSON line {line_number}") from exc
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
                raise SagaConflict("saga ledger event shape/version mismatch")
            if event["sequence"] != len(self.events) + 1:
                raise SagaConflict("saga ledger sequence mismatch")
            if event["eventKey"] in self.by_key:
                raise SagaConflict("duplicate saga ledger event key")
            if event["previousStateDigest"] != _sha(self.state):
                raise SagaConflict("saga ledger previous-state chain mismatch")
            if event["newStateDigest"] != _sha(event["newState"]):
                raise SagaConflict("saga ledger new-state digest mismatch")
            identity = {
                key: value
                for key, value in event.items()
                if key not in {"timestampMetadata", "eventDigest"}
            }
            if event["eventDigest"] != _sha(identity):
                raise SagaConflict("saga ledger event digest mismatch")
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
            ):
                raise SagaConflict(f"conflicting saga replay for {event_key}")
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
            if key != "timestampMetadata"
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
        if spec["sagaId"] != self.state.get("sagaId"):
            raise SagaConflict("saga identity changed")
        if spec["immutableDigest"] != self.state.get("immutableDigest"):
            raise SagaConflict("saga immutable payload/config changed")
        if spec["parentR33Authority"] != self.state.get("parentR33Authority"):
            raise SagaConflict("parent R33 authority changed")
        if spec["releaseWindow"] != self.state.get("releaseWindow"):
            raise SagaConflict("release window revision drift")
        if spec["releasePolicy"] != self.state.get("releasePolicy"):
            raise SagaConflict("release policy changed")

    def _snapshot(self, base: Mapping[str, Any] | None = None) -> dict[str, Any]:
        current = _clone(base if base is not None else self.state)
        platform_states: dict[str, Any] = {}
        states: list[str] = []
        for platform in REQUIRED_PLATFORMS:
            child = self.child(platform)
            status = r33.transaction_status(child)
            states.append(status["state"])
            platform_states[platform] = {
                "state": status["state"],
                "transactionId": status["transactionId"],
                "idempotencyKey": status["idempotencyKey"],
                "requestDigest": status["requestDigest"],
                "allowedNextAction": status["allowedNextAction"],
                "blindRetryPermitted": status["blindRetryPermitted"],
                "providerInvocationStarted": status["providerInvocationStarted"],
                "externalOperationConfirmed": status["externalOperationConfirmed"],
                "externalPostConfirmed": status["externalPostConfirmed"],
                "blockers": _clone(status["blockers"]),
                "ledgerDigest": status["ledgerDigest"],
            }

        any_unknown = any(
            item["state"] == "RECONCILIATION_REQUIRED"
            or (
                item["state"] == "COMMITTING"
                and item["providerInvocationStarted"]
            )
            for item in platform_states.values()
        )
        committed = sum(item["state"] == "COMMITTED" for item in platform_states.values())
        aborted = sum(item["state"] == "ABORTED" for item in platform_states.values())

        if committed == len(REQUIRED_PLATFORMS):
            saga_state = "ALL_COMMITTED"
        elif any_unknown:
            saga_state = "RECONCILIATION_REQUIRED"
        elif aborted:
            saga_state = "TERMINAL_BLOCKED"
        elif committed:
            saga_state = "PARTIALLY_COMMITTED"
        else:
            saga_state = "ALL_PENDING"

        policy = current["releasePolicy"]
        if policy["mode"] == "all_required":
            global_success = committed == len(REQUIRED_PLATFORMS)
        else:
            global_success = (
                committed >= policy["minimumCommittedPlatforms"]
                and not any_unknown
            )

        blockers: list[dict[str, Any]] = []
        for platform, item in platform_states.items():
            if item["state"] == "RECONCILIATION_REQUIRED" or (
                item["state"] == "COMMITTING" and item["providerInvocationStarted"]
            ):
                blockers.append(
                    {
                        "code": "PLATFORM_RECONCILIATION_REQUIRED",
                        "platform": platform,
                        "blindRetryForbidden": True,
                    }
                )
            if item["state"] == "ABORTED":
                blockers.append(
                    {
                        "code": "PLATFORM_ABORTED",
                        "platform": platform,
                        "globalSuccessBlockedUnderDefaultPolicy": (
                            policy["mode"] == "all_required"
                        ),
                    }
                )
        for platform, block in current.get("validationBlocks", {}).items():
            blockers.append(
                {
                    "code": "PLATFORM_VALIDATION_REJECTED",
                    "platform": platform,
                    "reasonCode": block["reasonCode"],
                }
            )

        current["platformStates"] = platform_states
        current["sagaState"] = saga_state
        current["globalSuccess"] = global_success
        current["blockers"] = blockers
        current["livePublish"] = False
        current["providerNetworkEffects"] = 0
        return current

    def sync(
        self,
        *,
        event_key: str,
        event_type: str,
        operation_id: str,
        request: Mapping[str, Any],
        timestamp_metadata: str = "2026-10-04T00:00:01Z",
    ) -> dict[str, Any]:
        new = self._snapshot()
        if new == self.state:
            return _clone(new)
        self._append(
            event_key=event_key,
            event_type=event_type,
            operation_id=operation_id,
            request=request,
            new_state=new,
            timestamp_metadata=timestamp_metadata,
        )
        return _clone(new)

    @property
    def digest(self) -> str:
        return _sha(self.events)


def prepare_saga(
    root: str | os.PathLike[str],
    **kwargs: Any,
) -> SagaLedger:
    spec = build_saga_spec(**kwargs)
    return SagaLedger(root, saga_spec=spec)


def validate_platform(saga: SagaLedger, platform: str) -> dict[str, Any]:
    child = saga.child(platform)
    state = r33.validate_prepared(child)
    saga.sync(
        event_key=f"validated:{platform}",
        event_type="PLATFORM_VALIDATED",
        operation_id="r34validate:" + _sha(
            {
                "sagaId": saga.state["sagaId"],
                "platform": platform,
                "validationDigest": state["validationDigest"],
            }
        ),
        request={
            "platform": platform,
            "validationDigest": state["validationDigest"],
        },
    )
    return _clone(state)


def mark_platform_commit_eligible(
    saga: SagaLedger,
    platform: str,
) -> dict[str, Any]:
    child = saga.child(platform)
    state = r33.mark_commit_eligible(child)
    saga.sync(
        event_key=f"eligible:{platform}",
        event_type="PLATFORM_COMMIT_ELIGIBLE",
        operation_id="r34eligible:" + _sha(
            {
                "sagaId": saga.state["sagaId"],
                "platform": platform,
                "requestDigest": state["requestDigest"],
            }
        ),
        request={
            "platform": platform,
            "requestDigest": state["requestDigest"],
        },
    )
    return _clone(state)


def reject_platform_validation(
    saga: SagaLedger,
    platform: str,
    *,
    reason_code: str,
) -> dict[str, Any]:
    if not isinstance(reason_code, str) or not reason_code:
        raise SagaError("reason_code required")
    child = saga.child(platform)
    if child.state["state"] not in {"PREPARED", "VALIDATED"}:
        raise SagaTransitionError("validation rejection only before commit eligibility")
    r33.abort_transaction(
        child,
        reason=f"r34_validation_rejected:{reason_code}",
    )
    new = _clone(saga.state)
    existing = new.setdefault("validationBlocks", {}).get(platform)
    payload = {
        "reasonCode": reason_code,
        "reasonDigest": _sha_text(reason_code),
        "providerEffect": False,
    }
    if existing is not None and existing != payload:
        raise SagaConflict("changed validation rejection under same saga")
    new["validationBlocks"][platform] = payload
    new = saga._snapshot(new)
    saga._append(
        event_key=f"validation-rejected:{platform}",
        event_type="PLATFORM_VALIDATION_REJECTED",
        operation_id="r34validationreject:" + _sha(
            {
                "sagaId": saga.state["sagaId"],
                "platform": platform,
                "reasonDigest": payload["reasonDigest"],
            }
        ),
        request={
            "platform": platform,
            "reasonCode": reason_code,
        },
        new_state=new,
        timestamp_metadata="2026-10-04T00:00:02Z",
    )
    return _clone(new)


def commit_platform(
    saga: SagaLedger,
    platform: str,
    adapter: Any,
    *,
    at_time: str,
) -> dict[str, Any]:
    window_state = _window_state(saga.state["releaseWindow"], at_time)
    if window_state == "BEFORE_WINDOW":
        raise SagaScheduleError("publish window has not opened")
    if window_state == "AFTER_DEADLINE":
        raise SagaScheduleError("publish deadline has passed")
    child = saga.child(platform)
    if child.state["state"] == "RECONCILIATION_REQUIRED":
        raise r33.ReconciliationRequired(
            "platform outcome unknown; saga forbids blind replay"
        )
    before_calls = getattr(adapter, "commit_calls", None)
    state = r33.commit_transaction(child, adapter)
    after_calls = getattr(adapter, "commit_calls", None)
    if (
        before_calls is not None
        and after_calls is not None
        and state["state"] == "RECONCILIATION_REQUIRED"
        and after_calls < before_calls
    ):
        raise AssertionError("provider call accounting regressed")
    saga.sync(
        event_key=f"commit-sync:{platform}:{state['commit']['attemptNumber']}:{state['state']}",
        event_type="PLATFORM_COMMIT_SYNC",
        operation_id=state["commit"]["attemptId"]
        or "r34commit:" + state["transactionId"],
        request={
            "platform": platform,
            "atTime": at_time,
            "childState": state["state"],
            "requestDigest": state["requestDigest"],
        },
        timestamp_metadata="2026-10-04T00:00:03Z",
    )
    return _clone(state)


def reconcile_platform(
    saga: SagaLedger,
    platform: str,
    adapter: Any,
) -> dict[str, Any]:
    child = saga.child(platform)
    state = r33.reconcile_transaction(child, adapter)
    saga.sync(
        event_key=f"reconcile-sync:{platform}:{state['state']}:{_sha(state['commit'])[:16]}",
        event_type="PLATFORM_RECONCILIATION_SYNC",
        operation_id=state["commit"]["attemptId"]
        or "r34reconcile:" + state["transactionId"],
        request={
            "platform": platform,
            "childState": state["state"],
            "outcomeProofDigest": state["commit"]["outcomeProofDigest"],
        },
        timestamp_metadata="2026-10-04T00:00:04Z",
    )
    return _clone(state)


def abort_platform(
    saga: SagaLedger,
    platform: str,
    *,
    reason: str,
) -> dict[str, Any]:
    child = saga.child(platform)
    state = r33.abort_transaction(child, reason=reason)
    saga.sync(
        event_key=f"abort-sync:{platform}",
        event_type="PLATFORM_ABORT_SYNC",
        operation_id="r34abort:" + _sha(
            {
                "sagaId": saga.state["sagaId"],
                "platform": platform,
                "reasonDigest": _sha_text(reason),
            }
        ),
        request={
            "platform": platform,
            "reasonDigest": _sha_text(reason),
        },
        timestamp_metadata="2026-10-04T00:00:05Z",
    )
    return _clone(state)


def record_compensation_metadata(
    saga: SagaLedger,
    platform: str,
    *,
    reason: str,
) -> dict[str, Any]:
    child = saga.child(platform)
    if child.state["state"] != "COMMITTED":
        raise SagaTransitionError(
            "compensation metadata applies only to an externally committed child"
        )
    if not isinstance(reason, str) or not reason:
        raise SagaError("compensation reason required")
    new = _clone(saga.state)
    payload = {
        "requested": True,
        "reasonDigest": _sha_text(reason),
        "providerDeleteContractAvailable": False,
        "providerDeleteExecuted": False,
        "localRollbackClaimed": False,
        "externalPostStillCommitted": True,
        "workflowAction": "MANUAL_OR_FUTURE_VERIFIED_DELETE_CONTRACT",
    }
    existing = new.setdefault("compensations", {}).get(platform)
    if existing is not None and existing != payload:
        raise SagaConflict("changed compensation metadata under same operation")
    new["compensations"][platform] = payload
    new = saga._snapshot(new)
    saga._append(
        event_key=f"compensation-metadata:{platform}",
        event_type="COMPENSATION_METADATA_RECORDED",
        operation_id="r34compensation:" + _sha(
            {
                "sagaId": saga.state["sagaId"],
                "platform": platform,
                "reasonDigest": payload["reasonDigest"],
            }
        ),
        request={
            "platform": platform,
            "reasonDigest": payload["reasonDigest"],
            "providerDeleteContractAvailable": False,
        },
        new_state=new,
        timestamp_metadata="2026-10-04T00:00:06Z",
    )
    return _clone(new)


def saga_status(
    saga: SagaLedger,
    *,
    at_time: str | None = None,
) -> dict[str, Any]:
    state = saga._snapshot()
    per_platform: dict[str, Any] = {}
    for platform in REQUIRED_PLATFORMS:
        item = state["platformStates"][platform]
        next_action = item["allowedNextAction"]
        replay_authorized = item["blindRetryPermitted"]
        if item["state"] == "COMMIT_ELIGIBLE":
            if at_time is None:
                next_action = "COMMIT_FAKE_PROVIDER_WHEN_WINDOW_OPEN"
            else:
                window_state = _window_state(state["releaseWindow"], at_time)
                if window_state == "BEFORE_WINDOW":
                    next_action = "WAIT_FOR_RELEASE_WINDOW"
                    replay_authorized = False
                elif window_state == "AFTER_DEADLINE":
                    next_action = "BLOCKED_RELEASE_DEADLINE_PASSED"
                    replay_authorized = False
                else:
                    next_action = "COMMIT_FAKE_PROVIDER"
                    replay_authorized = True
        if item["state"] == "RECONCILIATION_REQUIRED" or (
            item["state"] == "COMMITTING"
            and item["providerInvocationStarted"]
        ):
            next_action = "READ_ONLY_RECONCILE_ONLY"
            replay_authorized = False
        if item["state"] in {"COMMITTED", "ABORTED"}:
            replay_authorized = False
        exact_blocker = None
        if item["blockers"]:
            exact_blocker = _clone(item["blockers"][0])
        elif platform in state.get("validationBlocks", {}):
            exact_blocker = {
                "code": "PLATFORM_VALIDATION_REJECTED",
                **_clone(state["validationBlocks"][platform]),
            }
        per_platform[platform] = {
            **_clone(item),
            "exactBlocker": exact_blocker,
            "nextSafeAction": next_action,
            "replayAuthorized": replay_authorized,
        }

    committed = [
        platform
        for platform in REQUIRED_PLATFORMS
        if per_platform[platform]["state"] == "COMMITTED"
    ]
    value = {
        "contractVersion": STATUS_VERSION,
        "sagaId": state["sagaId"],
        "state": state["sagaState"],
        "parentQaStatus": state["parentQaStatus"],
        "parentR33Authority": _clone(state["parentR33Authority"]),
        "releaseWindow": _clone(state["releaseWindow"]),
        "releasePolicy": _clone(state["releasePolicy"]),
        "winnerSha256": state["winner"]["sha256"],
        "winnerSize": state["winner"]["size"],
        "globalSuccess": state["globalSuccess"],
        "committedPlatforms": committed,
        "perPlatform": per_platform,
        "blockers": _clone(state["blockers"]),
        "compensations": _clone(state.get("compensations", {})),
        "realProviderEffects": 0,
        "providerNetworkEffects": 0,
        "livePublish": False,
        "credentialsStored": False,
        "sagaLedgerDigest": saga.digest,
    }
    value["statusDigest"] = _sha(value)
    return value


class DuplicateConfirmedAfterDispatch(r33.FakeProviderHarness):
    """Fake timeout-after-dispatch whose read-only lookup proves duplicate."""

    def __init__(self) -> None:
        super().__init__("timeout_after_dispatch")

    def lookup(self, state: Mapping[str, Any]) -> dict[str, Any]:
        self.lookup_calls += 1
        existing = self.effects.get(state["idempotencyKey"])
        if existing is None:
            return {
                "outcome": "unknown",
                "authoritative": False,
                "reason": "fake_effect_missing",
            }
        duplicate = _clone(existing)
        duplicate["outcome"] = "duplicate_confirmed"
        duplicate["proofDigest"] = r33._provider_proof(
            platform=state["target"]["platform"],
            transaction_id=state["transactionId"],
            request_digest=state["requestDigest"],
            operation_id=duplicate["externalOperationId"],
            post_id=duplicate["externalPostId"],
            outcome="duplicate_confirmed",
        )
        return duplicate


def readiness() -> dict[str, Any]:
    validate_parent_r33_authority(PARENT_R33_AUTHORITY)
    value = {
        "reportVersion": READINESS_VERSION,
        "state": "SOURCE_READY_PENDING_R34_QA",
        "SOURCE_READY": True,
        "PARENT_R33_ACCEPTED": True,
        "R34_INDEPENDENTLY_ACCEPTED": False,
        "parentQa": {
            "requiredGate": "QA-R3",
            "status": "ACCEPTED",
            "disposition": "PUBLISH_TRANSACTION_SOURCE_READY",
            "acceptanceEvidence": _clone(QA_R3_ACCEPTANCE),
        },
        "selfQa": {
            "requiredGate": "independent R34 QA",
            "status": "PENDING",
            "accepted": False,
            "liveReady": False,
        },
        "parentR33Authority": _clone(PARENT_R33_AUTHORITY),
        "r32Authority": _clone(r33.CREATOR_R32_AUTHORITY),
        "sagaContract": CONTRACT_VERSION,
        "defaultReleasePolicy": {
            "mode": "all_required",
            "requiredPlatforms": list(REQUIRED_PLATFORMS),
            "minimumCommittedPlatforms": 3,
        },
        "safety": {
            "fakeProviderOnly": True,
            "providerNetworkEffects": 0,
            "realProviderEffects": 0,
            "livePublish": False,
            "credentialsStored": False,
            "blindRetryAfterUnknown": False,
            "committedPostLocalRollbackClaimed": False,
            "providerDeleteContractInScope": False,
            "mergePerformed": False,
        },
        "blockers": [
            {
                "code": "WAITING_R34_INDEPENDENT_QA",
                "detail": "R33 parent is QA-R3 accepted; R34 itself is not independently accepted",
            }
        ],
    }
    value["reportDigest"] = _sha(value)
    return value


def _fixture_configs(
    handoff: Mapping[str, Any],
    *,
    caption_suffix: str = "",
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for platform in REQUIRED_PLATFORMS:
        target = r33._target(platform)
        values[platform] = {
            "providerAdapter": target["provider_adapter"],
            "accountRef": target["account_ref"],
            "destination": target["destination"],
            "credentialRef": target["credential_ref"],
            "authorizationRef": target["authorization_ref"],
            "configurationRef": target["configuration_ref"],
            "configRevision": 7,
            "caption": f"R34 deterministic {platform}{caption_suffix}",
            "title": f"R34 title {platform}",
            "thumbnailSha256": "e" * 64,
            "mediaMetadata": r33._fixture_media(handoff, platform),
        }
    return values


def _fixture_kwargs() -> dict[str, Any]:
    upstream, handoff = r33._fixture_upstream()
    return {
        "upstream_state": upstream,
        "handoff": handoff,
        "upstream_outcome": "winner",
        "platform_configs": _fixture_configs(handoff),
        "release_window": {
            "start": "2026-10-05T12:00:00Z",
            "deadline": "2026-10-05T13:00:00Z",
            "revision": 4,
        },
    }


def _prepare_all(saga: SagaLedger) -> None:
    for platform in REQUIRED_PLATFORMS:
        validate_platform(saga, platform)
        mark_platform_commit_eligible(saga, platform)


def run_chaos_rehearsal(work_dir: str | os.PathLike[str]) -> dict[str, Any]:
    root = Path(work_dir)
    root.mkdir(parents=True, exist_ok=True)

    main = prepare_saga(root / "partial-saga", **_fixture_kwargs())
    before_window = saga_status(main, at_time="2026-10-05T11:59:59Z")
    try:
        commit_platform(
            main,
            "instagram_reels",
            r33.FakeProviderHarness("clean_success"),
            at_time="2026-10-05T11:59:59Z",
        )
    except SagaScheduleError:
        crash_before_window_blocked = True
    else:
        crash_before_window_blocked = False

    _prepare_all(main)
    main = SagaLedger(root / "partial-saga")
    ig = r33.FakeProviderHarness("clean_success")
    commit_platform(
        main,
        "instagram_reels",
        ig,
        at_time="2026-10-05T12:10:00Z",
    )
    after_ig = saga_status(main, at_time="2026-10-05T12:10:01Z")

    main = SagaLedger(root / "partial-saga")
    tt = DuplicateConfirmedAfterDispatch()
    commit_platform(
        main,
        "tiktok",
        tt,
        at_time="2026-10-05T12:11:00Z",
    )
    unknown = saga_status(main, at_time="2026-10-05T12:11:01Z")
    calls_before_blind_retry = tt.commit_calls
    try:
        commit_platform(
            main,
            "tiktok",
            tt,
            at_time="2026-10-05T12:11:02Z",
        )
    except r33.ReconciliationRequired:
        blind_retry_blocked = True
    else:
        blind_retry_blocked = False
    if tt.commit_calls != calls_before_blind_retry:
        raise AssertionError("unknown TikTok outcome triggered provider replay")

    main = SagaLedger(root / "partial-saga")
    reconcile_platform(main, "tiktok", tt)
    after_duplicate_confirmed = saga_status(
        main,
        at_time="2026-10-05T12:12:00Z",
    )

    main = SagaLedger(root / "partial-saga")
    yt = r33.FakeProviderHarness("clean_success")
    commit_platform(
        main,
        "youtube_shorts",
        yt,
        at_time="2026-10-05T12:13:00Z",
    )
    final = saga_status(main, at_time="2026-10-05T12:13:01Z")

    unavailable = prepare_saga(
        root / "lookup-unavailable-saga",
        **_fixture_kwargs(),
    )
    _prepare_all(unavailable)
    unknown_provider = r33.FakeProviderHarness("unknown_no_lookup")
    commit_platform(
        unavailable,
        "tiktok",
        unknown_provider,
        at_time="2026-10-05T12:20:00Z",
    )
    unknown_calls = unknown_provider.commit_calls
    reconcile_platform(unavailable, "tiktok", unknown_provider)
    unavailable_status = saga_status(
        unavailable,
        at_time="2026-10-05T12:20:01Z",
    )
    try:
        commit_platform(
            unavailable,
            "tiktok",
            unknown_provider,
            at_time="2026-10-05T12:20:02Z",
        )
    except r33.ReconciliationRequired:
        unavailable_blind_retry_blocked = True
    else:
        unavailable_blind_retry_blocked = False
    if unknown_provider.commit_calls != unknown_calls:
        raise AssertionError("lookup-unavailable child was blindly replayed")

    rejected = prepare_saga(
        root / "validation-reject-saga",
        **_fixture_kwargs(),
    )
    validate_platform(rejected, "instagram_reels")
    mark_platform_commit_eligible(rejected, "instagram_reels")
    validate_platform(rejected, "tiktok")
    mark_platform_commit_eligible(rejected, "tiktok")
    reject_platform_validation(
        rejected,
        "youtube_shorts",
        reason_code="fixture_provider_account_not_ready",
    )
    rejected_status = saga_status(
        rejected,
        at_time="2026-10-05T12:30:00Z",
    )

    compensation = record_compensation_metadata(
        main,
        "instagram_reels",
        reason="campaign locally withdrawn after external commit",
    )
    compensation_status = saga_status(
        main,
        at_time="2026-10-05T12:31:00Z",
    )
    if main.child("instagram_reels").state["state"] != "COMMITTED":
        raise AssertionError("compensation metadata rewrote external commit")

    report = {
        "reportVersion": REHEARSAL_VERSION,
        "state": "SOURCE_READY_PENDING_R34_QA",
        "parentR33Authority": _clone(PARENT_R33_AUTHORITY),
        "parentQaAccepted": True,
        "crashBeforeWindowBlocked": crash_before_window_blocked,
        "beforeWindow": before_window,
        "afterInstagramCommit": after_ig,
        "partialUnknown": unknown,
        "blindRetryBlocked": blind_retry_blocked,
        "tiktokCommitCallsBeforeBlindRetry": calls_before_blind_retry,
        "afterTikTokDuplicateConfirmed": after_duplicate_confirmed,
        "allCommitted": final,
        "lookupUnavailable": unavailable_status,
        "lookupUnavailableBlindRetryBlocked": unavailable_blind_retry_blocked,
        "validationRejected": rejected_status,
        "compensationMetadata": compensation["compensations"]["instagram_reels"],
        "compensationStatus": compensation_status,
        "fakeProviderEffects": {
            "instagram": ig.effect_count,
            "tiktok": tt.effect_count,
            "youtube": yt.effect_count,
            "lookupUnavailableTikTok": unknown_provider.effect_count,
        },
        "realProviderEffects": 0,
        "providerNetworkEffects": 0,
        "livePublish": False,
        "credentialsStored": False,
    }
    report["reportDigest"] = _sha(report)
    (root / "chaos-rehearsal.r34.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    evidence = {
        "contractVersion": EVIDENCE_VERSION,
        "parentR33Authority": _clone(PARENT_R33_AUTHORITY),
        "parentQaAccepted": True,
        "rehearsalDigest": report["reportDigest"],
        "mainSaga": {
            "sagaId": final["sagaId"],
            "state": final["state"],
            "statusDigest": final["statusDigest"],
            "ledgerDigest": final["sagaLedgerDigest"],
            "platforms": {
                platform: {
                    "state": final["perPlatform"][platform]["state"],
                    "transactionId": final["perPlatform"][platform]["transactionId"],
                    "idempotencyKey": final["perPlatform"][platform]["idempotencyKey"],
                    "requestDigest": final["perPlatform"][platform]["requestDigest"],
                    "ledgerDigest": final["perPlatform"][platform]["ledgerDigest"],
                }
                for platform in REQUIRED_PLATFORMS
            },
        },
        "partialCommitObserved": (
            after_ig["state"] == "PARTIALLY_COMMITTED"
            and after_ig["committedPlatforms"] == ["instagram_reels"]
        ),
        "unknownOutcomeObserved": unknown["state"] == "RECONCILIATION_REQUIRED",
        "tiktokDuplicateConfirmed": (
            after_duplicate_confirmed["perPlatform"]["tiktok"]["state"] == "COMMITTED"
        ),
        "outcomeLookupUnavailableRemainsBlocked": (
            unavailable_status["perPlatform"]["tiktok"]["state"]
            == "RECONCILIATION_REQUIRED"
        ),
        "validationRejectTerminalBlocked": (
            rejected_status["state"] == "TERMINAL_BLOCKED"
        ),
        "unknownOutcomeBlindRetryForbidden": (
            blind_retry_blocked and unavailable_blind_retry_blocked
        ),
        "compensationNeverRewritesCommittedPost": (
            compensation_status["perPlatform"]["instagram_reels"]["state"]
            == "COMMITTED"
            and compensation_status["compensations"]["instagram_reels"][
                "externalPostStillCommitted"
            ]
            is True
        ),
        "realProviderEffects": 0,
        "providerNetworkEffects": 0,
        "livePublish": False,
    }
    evidence["evidenceDigest"] = _sha(evidence)
    (root / "evidence-manifest.r34.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="creator-multiplatform-publish-r34")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("readiness")
    p.add_argument("--out")
    p = sub.add_parser("status")
    p.add_argument("--saga-dir", required=True)
    p.add_argument("--at-time")
    p.add_argument("--out")
    p = sub.add_parser("chaos-rehearsal")
    p.add_argument("--out", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "readiness":
        value = readiness()
    elif args.command == "status":
        value = saga_status(
            SagaLedger(args.saga_dir),
            at_time=args.at_time,
        )
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
