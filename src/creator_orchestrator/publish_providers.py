from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

from .autonomous_reels import (
    ContractValidationError,
    InjectedCrash,
    PublishGateError,
    PublishOutcomeUnknown,
    _nonempty,
    _parse_time,
    _reject_secrets,
    _sha64,
    _validate_release_authorization,
    canonical_json,
    sha256_json,
)

PUBLISH_PROVIDER_CONTRACT_VERSION = "creator.publish_provider.v1"
PUBLISH_REQUEST_VERSION = "creator.publish_request.v1"
PUBLISH_PREPARE_VERSION = "creator.publish_provider_prepare.v1"
PUBLISH_STATUS_VERSION = "creator.publish_provider_status.v1"
PUBLISH_RECEIPT_VERSION = "creator.publish_provider_receipt.v2"
PUBLISH_LEDGER_VERSION = "creator.publish_provider_ledger.v1"
PUBLISH_GROWTH_HANDOFF_VERSION = "creator.publish_provider_growth_handoff.v1"

PLATFORMS = frozenset({"instagram_reels", "tiktok", "youtube_shorts"})
OPERATOR_STATES = frozenset({
    "waiting_for_credentials",
    "waiting_for_provider_processing",
    "recoverable_unknown",
    "published",
    "failed_terminal",
})
PROVIDER_STATES = frozenset({"absent", "processing", "published", "failed_terminal", "unknown"})


