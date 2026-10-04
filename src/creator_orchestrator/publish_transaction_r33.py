from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import autonomous_reels as reels
from . import autonomous_tournament_r32 as r32

CONTRACT_VERSION = "creator.publish_transaction.r33.v1"
LEDGER_VERSION = "creator.publish_transaction_ledger.r33.v1"
STATUS_VERSION = "creator.publish_transaction_status.r33.v1"
BATCH_VERSION = "creator.publish_batch_status.r33.v1"
READINESS_VERSION = "creator.publish_transaction.r33.readiness.v1"
REHEARSAL_VERSION = "creator.publish_transaction_rehearsal.r33.v1"
EVIDENCE_VERSION = "creator.publish_transaction_evidence.r33.v1"

CREATOR_R32_AUTHORITY = {
    "repository": "foto6/video1",
    "producerSha": "f0dc1d27da6452f1de32cd887651805b47a1735d",
    "ciRunId": 37199512624,
    "artifactId": 11302367811,
    "artifactName": "creator-r32-autonomous-tournament-f0dc1d27da6452f1de32cd887651805b47a1735d",
    "artifactDigest": "sha256:6803db334974b8dbea1c30c107ec5af00fe2cb892ed67e68540c2b2d74b18599",
    "contract": "creator.autonomous_tournament.r32.v1",
    "blobs": {
        "runtime": "6d35bb30d0834908ed6043c89ba7d9980da388e4",
        "schema": "d6a593b8d9351de81213b179ae7d3d8e51497bbe",
        "manifest": "3304a4cdc8b2130ed98075e5a9653f4c25e178aa",
        "authorityProfiles": "89674be575ad87d44da46ec3c64a976df71201b3",
        "publishHandoffSchema": "bf0cbd4073e275ef3b00dc05c23b48463779ea90",
        "publishHandoffManifest": "2f1c9c4a93e5a508501e4c44d8f3a64c8e3cf2e4",
        "publishHandoffRuntime": "e18a06dc482f2a23b43b689c935209cd1415f08e",
    },
}

STATES = {
    "PREPARED",
    "VALIDATED",
    "COMMIT_ELIGIBLE",
    "COMMITTING",
    "RECONCILIATION_REQUIRED",
    "COMMITTED",
    "ABORTED",
}

PLATFORM_METADATA = {
    "instagram_reels": {
        "adapter": "InstagramReelsProvider",
        "provider": "instagram_graph",
        "media": {
            "contentType": "video/mp4",
            "aspectRatio": "9:16",
            "durationSeconds": {"minimum": 15.0, "maximum": 60.0},
            "maxBytes": 1024 * 1024 * 1024,
            "fps": {"minimum": 23.0, "maximum": 60.0},
            "maxWidth": 1920,
            "videoCodecs": ["h264", "hevc", "h265"],
            "audioCodecs": [None, "aac"],
            "requiresPublicHttpsUrl": True,
        },
        "destinationRule": "profile:<accountRef>",
        "phases": [
            "create_or_upload_session",
            "provider_processing",
            "publish_commit",
            "terminal_receipt",
        ],
        "readOnlyRecovery": True,
    },
    "tiktok": {
        "adapter": "TikTokDirectPostProvider",
        "provider": "tiktok_content_posting",
        "media": {
            "contentType": "video/mp4",
            "aspectRatio": "9:16",
            "durationSeconds": {"minimum": 15.0, "maximum": 60.0},
            "maxBytes": 4 * 1024 * 1024 * 1024,
            "fps": {"minimum": 23.0, "maximum": 60.0},
            "minDimension": 360,
            "maxDimension": 4096,
            "videoCodecs": ["h264", "hevc", "h265"],
            "requiresPublicHttpsUrl": True,
        },
        "destinationRule": "privacy:<provider-supported-level>",
        "phases": [
            "create_or_upload_session",
            "provider_processing",
            "terminal_receipt",
        ],
        "readOnlyRecovery": True,
    },
    "youtube_shorts": {
        "adapter": "YouTubeShortsProvider",
        "provider": "youtube_data_api",
        "media": {
            "contentType": "video/mp4",
            "aspectRatio": "9:16",
            "durationSeconds": {"minimum": 15.0, "maximum": 60.0},
            "maxBytes": 256 * 1024 * 1024 * 1024,
            "videoCodecs": ["h264", "hevc", "h265"],
            "requiresPublicHttpsUrl": False,
        },
        "destinationRule": "privacy:public|private|unlisted",
        "phases": [
            "create_or_upload_session",
            "provider_processing",
            "terminal_receipt",
        ],
        "readOnlyRecovery": True,
    },
}

SECRET_FIELD_FRAGMENTS = (
    "access_token",
    "refresh_token",
    "password",
    "authorization_header",
    "cookie",
    "client_secret",
    "api_key",
    "bearer",
)


class PublishTransactionError(ValueError):
    pass


class AuthorityDrift(PublishTransactionError):
    pass


class UpstreamIneligible(PublishTransactionError):
    pass


class ValidationFailed(PublishTransactionError):
    pass


class ReplayConflict(PublishTransactionError):
    pass


class InvalidTransition(PublishTransactionError):
    pass


class ReconciliationRequired(PublishTransactionError):
    pass


class LivePublishForbidden(PublishTransactionError):
    pass


class OutcomeProofError(PublishTransactionError):
    pass


class ProviderTimeoutBeforeDispatch(RuntimeError):
    pass


class ProviderTimeoutAfterDispatch(RuntimeError):
    pass


def _clone(value: Any) -> Any:
    return json.loads(reels.canonical_json(value))