class PublishProvider(Protocol):
    platform: str
    source_class: str

    def prepare(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def submit(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def recover(self, idempotency_key: str) -> Mapping[str, Any]: ...
    def status(self, operation_ref: str) -> Mapping[str, Any]: ...


def _validate_media_binding(media: Mapping[str, Any], *, allow_synthetic_fixture: bool) -> dict[str, Any]:
    fields = {
        "sourceClass", "contentId", "contentSha256", "sizeBytes", "contentType",
        "durationSeconds", "aspectRatio", "manifestDigest",
    }
    if not isinstance(media, Mapping) or set(media) != fields:
        raise ContractValidationError("publish media binding fields must match exactly")
    source_class = media["sourceClass"]
    if source_class not in {"provider", "synthetic_fixture"}:
        raise ContractValidationError("unsupported media sourceClass")
    if source_class == "synthetic_fixture" and not allow_synthetic_fixture:
        raise PublishGateError("synthetic Media evidence is conformance-only")
    digest = _sha64(media["contentSha256"], "media contentSha256")
    _sha64(media["manifestDigest"], "media manifestDigest")
    if media["contentId"] != f"sha256:{digest}":
        raise ContractValidationError("media contentId must bind contentSha256")
    if isinstance(media["sizeBytes"], bool) or not isinstance(media["sizeBytes"], int) or media["sizeBytes"] <= 0:
        raise ContractValidationError("media sizeBytes must be a positive integer")
    if media["contentType"] != "video/mp4":
        raise PublishGateError("publish providers require video/mp4")
    duration = media["durationSeconds"]
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 15 <= float(duration) <= 60:
        raise PublishGateError("media duration must remain inside Creator canonical 15-60s profile")
    if media["aspectRatio"] != "9:16":
        raise PublishGateError("media aspect ratio must be 9:16")
    return json.loads(canonical_json(media))


def _request_identity(
    *,
    platform: str,
    account_id: str,
    destination: str,
    media: Mapping[str, Any],
    caption: str,
    cta: str,
    authorization_digest: str,
) -> dict[str, Any]:
    return {
        "platform": platform,
        "accountId": account_id,
        "destination": destination,
        "mediaContentSha256": media["contentSha256"],
        "mediaManifestDigest": media["manifestDigest"],
        "caption": caption,
        "cta": cta,
        "releaseAuthorizationDigest": authorization_digest,
    }


def build_publish_request(
    *,
    platform: str,
    account_id: str,
    destination: str,
    credential_ref: str,
    authorization_lineage: Mapping[str, Any],
    media: Mapping[str, Any],
    caption: str,
    cta: str,
    release_authorization: Mapping[str, Any],
    allow_synthetic_fixture: bool = False,
) -> dict[str, Any]:
    if platform not in PLATFORMS:
        raise PublishGateError("unsupported publish platform")
    for value, field_name in (
        (account_id, "account_id"), (destination, "destination"),
        (credential_ref, "credential_ref"), (caption, "caption"), (cta, "cta"),
    ):
        _nonempty(value, field_name)
    if (
        not isinstance(authorization_lineage, Mapping)
        or set(authorization_lineage) != {"credentialRef", "authorizationRef"}
    ):
        raise ContractValidationError("authorization lineage fields must match exactly")
    if authorization_lineage["credentialRef"] != credential_ref:
        raise PublishGateError("authorization lineage credential reference mismatch")
    _nonempty(authorization_lineage["authorizationRef"], "authorizationRef")
    bound_media = _validate_media_binding(media, allow_synthetic_fixture=allow_synthetic_fixture)
    auth = _validate_release_authorization(
        release_authorization,
        bound_media["contentId"],
        bound_media["contentSha256"],
        platform,
        destination,
    )
    authorization_digest = sha256_json(auth)
    identity = _request_identity(
        platform=platform,
        account_id=account_id,
        destination=destination,
        media=bound_media,
        caption=caption,
        cta=cta,
        authorization_digest=authorization_digest,
    )
    idempotency_key = "cpp1:" + sha256_json(identity)
    publish_id = "publish1:" + sha256_json({"idempotencyKey": idempotency_key})
    request = {
        "contractVersion": PUBLISH_REQUEST_VERSION,
        "publishId": publish_id,
        "idempotencyKey": idempotency_key,
        "platform": platform,
        "accountId": account_id,
        "destination": destination,
        "credentialRef": credential_ref,
        "authorizationLineage": json.loads(canonical_json(authorization_lineage)),
        "media": bound_media,
        "caption": caption,
        "cta": cta,
        "releaseAuthorization": auth,
    }
    _reject_secrets(request)
    return request


def validate_publish_request(
    request: Mapping[str, Any], *, allow_synthetic_fixture: bool = False
) -> dict[str, Any]:
    fields = {
        "contractVersion", "publishId", "idempotencyKey", "platform", "accountId",
        "destination", "credentialRef", "authorizationLineage", "media", "caption",
        "cta", "releaseAuthorization",
    }
    if not isinstance(request, Mapping) or set(request) != fields:
        raise ContractValidationError("publish request fields must match exactly")
    if request["contractVersion"] != PUBLISH_REQUEST_VERSION:
        raise ContractValidationError("unsupported publish request version")
    rebuilt = build_publish_request(
        platform=request["platform"],
        account_id=request["accountId"],
        destination=request["destination"],
        credential_ref=request["credentialRef"],
        authorization_lineage=request["authorizationLineage"],
        media=request["media"],
        caption=request["caption"],
        cta=request["cta"],
        release_authorization=request["releaseAuthorization"],
        allow_synthetic_fixture=allow_synthetic_fixture,
    )
    if rebuilt != request:
        raise PublishGateError("publish request identity or binding mismatch")
    return rebuilt


def _validate_prepare(prepared: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "contractVersion", "platform", "accountId", "destination", "credentialRef",
        "credentialsAvailable", "capability", "evidenceDigest",
    }
    if not isinstance(prepared, Mapping) or set(prepared) != fields:
        raise ContractValidationError("provider prepare result fields must match exactly")
    if prepared["contractVersion"] != PUBLISH_PREPARE_VERSION:
        raise ContractValidationError("unsupported provider prepare version")
    for field_name, request_name in (
        ("platform", "platform"), ("accountId", "accountId"),
        ("destination", "destination"), ("credentialRef", "credentialRef"),
    ):
        if prepared[field_name] != request[request_name]:
            raise PublishGateError(f"provider prepare {field_name} binding mismatch")
    capability = prepared["capability"]
    expected = {
        "supported", "reason", "idempotentSubmit", "authoritativeRecovery",
        "asyncProcessing", "phases",
    }
    if not isinstance(capability, Mapping) or set(capability) != expected:
        raise ContractValidationError("provider capability fields must match exactly")
    if capability["idempotentSubmit"] is not True or capability["authoritativeRecovery"] is not True:
        raise PublishGateError("provider lacks required idempotency/recovery guarantees")
    if capability["asyncProcessing"] is not True:
        raise PublishGateError("provider must expose asynchronous processing status")
    if capability["phases"] != [
        "create_or_upload_session", "provider_processing", "publish_commit", "terminal_receipt"
    ]:
        raise ContractValidationError("provider capability phase plan mismatch")
    material = dict(prepared)
    digest = material.pop("evidenceDigest")
    _sha64(digest, "provider prepare evidenceDigest")
    if sha256_json(material) != digest:
        raise ContractValidationError("provider prepare evidence digest mismatch")
    _reject_secrets(prepared)
    return json.loads(canonical_json(prepared))


def _validate_status(status: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "contractVersion", "platform", "idempotencyKey", "state", "phase",
        "authoritative", "operationRef", "postId", "publishedAt", "capturedAt",
        "sourceClass", "statusDigest",
    }
    if not isinstance(status, Mapping) or set(status) != fields:
        raise ContractValidationError("provider status fields must match exactly")
    if status["contractVersion"] != PUBLISH_STATUS_VERSION:
        raise ContractValidationError("unsupported provider status version")
    if status["platform"] != request["platform"] or status["idempotencyKey"] != request["idempotencyKey"]:
        raise PublishGateError("provider status identity mismatch")
    if status["state"] not in PROVIDER_STATES:
        raise ContractValidationError("unsupported provider status state")
    if status["sourceClass"] not in {"provider_receipt", "synthetic_fixture"}:
        raise ContractValidationError("unsupported provider status sourceClass")
    if status["state"] == "absent":
        if status["operationRef"] is not None or status["postId"] is not None:
            raise ContractValidationError("absent provider status cannot contain operation identity")
    else:
        if status["state"] != "unknown":
            _nonempty(status["operationRef"], "provider operationRef")
    if status["state"] == "published":
        for field_name in ("postId", "publishedAt", "capturedAt"):
            _nonempty(status[field_name], field_name)
    material = dict(status)
    digest = material.pop("statusDigest")
    _sha64(digest, "provider statusDigest")
    if sha256_json(material) != digest:
        raise ContractValidationError("provider status digest mismatch")
    _reject_secrets(status)
    return json.loads(canonical_json(status))


def _receipt_digest(receipt: Mapping[str, Any]) -> str:
    material = dict(receipt)
    material.pop("receiptDigest", None)
    return sha256_json(material)


def validate_provider_receipt(
    receipt: Mapping[str, Any],
    request: Mapping[str, Any],
    *,
    allow_synthetic_fixture: bool = False,
) -> dict[str, Any]:
    request = validate_publish_request(request, allow_synthetic_fixture=allow_synthetic_fixture)
    fields = {
        "contractVersion", "providerContractVersion", "sourceClass", "platform",
        "accountId", "destination", "publishId", "idempotencyKey", "operationRef",
        "postId", "mediaContentId", "mediaContentSha256", "mediaManifestDigest",
        "caption", "cta", "authorizationId", "releaseAuthorizationDigest",
        "releaseAuthorizationExpiresAt", "authorizationLineage", "publishedAt",
        "capturedAt", "terminalState", "receiptDigest",
    }
    if not isinstance(receipt, Mapping) or set(receipt) != fields:
        raise ContractValidationError("provider receipt fields must match exactly")
    if receipt["contractVersion"] != PUBLISH_RECEIPT_VERSION:
        raise PublishGateError("unsupported provider receipt version")
    if receipt["providerContractVersion"] != PUBLISH_PROVIDER_CONTRACT_VERSION:
        raise PublishGateError("provider contract version mismatch")
    if receipt["terminalState"] != "published":
        raise PublishGateError("provider receipt must be terminal published")
    if receipt["sourceClass"] not in {"provider_receipt", "synthetic_fixture"}:
        raise PublishGateError("unsupported provider receipt sourceClass")
    if receipt["sourceClass"] == "synthetic_fixture" and not allow_synthetic_fixture:
        raise PublishGateError("synthetic provider receipt is conformance-only")
    if receipt["sourceClass"] == "provider_receipt" and request["media"]["sourceClass"] != "provider":
        raise PublishGateError("live provider receipt requires provider-sourced Media evidence")
    auth = request["releaseAuthorization"]
    expected = {
        "platform": request["platform"],
        "accountId": request["accountId"],
        "destination": request["destination"],
        "publishId": request["publishId"],
        "idempotencyKey": request["idempotencyKey"],
        "mediaContentId": request["media"]["contentId"],
        "mediaContentSha256": request["media"]["contentSha256"],
        "mediaManifestDigest": request["media"]["manifestDigest"],
        "caption": request["caption"],
        "cta": request["cta"],
        "authorizationId": auth["authorizationId"],
        "releaseAuthorizationDigest": sha256_json(auth),
        "releaseAuthorizationExpiresAt": auth["expiresAt"],
        "authorizationLineage": request["authorizationLineage"],
    }
    for field_name, expected_value in expected.items():
        if receipt[field_name] != expected_value:
            raise PublishGateError(f"provider receipt {field_name} binding mismatch")
    for field_name in ("operationRef", "postId", "publishedAt", "capturedAt"):
        _nonempty(receipt[field_name], field_name)
    _sha64(receipt["mediaContentSha256"], "receipt mediaContentSha256")
    _sha64(receipt["mediaManifestDigest"], "receipt mediaManifestDigest")
    _sha64(receipt["releaseAuthorizationDigest"], "releaseAuthorizationDigest")
    _sha64(receipt["receiptDigest"], "receiptDigest")
    if _parse_time(receipt["publishedAt"], "publishedAt") >= _parse_time(
        receipt["releaseAuthorizationExpiresAt"], "releaseAuthorizationExpiresAt"
    ):
        raise PublishGateError("provider publish completed after release authorization expiry")
    if _receipt_digest(receipt) != receipt["receiptDigest"]:
        raise PublishGateError("provider receipt digest mismatch")
    _reject_secrets(receipt)
    return json.loads(canonical_json(receipt))


def build_growth_handoff(
    receipt: Mapping[str, Any],
    request: Mapping[str, Any],
    *,
    allow_synthetic_fixture: bool = False,
) -> dict[str, Any]:
    receipt = validate_provider_receipt(
        receipt, request, allow_synthetic_fixture=allow_synthetic_fixture
    )
    live = (
        receipt["sourceClass"] == "provider_receipt"
        and request["media"]["sourceClass"] == "provider"
    )
    handoff = {
        "contractVersion": PUBLISH_GROWTH_HANDOFF_VERSION,
        "sourceClass": "platform_export" if live else "synthetic_fixture",
        "livePerformanceClaimEligible": live,
        "providerReceiptDigest": receipt["receiptDigest"],
        "platform": receipt["platform"],
        "accountId": receipt["accountId"],
        "postId": receipt["postId"],
        "publishedAt": receipt["publishedAt"],
        "mediaContentSha256": receipt["mediaContentSha256"],
    }
    handoff["handoffDigest"] = sha256_json(handoff)
    return handoff


class DurablePublishCoordinator:
    def __init__(
        self,
        path: str | os.PathLike[str],
        request: Mapping[str, Any],
        *,
        allow_synthetic_fixture: bool = False,
    ) -> None:
        self.path = Path(path)
        self.allow_synthetic_fixture = allow_synthetic_fixture
        self.request = validate_publish_request(
            request, allow_synthetic_fixture=allow_synthetic_fixture
        )
        self.events: list[dict[str, Any]] = []
        self.prepared: dict[str, Any] | None = None
        self.provider_status: dict[str, Any] | None = None
        self.receipt: dict[str, Any] | None = None
        self.operator_state: str | None = None
        self.operator_reason: str | None = None
        if self.path.exists():
            self._load()
        else:
            self._append("request_created", self.request)

    def _event(self, event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = {
            "ledgerVersion": PUBLISH_LEDGER_VERSION,
            "sequence": len(self.events) + 1,
            "eventType": event_type,
            "payload": json.loads(canonical_json(payload)),
        }
        body["eventDigest"] = sha256_json(body)
        return body

    def _append(self, event_type: str, payload: Mapping[str, Any]) -> None:
        _reject_secrets(payload)
        event = self._event(event_type, payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.events.append(event)
        self._apply(event)

    def _load(self) -> None:
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ContractValidationError(f"invalid publish ledger JSON line {line_number}") from exc
            if set(event) != {"ledgerVersion", "sequence", "eventType", "payload", "eventDigest"}:
                raise ContractValidationError("publish ledger event fields must match exactly")
            if event["ledgerVersion"] != PUBLISH_LEDGER_VERSION:
                raise ContractValidationError("publish ledger version mismatch")
            if event["sequence"] != len(self.events) + 1:
                raise ContractValidationError("publish ledger sequence mismatch")
            material = dict(event)
            digest = material.pop("eventDigest")
            if sha256_json(material) != digest:
                raise ContractValidationError("publish ledger event digest mismatch")
            self.events.append(event)
            self._apply(event)
        if not self.events or self.events[0]["eventType"] != "request_created":
            raise ContractValidationError("publish ledger missing request_created")
        if self.events[0]["payload"] != self.request:
            raise PublishGateError("publish ledger request identity mismatch")

    def _apply(self, event: Mapping[str, Any]) -> None:
        event_type = event["eventType"]
        payload = event["payload"]
        if event_type == "request_created":
            if len(self.events) != 1:
                raise ContractValidationError("request_created must be first")
        elif event_type == "provider_prepared":
            self.prepared = json.loads(canonical_json(payload))
        elif event_type == "provider_observed":
            self.provider_status = json.loads(canonical_json(payload))
        elif event_type == "operator_state":
            if payload["state"] not in OPERATOR_STATES:
                raise ContractValidationError("unknown operator state")
            self.operator_state = payload["state"]
            self.operator_reason = payload["reason"]
        elif event_type == "receipt_committed":
            self.receipt = validate_provider_receipt(
                payload, self.request, allow_synthetic_fixture=self.allow_synthetic_fixture
            )
        else:
            raise ContractValidationError(f"unknown publish ledger event type {event_type!r}")

    def _set_state(self, state: str, reason: str) -> None:
        if state not in OPERATOR_STATES:
            raise ContractValidationError("unsupported operator state")
        if self.operator_state == state and self.operator_reason == reason:
            return
        self._append("operator_state", {"state": state, "reason": reason})

    def snapshot(self) -> dict[str, Any]:
        return {
            "contractVersion": PUBLISH_LEDGER_VERSION,
            "publishId": self.request["publishId"],
            "idempotencyKey": self.request["idempotencyKey"],
            "platform": self.request["platform"],
            "state": self.operator_state,
            "reason": self.operator_reason,
            "providerOperationRef": None if self.provider_status is None else self.provider_status["operationRef"],
            "receiptDigest": None if self.receipt is None else self.receipt["receiptDigest"],
            "eventCount": len(self.events),
            "ledgerDigest": sha256_json(self.events),
        }

    def _published_receipt(self, status: Mapping[str, Any]) -> dict[str, Any]:
        auth = self.request["releaseAuthorization"]
        receipt = {
            "contractVersion": PUBLISH_RECEIPT_VERSION,
            "providerContractVersion": PUBLISH_PROVIDER_CONTRACT_VERSION,
            "sourceClass": status["sourceClass"],
            "platform": self.request["platform"],
            "accountId": self.request["accountId"],
            "destination": self.request["destination"],
            "publishId": self.request["publishId"],
            "idempotencyKey": self.request["idempotencyKey"],
            "operationRef": status["operationRef"],
            "postId": status["postId"],
            "mediaContentId": self.request["media"]["contentId"],
            "mediaContentSha256": self.request["media"]["contentSha256"],
            "mediaManifestDigest": self.request["media"]["manifestDigest"],
            "caption": self.request["caption"],
            "cta": self.request["cta"],
            "authorizationId": auth["authorizationId"],
            "releaseAuthorizationDigest": sha256_json(auth),
            "releaseAuthorizationExpiresAt": auth["expiresAt"],
            "authorizationLineage": self.request["authorizationLineage"],
            "publishedAt": status["publishedAt"],
            "capturedAt": status["capturedAt"],
            "terminalState": "published",
        }
        receipt["receiptDigest"] = _receipt_digest(receipt)
        return validate_provider_receipt(
            receipt, self.request, allow_synthetic_fixture=self.allow_synthetic_fixture
        )

    def drive(self, provider: PublishProvider, *, now: str) -> dict[str, Any]:
        if self.receipt is not None:
            return {"state": "published", "receipt": self.receipt}
        if self.operator_state == "failed_terminal":
            return {"state": "failed_terminal", "receipt": None}
        if provider.platform != self.request["platform"]:
            raise PublishGateError("runtime provider platform mismatch")
        auth_expiry = _parse_time(self.request["releaseAuthorization"]["expiresAt"], "expiresAt")
        if _parse_time(now, "now") >= auth_expiry:
            self._set_state("failed_terminal", "release_authorization_expired")
            return {"state": "failed_terminal", "receipt": None}

        prepared = _validate_prepare(provider.prepare(self.request), self.request)
        self._append("provider_prepared", prepared)
        if prepared["credentialsAvailable"] is not True:
            self._set_state("waiting_for_credentials", "credential_reference_not_authorized")
            return {"state": "waiting_for_credentials", "receipt": None}
        if prepared["capability"]["supported"] is not True:
            self._set_state("failed_terminal", prepared["capability"]["reason"])
            return {"state": "failed_terminal", "receipt": None}

        status = self.provider_status
        if status is None or status["operationRef"] is None:
            recovered = _validate_status(
                provider.recover(self.request["idempotencyKey"]), self.request
            )
            if recovered["state"] == "unknown" or (
                recovered["state"] == "absent" and recovered["authoritative"] is not True
            ):
                self._append("provider_observed", recovered)
                self._set_state("recoverable_unknown", "provider_recovery_not_authoritative")
                return {"state": "recoverable_unknown", "receipt": None}
            if recovered["state"] == "absent":
                try:
                    status = _validate_status(provider.submit(self.request), self.request)
                except PublishOutcomeUnknown:
                    self._set_state("recoverable_unknown", "submit_acknowledgement_unknown")
                    return {"state": "recoverable_unknown", "receipt": None}
                self._append("provider_observed", status)
            else:
                status = recovered
                self._append("provider_observed", status)
        else:
            status = _validate_status(provider.status(status["operationRef"]), self.request)
            self._append("provider_observed", status)

        if status["state"] == "unknown":
            self._set_state("recoverable_unknown", "provider_status_unknown")
            return {"state": "recoverable_unknown", "receipt": None}
        if status["state"] == "failed_terminal":
            self._set_state("failed_terminal", "provider_failed_terminal")
            return {"state": "failed_terminal", "receipt": None}
        if status["state"] in {"absent", "processing"}:
            self._set_state("waiting_for_provider_processing", status["phase"])
            return {"state": "waiting_for_provider_processing", "receipt": None}
        if status["state"] != "published":
            raise ContractValidationError("unhandled provider status state")
        if _parse_time(status["publishedAt"], "publishedAt") >= auth_expiry:
            self._set_state("failed_terminal", "provider_published_after_authorization_expiry")
            return {"state": "failed_terminal", "receipt": None}
        receipt = self._published_receipt(status)
        self._append("receipt_committed", receipt)
        self._set_state("published", "validated_terminal_provider_receipt")
        return {"state": "published", "receipt": receipt}


@dataclass
class MockPublishProvider:
    platform: str
    source_class: str = "synthetic_fixture"
    credentials_available: bool = True
    blocked_accounts: set[str] = field(default_factory=set)
    polls_before_publish: int = 1
    crash_after_effect_once: bool = False
    recovery_unknown_once: bool = False
    runtime_secret: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.platform not in PLATFORMS:
            raise ValueError("unsupported mock platform")
        self._operations: dict[str, dict[str, Any]] = {}
        self.prepare_calls = 0
        self.recover_calls = 0
        self.submit_calls = 0
        self.status_calls = 0
        self.accepted_effects = 0

    def prepare(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.prepare_calls += 1
        supported = (
            request["platform"] == self.platform
            and request["accountId"] not in self.blocked_accounts
            and request["media"]["contentType"] == "video/mp4"
            and request["media"]["aspectRatio"] == "9:16"
            and 15 <= float(request["media"]["durationSeconds"]) <= 60
        )
        capability = {
            "supported": supported,
            "reason": "supported" if supported else "unsupported_account_or_media_combination",
            "idempotentSubmit": True,
            "authoritativeRecovery": True,
            "asyncProcessing": True,
            "phases": [
                "create_or_upload_session", "provider_processing",
                "publish_commit", "terminal_receipt",
            ],
        }
        prepared = {
            "contractVersion": PUBLISH_PREPARE_VERSION,
            "platform": self.platform,
            "accountId": request["accountId"],
            "destination": request["destination"],
            "credentialRef": request["credentialRef"],
            "credentialsAvailable": self.credentials_available,
            "capability": capability,
        }
        prepared["evidenceDigest"] = sha256_json(prepared)
        return prepared

    def _status(self, request: Mapping[str, Any], operation: Mapping[str, Any] | None) -> dict[str, Any]:
        if operation is None:
            status = {
                "contractVersion": PUBLISH_STATUS_VERSION,
                "platform": self.platform,
                "idempotencyKey": request["idempotencyKey"],
                "state": "absent",
                "phase": "none",
                "authoritative": True,
                "operationRef": None,
                "postId": None,
                "publishedAt": None,
                "capturedAt": "2026-10-01T00:00:01Z",
                "sourceClass": self.source_class,
            }
        else:
            status = {
                "contractVersion": PUBLISH_STATUS_VERSION,
                "platform": self.platform,
                "idempotencyKey": request["idempotencyKey"],
                "state": operation["state"],
                "phase": operation["phase"],
                "authoritative": True,
                "operationRef": operation["operationRef"],
                "postId": operation.get("postId"),
                "publishedAt": operation.get("publishedAt"),
                "capturedAt": operation["capturedAt"],
                "sourceClass": self.source_class,
            }
        status["statusDigest"] = sha256_json(status)
        return status

    def recover(self, idempotency_key: str) -> Mapping[str, Any]:
        self.recover_calls += 1
        request = next(
            (item["request"] for item in self._operations.values() if item["request"]["idempotencyKey"] == idempotency_key),
            None,
        )
        if self.recovery_unknown_once:
            self.recovery_unknown_once = False
            if request is None:
                request = {
                    "idempotencyKey": idempotency_key,
                }
            status = {
                "contractVersion": PUBLISH_STATUS_VERSION,
                "platform": self.platform,
                "idempotencyKey": idempotency_key,
                "state": "unknown",
                "phase": "recovery",
                "authoritative": False,
                "operationRef": None,
                "postId": None,
                "publishedAt": None,
                "capturedAt": "2026-10-01T00:00:01Z",
                "sourceClass": self.source_class,
            }
            status["statusDigest"] = sha256_json(status)
            return status
        if request is None:
            status = {
                "contractVersion": PUBLISH_STATUS_VERSION,
                "platform": self.platform,
                "idempotencyKey": idempotency_key,
                "state": "absent",
                "phase": "none",
                "authoritative": True,
                "operationRef": None,
                "postId": None,
                "publishedAt": None,
                "capturedAt": "2026-10-01T00:00:01Z",
                "sourceClass": self.source_class,
            }
            status["statusDigest"] = sha256_json(status)
            return status
        operation = next(item for item in self._operations.values() if item["request"]["idempotencyKey"] == idempotency_key)
        return self._status(request, operation)

    def submit(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.submit_calls += 1
        key = request["idempotencyKey"]
        existing = next(
            (item for item in self._operations.values() if item["request"]["idempotencyKey"] == key),
            None,
        )
        if existing is not None:
            return self._status(request, existing)
        self.accepted_effects += 1
        operation_ref = f"{self.platform}:op:{sha256_json({'key': key})[:16]}"
        operation = {
            "request": json.loads(canonical_json(request)),
            "operationRef": operation_ref,
            "state": "processing",
            "phase": "provider_processing",
            "polls": 0,
            "capturedAt": "2026-10-01T00:00:02Z",
        }
        self._operations[operation_ref] = operation
        if self.crash_after_effect_once:
            self.crash_after_effect_once = False
            raise InjectedCrash("after_provider_side_effect_before_local_ack")
        return self._status(request, operation)

    def status(self, operation_ref: str) -> Mapping[str, Any]:
        self.status_calls += 1
        operation = self._operations[operation_ref]
        operation["polls"] += 1
        if operation["state"] == "processing" and operation["polls"] >= self.polls_before_publish:
            operation["state"] = "published"
            operation["phase"] = "terminal_receipt"
            operation["postId"] = f"{self.platform}-post-{sha256_json({'op': operation_ref})[:12]}"
            operation["publishedAt"] = "2026-10-01T00:00:03Z"
            operation["capturedAt"] = "2026-10-01T00:00:04Z"
        return self._status(operation["request"], operation)


class InstagramReelsMockProvider(MockPublishProvider):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(platform="instagram_reels", **kwargs)


class TikTokMockProvider(MockPublishProvider):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(platform="tiktok", **kwargs)


class YouTubeShortsMockProvider(MockPublishProvider):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(platform="youtube_shorts", **kwargs)