def _sha(value: Any) -> str:
    return reels.sha256_json(value)


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hex(value: Any, size: int, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != size
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise PublishTransactionError(f"{field} must be lowercase {size}-hex")
    return value


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublishTransactionError(f"{field} must be non-empty")
    return value


def _positive(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PublishTransactionError(f"{field} must be positive integer")
    return value


def _scan_no_secrets(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lower = str(key).lower()
            if any(fragment in lower for fragment in SECRET_FIELD_FRAGMENTS):
                raise PublishTransactionError(f"secret-bearing field forbidden: {path}.{key}")
            _scan_no_secrets(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_no_secrets(item, f"{path}[{index}]")


def validate_r32_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    if value != CREATOR_R32_AUTHORITY:
        raise AuthorityDrift("Creator R32 authority drift")
    return _clone(value)


def _validate_r32_handoff(
    upstream_state: Mapping[str, Any],
    handoff: Mapping[str, Any],
    *,
    upstream_outcome: str,
) -> dict[str, Any]:
    if upstream_outcome != "winner":
        raise UpstreamIneligible(f"{upstream_outcome} is not publishable")
    if upstream_state.get("state") != "PUBLISH_HANDOFF_READY":
        raise UpstreamIneligible("R32 state is not PUBLISH_HANDOFF_READY")
    if upstream_state.get("reconciliationRequired") is not False:
        raise UpstreamIneligible("R32 has unresolved reconciliation")
    review_round = upstream_state.get("reviewRound")
    if isinstance(review_round, bool) or not isinstance(review_round, int) or not 0 <= review_round <= 2:
        raise UpstreamIneligible("R32 review round invalid")
    if handoff.get("contractVersion") != "creator.editor_publish_handoff.v1":
        raise UpstreamIneligible("winner handoff contract mismatch")
    required = {
        "contractVersion",
        "handoffClass",
        "sessionId",
        "tournamentId",
        "winnerCandidateId",
        "finalArtifact",
        "sourceSha256",
        "consensusDigest",
        "livePublish",
        "providerMutation",
        "humanGroundTruth",
        "handoffDigest",
    }
    if set(handoff) != required:
        raise UpstreamIneligible("winner handoff fields mismatch")
    if handoff["sessionId"] != upstream_state.get("sessionId"):
        raise UpstreamIneligible("winner session lineage mismatch")
    if handoff["tournamentId"] != upstream_state.get("tournamentId"):
        raise UpstreamIneligible("winner tournament lineage mismatch")
    if handoff["winnerCandidateId"] != upstream_state.get("selectedCandidateId"):
        raise UpstreamIneligible("winner candidate lineage mismatch")
    if handoff["sourceSha256"] != upstream_state.get("source", {}).get("sha256"):
        raise UpstreamIneligible("winner source lineage mismatch")
    if handoff["consensusDigest"] != upstream_state.get("consensusDigest"):
        raise UpstreamIneligible("winner consensus lineage mismatch")
    final = handoff["finalArtifact"]
    if not isinstance(final, Mapping) or set(final) != {"fileName", "sha256", "size"}:
        raise UpstreamIneligible("winner final artifact fields mismatch")
    if final["fileName"] != "final.mp4":
        raise UpstreamIneligible("winner final artifact must be final.mp4")
    _hex(final["sha256"], 64, "winner.finalArtifact.sha256")
    _positive(final["size"], "winner.finalArtifact.size")
    if handoff["livePublish"] is not False or handoff["providerMutation"] is not False:
        raise UpstreamIneligible("R32 handoff unexpectedly claims provider mutation")
    if handoff["humanGroundTruth"] is not False:
        raise UpstreamIneligible("R32 handoff human-ground-truth boundary drift")
    material = copy.deepcopy(handoff)
    digest = material["handoffDigest"]
    material["handoffDigest"] = ""
    if _sha(material) != digest:
        raise UpstreamIneligible("winner handoff digest mismatch")
    return _clone(handoff)


def _validate_provider_target(target: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "platform",
        "providerAdapter",
        "accountRef",
        "destination",
        "credentialRef",
        "authorizationRef",
        "configurationRef",
    }
    if not isinstance(target, Mapping) or set(target) != required:
        raise ValidationFailed("provider target fields mismatch")
    _scan_no_secrets(target, "target")
    platform = target["platform"]
    if platform not in PLATFORM_METADATA:
        raise ValidationFailed("unsupported platform")
    metadata = PLATFORM_METADATA[platform]
    if target["providerAdapter"] != metadata["adapter"]:
        raise ValidationFailed("provider adapter identity mismatch")
    for key in ("accountRef", "destination", "credentialRef", "authorizationRef", "configurationRef"):
        _nonempty(target[key], f"target.{key}")
    if platform == "instagram_reels":
        if target["destination"] != "profile:" + target["accountRef"]:
            raise ValidationFailed("Instagram destination/account mismatch")
    elif platform == "tiktok":
        if not target["destination"].startswith("privacy:") or len(target["destination"]) <= len("privacy:"):
            raise ValidationFailed("TikTok destination must be privacy:<level>")
    elif target["destination"] not in {"privacy:public", "privacy:private", "privacy:unlisted"}:
        raise ValidationFailed("YouTube destination invalid")
    return _clone(target)


def _validate_media_metadata(media: Mapping[str, Any], final_artifact: Mapping[str, Any], platform: str) -> dict[str, Any]:
    required = {
        "sha256",
        "sizeBytes",
        "contentType",
        "aspectRatio",
        "durationSeconds",
        "width",
        "height",
        "fps",
        "videoCodec",
        "audioCodec",
        "publicHttpsUrlAvailable",
    }
    if not isinstance(media, Mapping) or set(media) != required:
        raise ValidationFailed("media metadata fields mismatch")
    if media["sha256"] != final_artifact["sha256"]:
        raise ValidationFailed("media SHA does not match final winner")
    if media["sizeBytes"] != final_artifact["size"]:
        raise ValidationFailed("media size does not match final winner")
    constraints = PLATFORM_METADATA[platform]["media"]
    if media["contentType"] != constraints["contentType"]:
        raise ValidationFailed("media content type unsupported")
    if media["aspectRatio"] != constraints["aspectRatio"]:
        raise ValidationFailed("media aspect ratio unsupported")
    duration = media["durationSeconds"]
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise ValidationFailed("media duration invalid")
    if not constraints["durationSeconds"]["minimum"] <= float(duration) <= constraints["durationSeconds"]["maximum"]:
        raise ValidationFailed("media duration outside Creator provider profile")
    if media["sizeBytes"] > constraints["maxBytes"]:
        raise ValidationFailed("media exceeds provider size bound")
    if media["videoCodec"] not in constraints["videoCodecs"]:
        raise ValidationFailed("video codec unsupported")
    if media["width"] * 16 != media["height"] * 9:
        raise ValidationFailed("probed dimensions are not exact 9:16")
    if "fps" in constraints:
        if not constraints["fps"]["minimum"] <= float(media["fps"]) <= constraints["fps"]["maximum"]:
            raise ValidationFailed("frame rate outside provider bound")
    if "maxWidth" in constraints and media["width"] > constraints["maxWidth"]:
        raise ValidationFailed("media width exceeds provider bound")
    if "minDimension" in constraints:
        if min(media["width"], media["height"]) < constraints["minDimension"]:
            raise ValidationFailed("media dimension below provider bound")
        if max(media["width"], media["height"]) > constraints["maxDimension"]:
            raise ValidationFailed("media dimension above provider bound")
    if "audioCodecs" in constraints and media["audioCodec"] not in constraints["audioCodecs"]:
        raise ValidationFailed("audio codec unsupported")
    if constraints["requiresPublicHttpsUrl"] and media["publicHttpsUrlAvailable"] is not True:
        raise ValidationFailed("provider requires public HTTPS media URL")
    return _clone(media)


def build_prepare_spec(
    *,
    upstream_state: Mapping[str, Any],
    handoff: Mapping[str, Any],
    upstream_outcome: str,
    platform: str,
    provider_adapter: str,
    account_ref: str,
    destination: str,
    credential_ref: str,
    authorization_ref: str,
    configuration_ref: str,
    media_metadata: Mapping[str, Any],
    caption: str,
    title: str,
    thumbnail_sha256: str | None,
    publish_policy: Mapping[str, Any],
    planned_publish_at: str | None = None,
    revision: int = 0,
    parent_transaction_id: str | None = None,
    r32_authority: Mapping[str, Any] = CREATOR_R32_AUTHORITY,
    explicit_idempotency_key: str | None = None,
) -> dict[str, Any]:
    validate_r32_authority(r32_authority)
    handoff = _validate_r32_handoff(
        upstream_state,
        handoff,
        upstream_outcome=upstream_outcome,
    )
    target = _validate_provider_target(
        {
            "platform": platform,
            "providerAdapter": provider_adapter,
            "accountRef": account_ref,
            "destination": destination,
            "credentialRef": credential_ref,
            "authorizationRef": authorization_ref,
            "configurationRef": configuration_ref,
        }
    )
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise PublishTransactionError("revision must be nonnegative integer")
    _scan_no_secrets(publish_policy, "publishPolicy")
    if not isinstance(publish_policy, Mapping) or not publish_policy:
        raise ValidationFailed("publish policy must be non-empty object")
    media = _validate_media_metadata(media_metadata, handoff["finalArtifact"], platform)
    if not isinstance(caption, str) or not isinstance(title, str):
        raise PublishTransactionError("caption/title must be strings")
    if thumbnail_sha256 is not None:
        _hex(thumbnail_sha256, 64, "thumbnail_sha256")
    content_hashes = {
        "captionSha256": _sha_text(caption),
        "titleSha256": _sha_text(title),
        "thumbnailSha256": thumbnail_sha256,
    }
    lineage = {
        "sourceSha256": handoff["sourceSha256"],
        "sessionId": handoff["sessionId"],
        "tournamentId": handoff["tournamentId"],
        "reviewRound": upstream_state["reviewRound"],
        "winnerCandidateId": handoff["winnerCandidateId"],
        "consensusDigest": handoff["consensusDigest"],
        "publishHandoffDigest": handoff["handoffDigest"],
    }
    schedule = {
        "plannedPublishAt": planned_publish_at,
        "scheduleDigest": _sha({"plannedPublishAt": planned_publish_at, "revision": revision}),
    }
    provider_metadata = _clone(PLATFORM_METADATA[platform])
    policy_hash = _sha(publish_policy)
    identity_material = {
        "contractVersion": CONTRACT_VERSION,
        "revision": revision,
        "parentTransactionId": parent_transaction_id,
        "winner": _clone(handoff["finalArtifact"]),
        "lineage": lineage,
        "r32Authority": _clone(r32_authority),
        "target": target,
        "contentHashes": content_hashes,
        "publishPolicyHash": policy_hash,
        "schedule": schedule,
        "providerMetadataDigest": _sha(provider_metadata),
    }
    transaction_id = "r33tx:" + _sha(identity_material)
    idempotency_key = (
        explicit_idempotency_key
        if explicit_idempotency_key is not None
        else "r33idem:" + _sha({"transactionId": transaction_id, "platform": platform})
    )
    _nonempty(idempotency_key, "idempotencyKey")
    dry_run_request = {
        "contractVersion": "creator.publish_transaction_dry_run_request.r33.v1",
        "transactionId": transaction_id,
        "idempotencyKey": idempotency_key,
        "platform": platform,
        "providerAdapter": provider_adapter,
        "accountRef": account_ref,
        "destination": destination,
        "winnerSha256": handoff["finalArtifact"]["sha256"],
        "winnerSize": handoff["finalArtifact"]["size"],
        "captionSha256": content_hashes["captionSha256"],
        "titleSha256": content_hashes["titleSha256"],
        "thumbnailSha256": thumbnail_sha256,
        "publishPolicyHash": policy_hash,
        "plannedPublishAt": planned_publish_at,
        "credentialRef": credential_ref,
        "authorizationRef": authorization_ref,
        "configurationRef": configuration_ref,
        "networkEnabled": False,
    }
    request_digest = _sha(dry_run_request)
    return {
        "contractVersion": CONTRACT_VERSION,
        "transactionId": transaction_id,
        "idempotencyKey": idempotency_key,
        "revision": revision,
        "parentTransactionId": parent_transaction_id,
        "state": "PREPARED",
        "r32Authority": _clone(r32_authority),
        "winner": _clone(handoff["finalArtifact"]),
        "lineage": lineage,
        "target": target,
        "contentHashes": content_hashes,
        "mediaMetadata": media,
        "publishPolicyHash": policy_hash,
        "schedule": schedule,
        "providerMetadata": provider_metadata,
        "providerMetadataDigest": _sha(provider_metadata),
        "dryRunRequest": dry_run_request,
        "requestDigest": request_digest,
        "validationDigest": None,
        "commit": {
            "attemptNumber": 0,
            "attemptId": None,
            "invocationStarted": False,
            "externalOperationId": None,
            "externalPostId": None,
            "outcomeProofDigest": None,
            "providerOutcome": None,
        },
        "blockers": [],
        "liveSideEffectPermitted": False,
        "networkPermitted": False,
    }


class TransactionLedger:
    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        prepared_spec: Mapping[str, Any] | None = None,
    ) -> None:
        self.path = Path(path)
        self.events: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        self.state: dict[str, Any] = {}
        if self.path.exists():
            self._load()
            if prepared_spec is not None:
                self.assert_prepared_identity(prepared_spec)
            return
        if prepared_spec is None:
            raise PublishTransactionError("new transaction ledger requires prepared_spec")
        if prepared_spec.get("state") != "PREPARED":
            raise PublishTransactionError("prepared_spec state must be PREPARED")
        self._append(
            event_key="prepare",
            event_type="TRANSACTION_PREPARED",
            operation_id="r33prepare:" + _sha(
                {
                    "transactionId": prepared_spec["transactionId"],
                    "requestDigest": prepared_spec["requestDigest"],
                }
            ),
            request=prepared_spec["dryRunRequest"],
            new_state=prepared_spec,
            input_artifacts={
                "winnerSha256": prepared_spec["winner"]["sha256"],
                "winnerSize": prepared_spec["winner"]["size"],
                "sourceSha256": prepared_spec["lineage"]["sourceSha256"],
                "publishHandoffDigest": prepared_spec["lineage"]["publishHandoffDigest"],
                "r32ArtifactDigest": prepared_spec["r32Authority"]["artifactDigest"],
            },
            output_artifacts={
                "transactionId": prepared_spec["transactionId"],
                "requestDigest": prepared_spec["requestDigest"],
            },
            timestamp_metadata="2026-10-04T00:00:00Z",
            previous_state={},
        )

    def _load(self) -> None:
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReplayConflict(f"invalid transaction ledger JSON line {line_number}") from exc
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
            if set(event) != required or event["ledgerVersion"] != LEDGER_VERSION:
                raise ReplayConflict("transaction ledger event shape/version mismatch")
            if event["sequence"] != len(self.events) + 1:
                raise ReplayConflict("transaction ledger sequence mismatch")
            if event["eventKey"] in self.by_key:
                raise ReplayConflict("duplicate transaction ledger event key")
            if event["previousStateDigest"] != _sha(self.state):
                raise ReplayConflict("transaction ledger previous-state chain mismatch")
            if event["newStateDigest"] != _sha(event["newState"]):
                raise ReplayConflict("transaction ledger new-state digest mismatch")
            identity = {k: v for k, v in event.items() if k not in {"timestampMetadata", "eventDigest"}}
            if event["eventDigest"] != _sha(identity):
                raise ReplayConflict("transaction ledger event digest mismatch")
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
            "previousStateDigest": _sha(old),
            "newStateDigest": _sha(new_state),
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

    def assert_prepared_identity(self, spec: Mapping[str, Any]) -> None:
        if spec.get("idempotencyKey") != self.state.get("idempotencyKey"):
            raise ReplayConflict("idempotency key changed")
        if spec.get("transactionId") != self.state.get("transactionId"):
            raise ReplayConflict("transaction identity changed under same ledger")
        if spec.get("requestDigest") != self.state.get("requestDigest"):
            raise ReplayConflict("same transaction key changed request bytes")
        for key in ("winner", "lineage", "target", "contentHashes", "publishPolicyHash", "schedule"):
            if spec.get(key) != self.state.get(key):
                raise ReplayConflict(f"prepared immutable field changed: {key}")

    @property
    def digest(self) -> str:
        return _sha(self.events)


def prepare_transaction(
    path: str | os.PathLike[str],
    **kwargs: Any,
) -> TransactionLedger:
    spec = build_prepare_spec(**kwargs)
    return TransactionLedger(path, prepared_spec=spec)


def validate_prepared(ledger: TransactionLedger) -> dict[str, Any]:
    state = ledger.state
    if state["state"] == "VALIDATED":
        return _clone(state)
    if state["state"] != "PREPARED":
        raise InvalidTransition(f"validation forbidden from {state['state']}")
    validate_r32_authority(state["r32Authority"])
    _validate_provider_target(state["target"])
    _validate_media_metadata(state["mediaMetadata"], state["winner"], state["target"]["platform"])
    _scan_no_secrets(state, "transaction")
    if state["dryRunRequest"]["networkEnabled"] is not False:
        raise ValidationFailed("R33 dry-run request cannot enable network")
    validation = {
        "winnerBinding": True,
        "r32AuthorityBinding": True,
        "providerTargetPresent": True,
        "credentialReferencePresent": bool(state["target"]["credentialRef"]),
        "authorizationReferencePresent": bool(state["target"]["authorizationRef"]),
        "configurationReferencePresent": bool(state["target"]["configurationRef"]),
        "mediaConstraintsPass": True,
        "requestDigest": state["requestDigest"],
        "providerMetadataDigest": state["providerMetadataDigest"],
    }
    new = _clone(state)
    new["state"] = "VALIDATED"
    new["validationDigest"] = _sha(validation)
    new["blockers"] = []
    ledger._append(
        event_key="validate",
        event_type="TRANSACTION_VALIDATED",
        operation_id="r33validate:" + _sha({"transactionId": state["transactionId"], "validation": validation}),
        request=validation,
        new_state=new,
        input_artifacts={
            "requestDigest": state["requestDigest"],
            "winnerSha256": state["winner"]["sha256"],
            "r32ArtifactDigest": state["r32Authority"]["artifactDigest"],
        },
        output_artifacts={"validationDigest": new["validationDigest"]},
        timestamp_metadata="2026-10-04T00:00:01Z",
    )
    return _clone(new)


def mark_commit_eligible(ledger: TransactionLedger) -> dict[str, Any]:
    state = ledger.state
    if state["state"] == "COMMIT_ELIGIBLE":
        return _clone(state)
    if state["state"] != "VALIDATED":
        raise InvalidTransition(f"commit eligibility forbidden from {state['state']}")
    new = _clone(state)
    new["state"] = "COMMIT_ELIGIBLE"
    new["blockers"] = []
    ledger._append(
        event_key="commit-eligible",
        event_type="COMMIT_ELIGIBLE",
        operation_id="r33eligible:" + _sha({"transactionId": state["transactionId"], "validationDigest": state["validationDigest"]}),
        request={"validationDigest": state["validationDigest"], "requestDigest": state["requestDigest"]},
        new_state=new,
        input_artifacts={"validationDigest": state["validationDigest"]},
        output_artifacts={"commitEligibilityDigest": _sha({"transactionId": state["transactionId"], "requestDigest": state["requestDigest"]})},
        timestamp_metadata="2026-10-04T00:00:02Z",
    )
    return _clone(new)


def abort_transaction(ledger: TransactionLedger, *, reason: str) -> dict[str, Any]:
    state = ledger.state
    if state["state"] == "ABORTED":
        return _clone(state)
    safe_absence = (
        state["state"] == "COMMIT_ELIGIBLE"
        and any(
            item.get("code") == "AUTHORITATIVE_PROVIDER_ABSENCE"
            for item in state.get("blockers", [])
            if isinstance(item, Mapping)
        )
    )
    if state["state"] not in {"PREPARED", "VALIDATED"} and not safe_absence:
        raise InvalidTransition(
            "abort allowed only before commit, or after authoritative provider absence"
        )
    _nonempty(reason, "abort reason")
    new = _clone(state)
    new["state"] = "ABORTED"
    new["blockers"] = [{"code": "ABORTED_BY_OPERATOR", "reasonDigest": _sha_text(reason)}]
    ledger._append(
        event_key="abort",
        event_type="TRANSACTION_ABORTED",
        operation_id="r33abort:" + _sha({"transactionId": state["transactionId"], "reasonDigest": _sha_text(reason)}),
        request={"reasonDigest": _sha_text(reason)},
        new_state=new,
        input_artifacts={"requestDigest": state["requestDigest"]},
        output_artifacts={},
        timestamp_metadata="2026-10-04T00:00:03Z",
    )
    return _clone(new)


def begin_commit(ledger: TransactionLedger) -> dict[str, Any]:
    state = ledger.state
    if state["state"] == "COMMITTING" and state["commit"]["invocationStarted"] is False:
        return _clone(state)
    if state["state"] != "COMMIT_ELIGIBLE":
        raise InvalidTransition(f"commit begin forbidden from {state['state']}")
    attempt_number = state["commit"]["attemptNumber"] + 1
    attempt_id = "r33attempt:" + _sha(
        {
            "transactionId": state["transactionId"],
            "idempotencyKey": state["idempotencyKey"],
            "requestDigest": state["requestDigest"],
            "attemptNumber": attempt_number,
        }
    )
    new = _clone(state)
    new["state"] = "COMMITTING"
    new["commit"]["attemptNumber"] = attempt_number
    new["commit"]["attemptId"] = attempt_id
    new["commit"]["invocationStarted"] = False
    new["blockers"] = []
    ledger._append(
        event_key=f"commit-begin:{attempt_number}",
        event_type="COMMITTING",
        operation_id=attempt_id,
        request={"requestDigest": state["requestDigest"], "idempotencyKey": state["idempotencyKey"]},
        new_state=new,
        input_artifacts={"winnerSha256": state["winner"]["sha256"], "requestDigest": state["requestDigest"]},
        output_artifacts={"attemptId": attempt_id},
        timestamp_metadata="2026-10-04T00:00:04Z",
    )
    return _clone(new)


def _provider_proof(
    *,
    platform: str,
    transaction_id: str,
    request_digest: str,
    operation_id: str,
    post_id: str,
    outcome: str,
) -> str:
    return _sha(
        {
            "platform": platform,
            "transactionId": transaction_id,
            "requestDigest": request_digest,
            "externalOperationId": operation_id,
            "externalPostId": post_id,
            "outcome": outcome,
        }
    )


class FakeProviderHarness:
    SCENARIOS = {
        "clean_success",
        "timeout_before_dispatch",
        "timeout_after_dispatch",
        "duplicate_confirmed",
        "unknown_no_lookup",
    }

    is_fake = True

    def __init__(self, scenario: str) -> None:
        if scenario not in self.SCENARIOS:
            raise ValueError("unsupported fake provider scenario")
        self.scenario = scenario
        self.effects: dict[str, dict[str, Any]] = {}
        self.commit_calls = 0
        self.effect_count = 0
        self.lookup_calls = 0

    def _outcome(self, state: Mapping[str, Any], *, outcome: str = "committed") -> dict[str, Any]:
        operation_id = "fakeop:" + _sha({"transactionId": state["transactionId"], "scenario": self.scenario})[:32]
        post_id = "fakepost:" + _sha({"idempotencyKey": state["idempotencyKey"], "platform": state["target"]["platform"]})[:32]
        value = {
            "outcome": outcome,
            "authoritative": True,
            "transactionId": state["transactionId"],
            "idempotencyKey": state["idempotencyKey"],
            "requestDigest": state["requestDigest"],
            "externalOperationId": operation_id,
            "externalPostId": post_id,
            "proofDigest": _provider_proof(
                platform=state["target"]["platform"],
                transaction_id=state["transactionId"],
                request_digest=state["requestDigest"],
                operation_id=operation_id,
                post_id=post_id,
                outcome=outcome,
            ),
        }
        return value

    def commit(self, state: Mapping[str, Any]) -> dict[str, Any]:
        self.commit_calls += 1
        key = state["idempotencyKey"]
        existing = self.effects.get(key)
        if existing is not None:
            return _clone(existing)
        if self.scenario == "timeout_before_dispatch":
            raise ProviderTimeoutBeforeDispatch("fake timeout before provider dispatch")
        if self.scenario == "duplicate_confirmed":
            value = self._outcome(state, outcome="duplicate_confirmed")
            self.effects[key] = _clone(value)
            return value
        if self.scenario == "unknown_no_lookup":
            self.effect_count += 1
            raise ProviderTimeoutAfterDispatch("fake unknown outcome without lookup support")
        value = self._outcome(state)
        self.effects[key] = _clone(value)
        self.effect_count += 1
        if self.scenario == "timeout_after_dispatch":
            raise ProviderTimeoutAfterDispatch("fake timeout after provider accepted operation")
        return value

    def lookup(self, state: Mapping[str, Any]) -> dict[str, Any]:
        self.lookup_calls += 1
        if self.scenario == "unknown_no_lookup":
            return {
                "outcome": "unknown",
                "authoritative": False,
                "reason": "provider_lookup_unavailable",
            }
        existing = self.effects.get(state["idempotencyKey"])
        if existing is None:
            return {
                "outcome": "absent",
                "authoritative": True,
                "requestDigest": state["requestDigest"],
            }
        return _clone(existing)


def _verify_provider_outcome(state: Mapping[str, Any], outcome: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "outcome",
        "authoritative",
        "transactionId",
        "idempotencyKey",
        "requestDigest",
        "externalOperationId",
        "externalPostId",
        "proofDigest",
    }
    if not isinstance(outcome, Mapping) or set(outcome) != required:
        raise OutcomeProofError("provider outcome fields mismatch")
    if outcome["outcome"] not in {"committed", "duplicate_confirmed"}:
        raise OutcomeProofError("provider outcome is not terminal committed proof")
    if outcome["authoritative"] is not True:
        raise OutcomeProofError("provider outcome is not authoritative")
    for key in ("transactionId", "idempotencyKey", "requestDigest"):
        if outcome[key] != state[key]:
            raise OutcomeProofError(f"provider outcome {key} mismatch")
    _nonempty(outcome["externalOperationId"], "externalOperationId")
    _nonempty(outcome["externalPostId"], "externalPostId")
    expected = _provider_proof(
        platform=state["target"]["platform"],
        transaction_id=state["transactionId"],
        request_digest=state["requestDigest"],
        operation_id=outcome["externalOperationId"],
        post_id=outcome["externalPostId"],
        outcome=outcome["outcome"],
    )
    if outcome["proofDigest"] != expected:
        raise OutcomeProofError("provider outcome proof digest mismatch")
    return _clone(outcome)


def _mark_reconciliation_required(
    ledger: TransactionLedger,
    *,
    reason: str,
    event_key: str,
) -> dict[str, Any]:
    state = ledger.state
    new = _clone(state)
    new["state"] = "RECONCILIATION_REQUIRED"
    new["blockers"] = [
        {
            "code": "RECONCILIATION_REQUIRED",
            "reason": reason,
            "blindRetryForbidden": True,
        }
    ]
    ledger._append(
        event_key=event_key,
        event_type="RECONCILIATION_REQUIRED",
        operation_id=state["commit"]["attemptId"] or "r33reconcile:" + state["transactionId"],
        request={"reason": reason, "requestDigest": state["requestDigest"]},
        new_state=new,
        input_artifacts={"requestDigest": state["requestDigest"], "winnerSha256": state["winner"]["sha256"]},
        output_artifacts={},
        timestamp_metadata="2026-10-04T00:00:06Z",
    )
    return _clone(new)


def _mark_committed(
    ledger: TransactionLedger,
    outcome: Mapping[str, Any],
    *,
    event_key: str,
) -> dict[str, Any]:
    state = ledger.state
    outcome = _verify_provider_outcome(state, outcome)
    new = _clone(state)
    new["state"] = "COMMITTED"
    new["commit"]["externalOperationId"] = outcome["externalOperationId"]
    new["commit"]["externalPostId"] = outcome["externalPostId"]
    new["commit"]["outcomeProofDigest"] = outcome["proofDigest"]
    new["commit"]["providerOutcome"] = outcome["outcome"]
    new["blockers"] = []
    ledger._append(
        event_key=event_key,
        event_type="TRANSACTION_COMMITTED",
        operation_id=state["commit"]["attemptId"] or "r33commit:" + state["transactionId"],
        request=outcome,
        new_state=new,
        input_artifacts={"requestDigest": state["requestDigest"], "winnerSha256": state["winner"]["sha256"]},
        output_artifacts={
            "externalOperationIdDigest": _sha_text(outcome["externalOperationId"]),
            "externalPostIdDigest": _sha_text(outcome["externalPostId"]),
            "outcomeProofDigest": outcome["proofDigest"],
        },
        timestamp_metadata="2026-10-04T00:00:07Z",
    )
    return _clone(new)


def commit_transaction(
    ledger: TransactionLedger,
    adapter: Any,
) -> dict[str, Any]:
    state = ledger.state
    if state["state"] == "COMMITTED":
        return _clone(state)
    if state["state"] == "RECONCILIATION_REQUIRED":
        raise ReconciliationRequired("blind retry forbidden while provider outcome is unknown")
    if state["state"] == "COMMIT_ELIGIBLE":
        begin_commit(ledger)
        state = ledger.state
    if state["state"] != "COMMITTING":
        raise InvalidTransition(f"commit forbidden from {state['state']}")
    if getattr(adapter, "is_fake", False) is not True:
        raise LivePublishForbidden("R33 milestone permits fake-provider harness only")
    if state["commit"]["invocationStarted"] is True:
        _mark_reconciliation_required(
            ledger,
            reason="restart_after_invocation_intent",
            event_key="reconciliation-after-restart",
        )
        raise ReconciliationRequired("provider invocation may have occurred; reconcile before retry")
    invoking = _clone(state)
    invoking["commit"]["invocationStarted"] = True
    invoking["blockers"] = [
        {
            "code": "PROVIDER_INVOCATION_IN_PROGRESS",
            "blindRetryForbiddenOnRestart": True,
        }
    ]
    ledger._append(
        event_key=f"provider-invocation-intent:{state['commit']['attemptNumber']}",
        event_type="PROVIDER_INVOCATION_INTENT",
        operation_id=state["commit"]["attemptId"],
        request={
            "transactionId": state["transactionId"],
            "idempotencyKey": state["idempotencyKey"],
            "requestDigest": state["requestDigest"],
            "networkEnabled": False,
        },
        new_state=invoking,
        input_artifacts={"requestDigest": state["requestDigest"], "winnerSha256": state["winner"]["sha256"]},
        output_artifacts={},
        timestamp_metadata="2026-10-04T00:00:05Z",
    )
    try:
        outcome = adapter.commit(ledger.state)
    except ProviderTimeoutBeforeDispatch:
        safe = _clone(ledger.state)
        safe["state"] = "COMMIT_ELIGIBLE"
        safe["commit"]["invocationStarted"] = False
        safe["blockers"] = [
            {
                "code": "KNOWN_NO_PROVIDER_DISPATCH",
                "safeToRetry": True,
            }
        ]
        ledger._append(
            event_key=f"provider-timeout-before-dispatch:{safe['commit']['attemptNumber']}",
            event_type="PROVIDER_NOT_DISPATCHED",
            operation_id=safe["commit"]["attemptId"],
            request={"requestDigest": safe["requestDigest"], "knownNoDispatch": True},
            new_state=safe,
            input_artifacts={"requestDigest": safe["requestDigest"]},
            output_artifacts={},
            timestamp_metadata="2026-10-04T00:00:06Z",
        )
        return _clone(safe)
    except ProviderTimeoutAfterDispatch:
        return _mark_reconciliation_required(
            ledger,
            reason="provider_dispatch_acknowledgement_unknown",
            event_key=f"reconciliation-after-dispatch:{ledger.state['commit']['attemptNumber']}",
        )
    return _mark_committed(ledger, outcome, event_key="commit-confirmed")


def reconcile_transaction(
    ledger: TransactionLedger,
    adapter: Any,
) -> dict[str, Any]:
    state = ledger.state
    if state["state"] == "COMMITTED":
        return _clone(state)
    if state["state"] not in {"RECONCILIATION_REQUIRED", "COMMITTING"}:
        raise InvalidTransition(f"reconciliation forbidden from {state['state']}")
    if getattr(adapter, "is_fake", False) is not True:
        raise LivePublishForbidden("R33 milestone permits fake read-only lookup only")
    outcome = adapter.lookup(state)
    if outcome.get("outcome") in {"committed", "duplicate_confirmed"}:
        return _mark_committed(ledger, outcome, event_key="reconcile-committed")
    if outcome.get("outcome") == "absent" and outcome.get("authoritative") is True:
        if outcome.get("requestDigest") != state["requestDigest"]:
            raise OutcomeProofError("authoritative absence request digest mismatch")
        new = _clone(state)
        new["state"] = "COMMIT_ELIGIBLE"
        new["commit"]["invocationStarted"] = False
        new["blockers"] = [{"code": "AUTHORITATIVE_PROVIDER_ABSENCE", "safeToRetry": True}]
        ledger._append(
            event_key="reconcile-absent",
            event_type="RECONCILED_PROVIDER_ABSENT",
            operation_id=state["commit"]["attemptId"] or "r33lookup:" + state["transactionId"],
            request=outcome,
            new_state=new,
            input_artifacts={"requestDigest": state["requestDigest"]},
            output_artifacts={"absenceProofDigest": _sha(outcome)},
            timestamp_metadata="2026-10-04T00:00:08Z",
        )
        return _clone(new)
    new = _clone(state)
    new["state"] = "RECONCILIATION_REQUIRED"
    new["blockers"] = [
        {
            "code": "RECONCILIATION_REQUIRED",
            "reason": outcome.get("reason", "provider_cannot_prove_outcome"),
            "blindRetryForbidden": True,
        }
    ]
    key = "reconcile-unknown:" + _sha(outcome)[:16]
    ledger._append(
        event_key=key,
        event_type="RECONCILIATION_STILL_UNKNOWN",
        operation_id=state["commit"]["attemptId"] or "r33lookup:" + state["transactionId"],
        request=outcome,
        new_state=new,
        input_artifacts={"requestDigest": state["requestDigest"]},
        output_artifacts={"lookupDigest": _sha(outcome)},
        timestamp_metadata="2026-10-04T00:00:08Z",
    )
    return _clone(new)


def transaction_status(ledger: TransactionLedger) -> dict[str, Any]:
    state = ledger.state
    allowed = {
        "PREPARED": "VALIDATE_OR_ABORT",
        "VALIDATED": "MARK_COMMIT_ELIGIBLE_OR_ABORT",
        "COMMIT_ELIGIBLE": "BEGIN_COMMIT_OR_HOLD",
        "COMMITTING": (
            "READ_ONLY_RECONCILE_BEFORE_RETRY"
            if state["commit"]["invocationStarted"]
            else "SAFE_TO_INVOKE_FAKE_PROVIDER"
        ),
        "RECONCILIATION_REQUIRED": "READ_ONLY_RECONCILE_ONLY",
        "COMMITTED": "NONE_ALREADY_COMMITTED",
        "ABORTED": "NONE_ABORTED",
    }[state["state"]]
    value = {
        "contractVersion": STATUS_VERSION,
        "transactionId": state["transactionId"],
        "idempotencyKey": state["idempotencyKey"],
        "platform": state["target"]["platform"],
        "state": state["state"],
        "allowedNextAction": allowed,
        "blockers": _clone(state["blockers"]),
        "winnerSha256": state["winner"]["sha256"],
        "winnerSize": state["winner"]["size"],
        "requestDigest": state["requestDigest"],
        "plannedPublishAt": state["schedule"]["plannedPublishAt"],
        "revision": state["revision"],
        "providerInvocationStarted": state["commit"]["invocationStarted"],
        "externalOperationConfirmed": state["commit"]["externalOperationId"] is not None,
        "externalPostConfirmed": state["commit"]["externalPostId"] is not None,
        "blindRetryPermitted": (
            state["state"] in {"COMMIT_ELIGIBLE"}
            or (state["state"] == "COMMITTING" and not state["commit"]["invocationStarted"])
        ),
        "realSideEffectPermitted": False,
        "networkPermitted": False,
        "ledgerDigest": ledger.digest,
    }
    value["statusDigest"] = _sha(value)
    return value


def batch_status(children: Sequence[TransactionLedger]) -> dict[str, Any]:
    rows = [transaction_status(item) for item in children]
    platforms = [row["platform"] for row in rows]
    if len(set(platforms)) != len(platforms):
        raise PublishTransactionError("publish batch requires unique platform children")
    counts = {state: 0 for state in sorted(STATES)}
    for row in rows:
        counts[row["state"]] += 1
    value = {
        "contractVersion": BATCH_VERSION,
        "children": [
            {
                "transactionId": row["transactionId"],
                "platform": row["platform"],
                "state": row["state"],
                "allowedNextAction": row["allowedNextAction"],
                "blindRetryPermitted": row["blindRetryPermitted"],
            }
            for row in rows
        ],
        "counts": counts,
        "committedPlatforms": [row["platform"] for row in rows if row["state"] == "COMMITTED"],
        "blockedPlatforms": [
            row["platform"]
            for row in rows
            if row["state"] in {"RECONCILIATION_REQUIRED", "COMMITTING"}
        ],
        "abortedPlatforms": [row["platform"] for row in rows if row["state"] == "ABORTED"],
        "realSideEffectPermitted": False,
    }
    value["batchDigest"] = _sha(value)
    return value


def schedule_revision_spec(
    ledger: TransactionLedger,
    *,
    new_planned_publish_at: str | None,
) -> dict[str, Any]:
    state = ledger.state
    if state["state"] in {"COMMITTING", "RECONCILIATION_REQUIRED", "COMMITTED", "ABORTED"}:
        raise InvalidTransition("schedule revision forbidden after commit/abort boundary")
    revision = state["revision"] + 1
    schedule = {
        "plannedPublishAt": new_planned_publish_at,
        "scheduleDigest": _sha({"plannedPublishAt": new_planned_publish_at, "revision": revision}),
    }
    identity = {
        "parentTransactionId": state["transactionId"],
        "revision": revision,
        "winner": state["winner"],
        "lineage": state["lineage"],
        "target": state["target"],
        "contentHashes": state["contentHashes"],
        "publishPolicyHash": state["publishPolicyHash"],
        "schedule": schedule,
        "r32Authority": state["r32Authority"],
    }
    new_transaction_id = "r33tx:" + _sha(identity)
    value = {
        "parentTransactionId": state["transactionId"],
        "revision": revision,
        "newPlannedPublishAt": new_planned_publish_at,
        "newScheduleDigest": schedule["scheduleDigest"],
        "newTransactionId": new_transaction_id,
        "newIdempotencyKey": "r33idem:" + _sha(
            {"transactionId": new_transaction_id, "platform": state["target"]["platform"]}
        ),
        "requiresNewLedger": True,
    }
    value["revisionDigest"] = _sha(value)
    return value


def readiness() -> dict[str, Any]:
    value = {
        "reportVersion": READINESS_VERSION,
        "state": "SOURCE_READY_NO_LIVE_PUBLISH",
        "SOURCE_READY": True,
        "LIVE_PUBLISH_ENABLED": False,
        "creatorR32Authority": _clone(CREATOR_R32_AUTHORITY),
        "transactionContract": CONTRACT_VERSION,
        "states": [
            "PREPARED",
            "VALIDATED",
            "COMMIT_ELIGIBLE",
            "COMMITTING",
            "RECONCILIATION_REQUIRED",
            "COMMITTED",
            "ABORTED",
        ],
        "platforms": {
            key: {
                "adapter": value["adapter"],
                "provider": value["provider"],
                "phases": value["phases"],
                "readOnlyRecovery": value["readOnlyRecovery"],
            }
            for key, value in PLATFORM_METADATA.items()
        },
        "safety": {
            "realSideEffectPermitted": False,
            "networkPermitted": False,
            "blindRetryAfterUnknown": False,
            "credentialsStored": False,
            "livePublish": False,
            "mergePerformed": False,
        },
    }
    value["reportDigest"] = _sha(value)
    return value


def _fixture_upstream() -> tuple[dict[str, Any], dict[str, Any]]:
    final_sha = "d" * 64
    source_sha = "a" * 64
    state = {
        "contractVersion": r32.CONTRACT_VERSION,
        "sessionId": "r32s:" + "1" * 64,
        "tournamentId": "r32t:" + "2" * 64,
        "state": "PUBLISH_HANDOFF_READY",
        "source": {"sha256": source_sha, "size": 790819, "durationMs": 30000},
        "briefDigest": "b" * 64,
        "authorityDigest": "c" * 64,
        "reviewRound": 1,
        "reeditRound": 1,
        "candidatePackageDigest": "3" * 64,
        "candidateIds": ["r32c:" + "4" * 64],
        "dispatches": {},
        "consensusDigest": "5" * 64,
        "selectedCandidateId": "r32c:" + "4" * 64,
        "selectedRender": {"candidateId": "r32c:" + "4" * 64},
        "reeditApplicationDigest": "6" * 64,
        "publishHandoffDigest": None,
        "reconciliationRequired": False,
        "blockers": [],
    }
    handoff = {
        "contractVersion": "creator.editor_publish_handoff.v1",
        "handoffClass": "frozen_contract_fixture",
        "sessionId": state["sessionId"],
        "tournamentId": state["tournamentId"],
        "winnerCandidateId": state["selectedCandidateId"],
        "finalArtifact": {"fileName": "final.mp4", "sha256": final_sha, "size": 646823},
        "sourceSha256": source_sha,
        "consensusDigest": state["consensusDigest"],
        "livePublish": False,
        "providerMutation": False,
        "humanGroundTruth": False,
        "handoffDigest": "",
    }
    material = copy.deepcopy(handoff)
    material["handoffDigest"] = ""
    handoff["handoffDigest"] = _sha(material)
    state["publishHandoffDigest"] = handoff["handoffDigest"]
    return state, handoff


def _fixture_media(handoff: Mapping[str, Any], platform: str) -> dict[str, Any]:
    return {
        "sha256": handoff["finalArtifact"]["sha256"],
        "sizeBytes": handoff["finalArtifact"]["size"],
        "contentType": "video/mp4",
        "aspectRatio": "9:16",
        "durationSeconds": 30.0,
        "width": 1080,
        "height": 1920,
        "fps": 30.0,
        "videoCodec": "h264",
        "audioCodec": "aac",
        "publicHttpsUrlAvailable": platform in {"instagram_reels", "tiktok"},
    }


def _target(platform: str) -> dict[str, str]:
    account = {
        "instagram_reels": "ig-account-r33",
        "tiktok": "tt-account-r33",
        "youtube_shorts": "yt-channel-r33",
    }[platform]
    destination = {
        "instagram_reels": "profile:" + account,
        "tiktok": "privacy:SELF_ONLY",
        "youtube_shorts": "privacy:private",
    }[platform]
    return {
        "platform": platform,
        "provider_adapter": PLATFORM_METADATA[platform]["adapter"],
        "account_ref": account,
        "destination": destination,
        "credential_ref": f"vault-ref://{platform}/r33",
        "authorization_ref": f"oauth-ref://{platform}/r33",
        "configuration_ref": f"provider-config://{platform}/r33",
    }


def _new_fixture_transaction(root: Path, platform: str, *, suffix: str = "") -> TransactionLedger:
    upstream, handoff = _fixture_upstream()
    target = _target(platform)
    return prepare_transaction(
        root / f"{platform}{suffix}.jsonl",
        upstream_state=upstream,
        handoff=handoff,
        upstream_outcome="winner",
        media_metadata=_fixture_media(handoff, platform),
        caption="R33 deterministic caption",
        title="R33 deterministic title",
        thumbnail_sha256="e" * 64,
        publish_policy={"comments": "provider_default", "visibilityPolicy": target["destination"]},
        planned_publish_at="2026-10-05T12:00:00Z",
        **target,
    )


def run_rehearsal(work_dir: str | os.PathLike[str]) -> dict[str, Any]:
    root = Path(work_dir)
    root.mkdir(parents=True, exist_ok=True)

    instagram = _new_fixture_transaction(root, "instagram_reels")
    validate_prepared(instagram)
    mark_commit_eligible(instagram)
    instagram_adapter = FakeProviderHarness("clean_success")
    commit_transaction(instagram, instagram_adapter)
    instagram_effects = instagram_adapter.effect_count
    # Duplicate commit after durable COMMITTED must not touch provider.
    commit_transaction(instagram, instagram_adapter)
    if instagram_adapter.effect_count != instagram_effects:
        raise AssertionError("COMMITTED replay invoked provider again")

    tiktok = _new_fixture_transaction(root, "tiktok")
    validate_prepared(tiktok)
    mark_commit_eligible(tiktok)
    tiktok_adapter = FakeProviderHarness("timeout_after_dispatch")
    state = commit_transaction(tiktok, tiktok_adapter)
    if state["state"] != "RECONCILIATION_REQUIRED":
        raise AssertionError("timeout-after-dispatch did not require reconciliation")
    before_calls = tiktok_adapter.commit_calls
    try:
        commit_transaction(tiktok, tiktok_adapter)
    except ReconciliationRequired:
        pass
    else:
        raise AssertionError("unknown outcome allowed blind retry")
    if tiktok_adapter.commit_calls != before_calls:
        raise AssertionError("blind retry invoked provider")
    reconcile_transaction(tiktok, tiktok_adapter)

    youtube = _new_fixture_transaction(root, "youtube_shorts")
    validate_prepared(youtube)
    mark_commit_eligible(youtube)
    youtube_adapter = FakeProviderHarness("unknown_no_lookup")
    commit_transaction(youtube, youtube_adapter)
    unknown_before = youtube_adapter.commit_calls
    reconcile_transaction(youtube, youtube_adapter)
    if youtube.state["state"] != "RECONCILIATION_REQUIRED":
        raise AssertionError("unknown provider outcome escaped reconciliation")
    try:
        commit_transaction(youtube, youtube_adapter)
    except ReconciliationRequired:
        pass
    else:
        raise AssertionError("unknown-no-lookup allowed commit")
    if youtube_adapter.commit_calls != unknown_before:
        raise AssertionError("unknown-no-lookup caused duplicate provider call")

    safe = _new_fixture_transaction(root, "instagram_reels", suffix="-timeout-before")
    validate_prepared(safe)
    mark_commit_eligible(safe)
    before_adapter = FakeProviderHarness("timeout_before_dispatch")
    commit_transaction(safe, before_adapter)
    if safe.state["state"] != "COMMIT_ELIGIBLE" or before_adapter.effect_count != 0:
        raise AssertionError("timeout-before-dispatch was not safely retryable")
    success_after_safe_timeout = FakeProviderHarness("clean_success")
    commit_transaction(safe, success_after_safe_timeout)
    if success_after_safe_timeout.effect_count != 1:
        raise AssertionError("safe pre-dispatch retry did not execute exactly once")

    batch = batch_status([instagram, tiktok, youtube])
    report = {
        "reportVersion": REHEARSAL_VERSION,
        "state": "SOURCE_READY_NO_LIVE_PUBLISH",
        "r32Authority": _clone(CREATOR_R32_AUTHORITY),
        "cleanSuccess": transaction_status(instagram),
        "timeoutAfterDispatchReconciled": transaction_status(tiktok),
        "unknownNoLookup": transaction_status(youtube),
        "timeoutBeforeDispatchSafeRetry": transaction_status(safe),
        "batchStatus": batch,
        "effects": {
            "instagram": instagram_adapter.effect_count,
            "tiktok": tiktok_adapter.effect_count,
            "youtube": youtube_adapter.effect_count,
            "safeRetryTransaction": success_after_safe_timeout.effect_count,
            "realProvider": 0,
        },
        "unknownOutcomeBlindRetryAttempted": False,
        "networkUsed": False,
        "livePublish": False,
        "credentialsStored": False,
    }
    report["reportDigest"] = _sha(report)
    (root / "rehearsal.r33.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "batch-status.r33.json").write_text(
        json.dumps(batch, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    evidence = {
        "contractVersion": EVIDENCE_VERSION,
        "r32Authority": _clone(CREATOR_R32_AUTHORITY),
        "rehearsalDigest": report["reportDigest"],
        "transactions": {
            item.state["target"]["platform"]: {
                "transactionId": item.state["transactionId"],
                "requestDigest": item.state["requestDigest"],
                "state": item.state["state"],
                "ledgerDigest": item.digest,
                "winnerSha256": item.state["winner"]["sha256"],
            }
            for item in (instagram, tiktok, youtube)
        },
        "unknownOutcomeBlindRetryForbidden": True,
        "realProviderEffects": 0,
        "networkUsed": False,
        "livePublish": False,
    }
    evidence["evidenceDigest"] = _sha(evidence)
    (root / "evidence-manifest.r33.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="creator-publish-transaction-r33")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("readiness")
    p.add_argument("--out")
    p = sub.add_parser("status")
    p.add_argument("--ledger", required=True)
    p.add_argument("--out")
    p = sub.add_parser("reconcile")
    p.add_argument("--ledger", required=True)
    p.add_argument("--fake-scenario", choices=tuple(sorted(FakeProviderHarness.SCENARIOS)))
    p.add_argument("--out")
    p = sub.add_parser("rehearsal")
    p.add_argument("--out", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "readiness":
        value = readiness()
    elif args.command == "status":
        value = transaction_status(TransactionLedger(args.ledger))
    elif args.command == "reconcile":
        ledger = TransactionLedger(args.ledger)
        if not args.fake_scenario:
            value = transaction_status(ledger)
            value["allowedNextAction"] = "BLOCKED_NO_READ_ONLY_PROVIDER_LOOKUP_ADAPTER"
            value["blockers"] = value["blockers"] + [
                {
                    "code": "NO_PROVIDER_LOOKUP_ADAPTER",
                    "realNetworkDisabled": True,
                }
            ]
            value["statusDigest"] = _sha({k: v for k, v in value.items() if k != "statusDigest"})
        else:
            adapter = FakeProviderHarness(args.fake_scenario)
            try:
                reconcile_transaction(ledger, adapter)
            except InvalidTransition:
                pass
            value = transaction_status(ledger)
    else:
        value = run_rehearsal(args.out)
    if getattr(args, "out", None) and args.command != "rehearsal":
        Path(args.out).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
