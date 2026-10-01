from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from . import autonomous_reels as reels
from . import publish_providers as r12

EXECUTION_VERSION = "creator.publish_execution.r21.v1"
OPERATION_JOURNAL_VERSION = "creator.publish_operation_journal.r21.v1"
PREFLIGHT_VERSION = "creator.publish_preflight.r21.v1"
SANDBOX_REPORT_VERSION = "creator.publish_sandbox_run.r21.v1"

REQUIRED_SCOPES = {
    "instagram_reels": frozenset({"instagram_business_content_publish"}),
    "tiktok": frozenset({"video.publish"}),
    "youtube_shorts": frozenset(
        {"https://www.googleapis.com/auth/youtube.upload"}
    ),
}


class PublishExecutionError(RuntimeError):
    pass


class ProviderTimeout(PublishExecutionError):
    pass


class ProviderRateLimited(PublishExecutionError):
    pass


class ProviderRejected(PublishExecutionError):
    pass


@dataclass(frozen=True)
class CredentialMaterial:
    access_token: str = field(repr=False)
    subject_id: str
    scopes: tuple[str, ...]
    expires_at: str
    revoked: bool = False
    interactive_required: bool = False

    def public_identity(self) -> dict[str, Any]:
        value = {
            "subjectId": self.subject_id,
            "scopes": sorted(set(self.scopes)),
            "expiresAt": self.expires_at,
            "revoked": self.revoked,
            "interactiveRequired": self.interactive_required,
        }
        value["identityDigest"] = reels.sha256_json(value)
        return value


class CredentialResolver(Protocol):
    def resolve(self, credential_ref: str) -> CredentialMaterial | None:
        ...


class EnvCredentialResolver:
    """Opaque ref -> secret environment value. Secrets never enter Creator state."""

    @staticmethod
    def variable_name(credential_ref: str) -> str:
        digest = hashlib.sha256(
            credential_ref.encode("utf-8")
        ).hexdigest()[:20]
        return "CREATOR_PUBLISH_SECRET_" + digest.upper()

    def resolve(self, credential_ref: str) -> CredentialMaterial | None:
        raw = os.environ.get(self.variable_name(credential_ref))
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderRejected(
                "credential environment payload is invalid"
            ) from exc
        required = {
            "access_token",
            "subject_id",
            "scopes",
            "expires_at",
            "revoked",
            "interactive_required",
        }
        if not isinstance(value, Mapping) or set(value) != required:
            raise ProviderRejected(
                "credential environment payload fields are invalid"
            )
        if not isinstance(value["access_token"], str) or not value["access_token"]:
            raise ProviderRejected("credential access token is empty")
        if not isinstance(value["scopes"], list) or not all(
            isinstance(item, str) and item for item in value["scopes"]
        ):
            raise ProviderRejected("credential scopes are invalid")
        return CredentialMaterial(
            access_token=value["access_token"],
            subject_id=str(value["subject_id"]),
            scopes=tuple(value["scopes"]),
            expires_at=str(value["expires_at"]),
            revoked=bool(value["revoked"]),
            interactive_required=bool(value["interactive_required"]),
        )


@dataclass(frozen=True)
class MediaAsset:
    path: Path
    sha256: str
    size_bytes: int
    duration_seconds: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str | None
    public_url: str | None = None


class MediaResolver(Protocol):
    def resolve(self, request: Mapping[str, Any]) -> MediaAsset:
        ...


def _rate(value: str) -> float:
    if "/" not in value:
        return float(value)
    left, right = value.split("/", 1)
    denominator = float(right)
    return 0.0 if denominator == 0 else float(left) / denominator


def probe_media(path: Path, *, public_url: str | None = None) -> MediaAsset:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ProviderRejected("media file does not exist")
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries",
                "stream=codec_type,codec_name,width,height,r_frame_rate:"
                "format=duration",
                "-of", "json",
                str(path),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProviderRejected("ffprobe unavailable or timed out") from exc
    if result.returncode != 0:
        raise ProviderRejected("ffprobe rejected media")
    try:
        value = json.loads(result.stdout)
        video = next(
            item for item in value["streams"]
            if item["codec_type"] == "video"
        )
        audio = next(
            (
                item for item in value["streams"]
                if item["codec_type"] == "audio"
            ),
            None,
        )
        duration = float(value["format"]["duration"])
    except (KeyError, TypeError, ValueError, StopIteration) as exc:
        raise ProviderRejected("media probe is incomplete") from exc
    return MediaAsset(
        path=path,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        size_bytes=path.stat().st_size,
        duration_seconds=duration,
        width=int(video["width"]),
        height=int(video["height"]),
        fps=_rate(str(video["r_frame_rate"])),
        video_codec=str(video["codec_name"]),
        audio_codec=None if audio is None else str(audio["codec_name"]),
        public_url=public_url,
    )


@dataclass
class FilesystemMediaResolver:
    path: Path
    public_url: str | None = None

    def resolve(self, request: Mapping[str, Any]) -> MediaAsset:
        asset = probe_media(self.path, public_url=self.public_url)
        media = request["media"]
        if asset.sha256 != media["contentSha256"]:
            raise ProviderRejected(
                "local media SHA does not match publish request"
            )
        if asset.size_bytes != media["sizeBytes"]:
            raise ProviderRejected(
                "local media size does not match publish request"
            )
        if abs(asset.duration_seconds - float(media["durationSeconds"])) > 0.25:
            raise ProviderRejected(
                "local media duration does not match publish request"
            )
        return asset


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    json_body: Mapping[str, Any] | None = None
    body: bytes = b""


class HttpTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        json_body: Mapping[str, Any] | None = None,
        body: bytes | None = None,
        timeout_seconds: float,
    ) -> HttpResponse:
        ...


class UrllibHttpTransport:
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        json_body: Mapping[str, Any] | None = None,
        body: bytes | None = None,
        timeout_seconds: float,
    ) -> HttpResponse:
        payload = body
        request_headers = dict(headers)
        if json_body is not None:
            payload = json.dumps(
                json_body,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url,
            data=payload,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout_seconds,
            ) as response:
                raw = response.read()
                parsed = None
                if raw:
                    try:
                        candidate = json.loads(raw)
                        if isinstance(candidate, Mapping):
                            parsed = candidate
                    except json.JSONDecodeError:
                        pass
                return HttpResponse(
                    status=int(response.status),
                    headers=dict(response.headers.items()),
                    json_body=parsed,
                    body=raw,
                )
        except urllib.error.HTTPError as exc:
            raw = exc.read() if hasattr(exc, "read") else b""
            parsed = None
            try:
                candidate = json.loads(raw)
                if isinstance(candidate, Mapping):
                    parsed = candidate
            except Exception:
                pass
            return HttpResponse(
                status=int(exc.code),
                headers=dict(exc.headers.items()) if exc.headers else {},
                json_body=parsed,
                body=raw,
            )
        except (TimeoutError, urllib.error.URLError) as exc:
            raise ProviderTimeout("provider transport timed out") from exc


@dataclass(frozen=True)
class RuntimeConfig:
    timeout_seconds: float = 30.0
    retry_attempts: int = 3
    initial_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 16.0
    instagram_graph_version: str = ""
    instagram_base_url: str = "https://graph.instagram.com"
    tiktok_base_url: str = "https://open.tiktokapis.com"
    youtube_base_url: str = "https://www.googleapis.com"

    def validate(self) -> "RuntimeConfig":
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not 1 <= self.retry_attempts <= 8:
            raise ValueError("retry_attempts must be 1-8")
        if self.initial_backoff_seconds <= 0 or self.max_backoff_seconds <= 0:
            raise ValueError("backoff values must be positive")
        return self


class OperationJournal:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.events: list[dict[str, Any]] = []
        if self.path.exists():
            self._load()

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
                raise r12.ContractValidationError(
                    f"invalid operation journal line {line_number}"
                ) from exc
            if set(event) != {
                "journalVersion",
                "sequence",
                "eventType",
                "idempotencyKey",
                "payload",
                "eventDigest",
            }:
                raise r12.ContractValidationError(
                    "operation journal event fields must match exactly"
                )
            if event["journalVersion"] != OPERATION_JOURNAL_VERSION:
                raise r12.ContractValidationError(
                    "operation journal version mismatch"
                )
            if event["sequence"] != len(self.events) + 1:
                raise r12.ContractValidationError(
                    "operation journal sequence mismatch"
                )
            material = dict(event)
            digest = material.pop("eventDigest")
            if reels.sha256_json(material) != digest:
                raise r12.ContractValidationError(
                    "operation journal digest mismatch"
                )
            reels._reject_secrets(event["payload"])
            self.events.append(event)

    def append(
        self,
        event_type: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> None:
        reels._reject_secrets(payload)
        event = {
            "journalVersion": OPERATION_JOURNAL_VERSION,
            "sequence": len(self.events) + 1,
            "eventType": event_type,
            "idempotencyKey": key,
            "payload": json.loads(reels.canonical_json(payload)),
        }
        event["eventDigest"] = reels.sha256_json(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(reels.canonical_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.events.append(event)

    def for_key(self, key: str) -> list[dict[str, Any]]:
        return [item for item in self.events if item["idempotencyKey"] == key]

    def bind_request(self, request: Mapping[str, Any]) -> None:
        key = request["idempotencyKey"]
        existing = next(
            (
                item["payload"]["request"]
                for item in self.for_key(key)
                if item["eventType"] == "request_bound"
            ),
            None,
        )
        if existing is None:
            self.append("request_bound", key, {"request": request})
        elif existing != request:
            raise r12.PublishGateError(
                "idempotency key already bound to a different request"
            )

    def request(self, key: str) -> dict[str, Any] | None:
        return next(
            (
                json.loads(reels.canonical_json(item["payload"]["request"]))
                for item in self.for_key(key)
                if item["eventType"] == "request_bound"
            ),
            None,
        )

    def latest(self, key: str, event_type: str) -> dict[str, Any] | None:
        values = [
            item["payload"]
            for item in self.for_key(key)
            if item["eventType"] == event_type
        ]
        return None if not values else json.loads(
            reels.canonical_json(values[-1])
        )

    def unresolved_intent(self, key: str) -> bool:
        events = self.for_key(key)
        latest_intent = next(
            (
                item for item in reversed(events)
                if item["eventType"] in {
                    "side_effect_intent",
                    "publish_commit_intent",
                }
            ),
            None,
        )
        if latest_intent is None:
            return False
        return not any(
            item["sequence"] > latest_intent["sequence"]
            and item["eventType"] in {
                "provider_ref",
                "terminal_status",
                "side_effect_rejected",
            }
            for item in events
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _r12_status(
    *,
    platform: str,
    key: str,
    state: str,
    phase: str,
    authoritative: bool,
    operation_ref: str | None,
    post_id: str | None,
    published_at: str | None,
    captured_at: str,
    source_class: str = "provider_receipt",
) -> dict[str, Any]:
    value = {
        "contractVersion": r12.PUBLISH_STATUS_VERSION,
        "platform": platform,
        "idempotencyKey": key,
        "state": state,
        "phase": phase,
        "authoritative": authoritative,
        "operationRef": operation_ref,
        "postId": post_id,
        "publishedAt": published_at,
        "capturedAt": captured_at,
        "sourceClass": source_class,
    }
    value["statusDigest"] = reels.sha256_json(value)
    return value


class ProductionPublishProvider:
    platform: str
    source_class = "provider_receipt"

    def __init__(
        self,
        *,
        credential_resolver: CredentialResolver,
        media_resolver: MediaResolver,
        transport: HttpTransport,
        journal_path: Path,
        config: RuntimeConfig | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], str] = _utc_now,
    ) -> None:
        self.credential_resolver = credential_resolver
        self.media_resolver = media_resolver
        self.transport = transport
        self.journal = OperationJournal(journal_path)
        self.config = (config or RuntimeConfig()).validate()
        self.sleep_fn = sleep_fn
        self.now_fn = now_fn
        self._credential: CredentialMaterial | None = None
        self._media: MediaAsset | None = None

    def _credential_state(
        self,
        request: Mapping[str, Any],
    ) -> tuple[CredentialMaterial | None, str]:
        credential = self.credential_resolver.resolve(
            request["credentialRef"]
        )
        if credential is None:
            return None, "credential_reference_unresolved"
        if credential.revoked:
            return None, "credential_revoked"
        try:
            if reels._parse_time(
                credential.expires_at,
                "credential.expiresAt",
            ) <= reels._parse_time(self.now_fn(), "now"):
                return None, "credential_expired"
        except Exception:
            return None, "credential_expired"
        if credential.interactive_required:
            return None, "interactive_authorization_required"
        missing = REQUIRED_SCOPES[self.platform] - set(credential.scopes)
        if missing:
            return None, "interactive_authorization_required"
        if (
            credential.subject_id
            and credential.subject_id != request["accountId"]
        ):
            return None, "credential_account_binding_mismatch"
        return credential, "authorized"

    def _auth_headers(self, credential: CredentialMaterial) -> dict[str, str]:
        return {"Authorization": "Bearer " + credential.access_token}

    def _backoff_seconds(
        self,
        response: HttpResponse,
        attempt: int,
    ) -> float:
        retry_after = next(
            (
                value
                for key, value in response.headers.items()
                if key.lower() == "retry-after"
            ),
            None,
        )
        try:
            if retry_after is not None:
                return min(
                    self.config.max_backoff_seconds,
                    max(0.0, float(retry_after)),
                )
        except ValueError:
            pass
        return min(
            self.config.max_backoff_seconds,
            self.config.initial_backoff_seconds * (2 ** attempt),
        )

    def _request(
        self,
        *,
        method: str,
        url: str,
        credential: CredentialMaterial | None,
        json_body: Mapping[str, Any] | None = None,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        safe_retry: bool,
    ) -> HttpResponse:
        combined = dict(headers or {})
        if credential is not None:
            combined.update(self._auth_headers(credential))
        for attempt in range(self.config.retry_attempts):
            try:
                response = self.transport.request(
                    method=method,
                    url=url,
                    headers=combined,
                    json_body=json_body,
                    body=body,
                    timeout_seconds=self.config.timeout_seconds,
                )
            except ProviderTimeout:
                if safe_retry and attempt + 1 < self.config.retry_attempts:
                    self.sleep_fn(
                        min(
                            self.config.max_backoff_seconds,
                            self.config.initial_backoff_seconds
                            * (2 ** attempt),
                        )
                    )
                    continue
                raise
            if 200 <= response.status < 300 or response.status == 308:
                return response
            if response.status == 429:
                if attempt + 1 >= self.config.retry_attempts:
                    raise ProviderRateLimited(
                        "provider rate limit persisted after bounded retries"
                    )
                self.sleep_fn(self._backoff_seconds(response, attempt))
                continue
            if response.status == 401:
                raise ProviderRejected("credential_expired_or_invalid")
            if response.status == 403:
                raise ProviderRejected("provider_permission_or_policy_rejected")
            if 500 <= response.status < 600 and safe_retry:
                if attempt + 1 >= self.config.retry_attempts:
                    raise ProviderTimeout(
                        "provider server error persisted after bounded retries"
                    )
                self.sleep_fn(self._backoff_seconds(response, attempt))
                continue
            if 500 <= response.status < 600:
                raise ProviderTimeout(
                    "provider side-effect acknowledgement is ambiguous"
                )
            raise ProviderRejected(
                f"provider rejected request with HTTP {response.status}"
            )
        raise ProviderTimeout("bounded provider request exhausted")

    def _common_media_preflight(
        self,
        request: Mapping[str, Any],
        asset: MediaAsset,
    ) -> str | None:
        media = request["media"]
        if media["contentType"] != "video/mp4":
            return "media_must_be_mp4"
        if media["aspectRatio"] != "9:16":
            return "media_must_be_9_16"
        if not 15 <= float(media["durationSeconds"]) <= 60:
            return "media_duration_outside_creator_profile"
        if asset.width * 16 != asset.height * 9:
            return "probed_media_not_exact_9_16"
        if asset.video_codec not in {"h264", "hevc", "h265"}:
            return "unsupported_video_codec"
        return None

    def _platform_preflight(
        self,
        request: Mapping[str, Any],
        credential: CredentialMaterial,
        asset: MediaAsset,
    ) -> tuple[bool, str]:
        raise NotImplementedError

    def prepare(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        request = r12.validate_publish_request(
            request,
            allow_synthetic_fixture=False,
        )
        self.journal.bind_request(request)
        credential, reason = self._credential_state(request)
        supported = False
        asset = None
        if credential is not None:
            try:
                asset = self.media_resolver.resolve(request)
                common = self._common_media_preflight(request, asset)
                if common is not None:
                    reason = common
                else:
                    supported, reason = self._platform_preflight(
                        request,
                        credential,
                        asset,
                    )
            except ProviderRejected as exc:
                if str(exc) in {
                    "credential_expired_or_invalid",
                    "provider_permission_or_policy_rejected",
                }:
                    credential = None
                    reason = "interactive_authorization_required"
                else:
                    reason = "provider_preflight_rejected"
                supported = False
            except ProviderRateLimited:
                reason = "provider_preflight_rate_limited"
                supported = False
            except ProviderTimeout:
                reason = "provider_preflight_timeout"
                supported = False
        self._credential = credential
        self._media = asset
        capability = {
            "supported": supported,
            "reason": reason,
            "idempotentSubmit": True,
            "authoritativeRecovery": True,
            "asyncProcessing": True,
            "phases": [
                "create_or_upload_session",
                "provider_processing",
                "publish_commit",
                "terminal_receipt",
            ],
        }
        prepared = {
            "contractVersion": r12.PUBLISH_PREPARE_VERSION,
            "platform": self.platform,
            "accountId": request["accountId"],
            "destination": request["destination"],
            "credentialRef": request["credentialRef"],
            "credentialsAvailable": credential is not None,
            "capability": capability,
        }
        prepared["evidenceDigest"] = reels.sha256_json(prepared)
        self.journal.append(
            "preflight",
            request["idempotencyKey"],
            {
                "preflightVersion": PREFLIGHT_VERSION,
                "credentialsAvailable": credential is not None,
                "capability": capability,
                "credentialIdentity": (
                    None
                    if credential is None
                    else credential.public_identity()
                ),
                "media": (
                    None
                    if asset is None
                    else {
                        "sha256": asset.sha256,
                        "sizeBytes": asset.size_bytes,
                        "durationSeconds": round(
                            asset.duration_seconds, 6
                        ),
                        "width": asset.width,
                        "height": asset.height,
                        "fps": round(asset.fps, 6),
                        "videoCodec": asset.video_codec,
                        "audioCodec": asset.audio_codec,
                        "publicUrlConfigured": bool(asset.public_url),
                    }
                ),
            },
        )
        return prepared

    def _bound(
        self,
        key: str,
    ) -> tuple[dict[str, Any], CredentialMaterial, MediaAsset]:
        request = self.journal.request(key)
        if request is None:
            raise ProviderRejected("provider operation has no bound request")
        credential, reason = self._credential_state(request)
        if credential is None:
            raise ProviderRejected(reason)
        asset = self.media_resolver.resolve(request)
        return request, credential, asset

    def _terminal(self, key: str) -> dict[str, Any] | None:
        value = self.journal.latest(key, "terminal_status")
        return None if value is None else value["status"]

    def _unknown(self, key: str, phase: str) -> dict[str, Any]:
        return _r12_status(
            platform=self.platform,
            key=key,
            state="unknown",
            phase=phase,
            authoritative=False,
            operation_ref=None,
            post_id=None,
            published_at=None,
            captured_at=self.now_fn(),
        )

    def recover(self, idempotency_key: str) -> Mapping[str, Any]:
        terminal = self._terminal(idempotency_key)
        if terminal is not None:
            return terminal
        request = self.journal.request(idempotency_key)
        if request is None:
            return _r12_status(
                platform=self.platform,
                key=idempotency_key,
                state="absent",
                phase="none",
                authoritative=True,
                operation_ref=None,
                post_id=None,
                published_at=None,
                captured_at=self.now_fn(),
            )
        ref = self.journal.latest(idempotency_key, "provider_ref")
        if ref is None:
            if self.journal.unresolved_intent(idempotency_key):
                return self._unknown(
                    idempotency_key,
                    "unresolved_side_effect_acknowledgement",
                )
            return _r12_status(
                platform=self.platform,
                key=idempotency_key,
                state="absent",
                phase="none",
                authoritative=True,
                operation_ref=None,
                post_id=None,
                published_at=None,
                captured_at=self.now_fn(),
            )
        return self.status(ref["operationRef"])

    def submit(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        request = r12.validate_publish_request(
            request,
            allow_synthetic_fixture=False,
        )
        self.journal.bind_request(request)
        terminal = self._terminal(request["idempotencyKey"])
        if terminal is not None:
            return terminal
        if self.journal.unresolved_intent(request["idempotencyKey"]):
            raise reels.PublishOutcomeUnknown(
                "unresolved provider side-effect acknowledgement"
            )
        ref = self.journal.latest(
            request["idempotencyKey"],
            "provider_ref",
        )
        if ref is not None:
            return self.status(ref["operationRef"])
        try:
            return self._submit_new(request)
        except ProviderRateLimited:
            self.journal.append(
                "side_effect_rejected",
                request["idempotencyKey"],
                {"phase": "side_effect", "reason": "rate_limited"},
            )
            return self._unknown(
                request["idempotencyKey"],
                "rate_limited_backoff_exhausted",
            )
        except ProviderRejected:
            self.journal.append(
                "side_effect_rejected",
                request["idempotencyKey"],
                {"phase": "side_effect", "reason": "provider_rejected"},
            )
            raise
        except ProviderTimeout as exc:
            raise reels.PublishOutcomeUnknown(
                "provider effect acknowledgement is unknown"
            ) from exc

    def _submit_new(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        raise NotImplementedError

    def status(self, operation_ref: str) -> Mapping[str, Any]:
        raise NotImplementedError

    def _commit_terminal(
        self,
        *,
        key: str,
        operation_ref: str,
        post_id: str,
        post_url: str | None,
        published_at: str | None = None,
    ) -> dict[str, Any]:
        status = _r12_status(
            platform=self.platform,
            key=key,
            state="published",
            phase="terminal_receipt",
            authoritative=True,
            operation_ref=operation_ref,
            post_id=post_id,
            published_at=published_at or self.now_fn(),
            captured_at=self.now_fn(),
        )
        self.journal.append(
            "terminal_status",
            key,
            {
                "status": status,
                "postUrl": post_url,
            },
        )
        return status


class InstagramReelsProvider(ProductionPublishProvider):
    platform = "instagram_reels"

    def _base(self) -> str:
        if not self.config.instagram_graph_version:
            raise ProviderRejected(
                "instagram_graph_api_version_not_configured"
            )
        return (
            self.config.instagram_base_url.rstrip("/")
            + "/"
            + self.config.instagram_graph_version
        )

    def _platform_preflight(
        self,
        request: Mapping[str, Any],
        credential: CredentialMaterial,
        asset: MediaAsset,
    ) -> tuple[bool, str]:
        if request["destination"] != "profile:" + request["accountId"]:
            return False, "instagram_destination_account_mismatch"
        if not asset.public_url or not asset.public_url.startswith("https://"):
            return False, "instagram_requires_public_https_video_url"
        if asset.size_bytes > 1024 * 1024 * 1024:
            return False, "instagram_reel_exceeds_1gb"
        if not 23 <= asset.fps <= 60:
            return False, "instagram_frame_rate_out_of_range"
        if asset.width > 1920:
            return False, "instagram_width_exceeds_1920"
        if asset.audio_codec not in {None, "aac"}:
            return False, "instagram_audio_codec_must_be_aac"
        response = self._request(
            method="GET",
            url=(
                self._base()
                + "/"
                + urllib.parse.quote(request["accountId"])
                + "?fields=id,username"
            ),
            credential=credential,
            safe_retry=True,
        )
        data = response.json_body or {}
        if str(data.get("id", "")) != request["accountId"]:
            return False, "instagram_account_preflight_mismatch"
        return True, "supported"

    def _submit_new(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        request, credential, asset = self._bound(
            request["idempotencyKey"]
        )
        key = request["idempotencyKey"]
        self.journal.append(
            "side_effect_intent",
            key,
            {
                "phase": "create_or_upload_session",
                "requestDigest": reels.sha256_json(request),
            },
        )
        params = urllib.parse.urlencode(
            {
                "media_type": "REELS",
                "video_url": asset.public_url or "",
                "caption": request["caption"],
                "share_to_feed": "false",
            }
        )
        try:
            response = self._request(
                method="POST",
                url=(
                    self._base()
                    + "/"
                    + urllib.parse.quote(request["accountId"])
                    + "/media?"
                    + params
                ),
                credential=credential,
                safe_retry=False,
            )
        except ProviderRateLimited:
            self.journal.append(
                "side_effect_rejected",
                key,
                {"phase": "create_or_upload_session", "reason": "rate_limited"},
            )
            raise
        data = response.json_body or {}
        container_id = str(data.get("id", ""))
        if not container_id:
            raise ProviderTimeout(
                "instagram container acknowledgement missing id"
            )
        operation_ref = "instagram:container:" + container_id
        self.journal.append(
            "provider_ref",
            key,
            {
                "operationRef": operation_ref,
                "phase": "provider_processing",
                "providerId": container_id,
            },
        )
        return _r12_status(
            platform=self.platform,
            key=key,
            state="processing",
            phase="provider_processing",
            authoritative=True,
            operation_ref=operation_ref,
            post_id=None,
            published_at=None,
            captured_at=self.now_fn(),
        )

    def status(self, operation_ref: str) -> Mapping[str, Any]:
        if not operation_ref.startswith("instagram:"):
            raise ProviderRejected("invalid Instagram operation reference")
        provider_id = operation_ref.rsplit(":", 1)[-1]
        key = self._key_for_ref(operation_ref)
        terminal = self._terminal(key)
        if terminal is not None:
            return terminal
        request, credential, _ = self._bound(key)
        try:
            response = self._request(
                method="GET",
                url=(
                    self._base()
                    + "/"
                    + urllib.parse.quote(provider_id)
                    + "?fields=status_code,status"
                ),
                credential=credential,
                safe_retry=True,
            )
        except (ProviderTimeout, ProviderRateLimited):
            return self._unknown(key, "provider_status_timeout")
        data = response.json_body or {}
        status_code = str(data.get("status_code", "")).upper()
        if status_code in {"ERROR", "EXPIRED"}:
            return _r12_status(
                platform=self.platform,
                key=key,
                state="failed_terminal",
                phase="provider_processing",
                authoritative=True,
                operation_ref=operation_ref,
                post_id=None,
                published_at=None,
                captured_at=self.now_fn(),
            )
        if status_code != "FINISHED":
            return _r12_status(
                platform=self.platform,
                key=key,
                state="processing",
                phase="provider_processing",
                authoritative=True,
                operation_ref=operation_ref,
                post_id=None,
                published_at=None,
                captured_at=self.now_fn(),
            )
        if self.journal.latest(key, "publish_commit_intent") is not None:
            published_ref = self.journal.latest(key, "published_ref")
            if published_ref is None:
                return self._unknown(
                    key,
                    "publish_commit_acknowledgement_unknown",
                )
            return self._commit_terminal(
                key=key,
                operation_ref=published_ref["operationRef"],
                post_id=published_ref["postId"],
                post_url=published_ref.get("postUrl"),
                published_at=published_ref["publishedAt"],
            )
        self.journal.append(
            "publish_commit_intent",
            key,
            {
                "phase": "publish_commit",
                "containerId": provider_id,
            },
        )
        try:
            response = self._request(
                method="POST",
                url=(
                    self._base()
                    + "/"
                    + urllib.parse.quote(request["accountId"])
                    + "/media_publish?"
                    + urllib.parse.urlencode({"creation_id": provider_id})
                ),
                credential=credential,
                safe_retry=False,
            )
        except ProviderRateLimited:
            self.journal.append(
                "side_effect_rejected",
                key,
                {"phase": "publish_commit", "reason": "rate_limited"},
            )
            raise
        except ProviderTimeout:
            return self._unknown(
                key,
                "publish_commit_acknowledgement_unknown",
            )
        post_id = str((response.json_body or {}).get("id", ""))
        if not post_id:
            return self._unknown(
                key,
                "publish_commit_acknowledgement_unknown",
            )
        published_at = self.now_fn()
        post_url = None
        try:
            permalink = self._request(
                method="GET",
                url=(
                    self._base()
                    + "/"
                    + urllib.parse.quote(post_id)
                    + "?fields=permalink"
                ),
                credential=credential,
                safe_retry=True,
            )
            post_url = str(
                (permalink.json_body or {}).get("permalink") or ""
            ) or None
        except PublishExecutionError:
            pass
        published_ref = {
            "operationRef": "instagram:media:" + post_id,
            "postId": post_id,
            "postUrl": post_url,
            "publishedAt": published_at,
        }
        self.journal.append("published_ref", key, published_ref)
        return self._commit_terminal(
            key=key,
            operation_ref=published_ref["operationRef"],
            post_id=post_id,
            post_url=post_url,
            published_at=published_at,
        )

    def _key_for_ref(self, operation_ref: str) -> str:
        for event in reversed(self.journal.events):
            if (
                event["eventType"] == "provider_ref"
                and event["payload"].get("operationRef") == operation_ref
            ):
                return event["idempotencyKey"]
        raise ProviderRejected("unknown Instagram operation reference")


class TikTokDirectPostProvider(ProductionPublishProvider):
    platform = "tiktok"

    def _endpoint(self, suffix: str) -> str:
        return self.config.tiktok_base_url.rstrip("/") + suffix

    def _platform_preflight(
        self,
        request: Mapping[str, Any],
        credential: CredentialMaterial,
        asset: MediaAsset,
    ) -> tuple[bool, str]:
        if not asset.public_url or not asset.public_url.startswith("https://"):
            return False, "tiktok_requires_verified_https_pull_url"
        if asset.size_bytes > 4 * 1024 * 1024 * 1024:
            return False, "tiktok_video_exceeds_4gb"
        if not 23 <= asset.fps <= 60:
            return False, "tiktok_frame_rate_out_of_range"
        if min(asset.width, asset.height) < 360 or max(
            asset.width, asset.height
        ) > 4096:
            return False, "tiktok_dimensions_out_of_range"
        response = self._request(
            method="POST",
            url=self._endpoint(
                "/v2/post/publish/creator_info/query/"
            ),
            credential=credential,
            json_body={},
            safe_retry=True,
        )
        data = (response.json_body or {}).get("data", {})
        if not isinstance(data, Mapping):
            return False, "tiktok_creator_info_invalid"
        max_duration = data.get("max_video_post_duration_sec")
        if isinstance(max_duration, (int, float)) and (
            float(request["media"]["durationSeconds"])
            > float(max_duration)
        ):
            return False, "tiktok_creator_duration_limit"
        if len(request["caption"].encode("utf-16-le")) // 2 > 2200:
            return False, "tiktok_caption_exceeds_2200_utf16_units"
        privacy = self._privacy(request)
        options = data.get("privacy_level_options")
        if (
            not isinstance(options, list)
            or privacy not in options
        ):
            return False, "tiktok_privacy_option_not_available"
        return True, "supported"

    @staticmethod
    def _privacy(request: Mapping[str, Any]) -> str:
        prefix = "privacy:"
        destination = request["destination"]
        if not destination.startswith(prefix):
            raise ProviderRejected(
                "TikTok destination must be privacy:<level>"
            )
        return destination[len(prefix):]

    def _submit_new(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        request, credential, asset = self._bound(
            request["idempotencyKey"]
        )
        key = request["idempotencyKey"]
        self.journal.append(
            "side_effect_intent",
            key,
            {
                "phase": "create_or_upload_session",
                "requestDigest": reels.sha256_json(request),
            },
        )
        payload = {
            "post_info": {
                "title": request["caption"],
                "privacy_level": self._privacy(request),
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": asset.public_url,
            },
        }
        try:
            response = self._request(
                method="POST",
                url=self._endpoint(
                    "/v2/post/publish/video/init/"
                ),
                credential=credential,
                json_body=payload,
                safe_retry=False,
            )
        except ProviderRateLimited:
            self.journal.append(
                "side_effect_rejected",
                key,
                {"phase": "create_or_upload_session", "reason": "rate_limited"},
            )
            raise
        data = (response.json_body or {}).get("data", {})
        publish_id = (
            str(data.get("publish_id", ""))
            if isinstance(data, Mapping)
            else ""
        )
        if not publish_id:
            raise ProviderTimeout(
                "TikTok init acknowledgement missing publish_id"
            )
        operation_ref = "tiktok:publish:" + publish_id
        self.journal.append(
            "provider_ref",
            key,
            {
                "operationRef": operation_ref,
                "phase": "provider_processing",
                "providerId": publish_id,
            },
        )
        return _r12_status(
            platform=self.platform,
            key=key,
            state="processing",
            phase="provider_processing",
            authoritative=True,
            operation_ref=operation_ref,
            post_id=None,
            published_at=None,
            captured_at=self.now_fn(),
        )

    def status(self, operation_ref: str) -> Mapping[str, Any]:
        if not operation_ref.startswith("tiktok:publish:"):
            raise ProviderRejected("invalid TikTok operation reference")
        key = self._key_for_ref(operation_ref)
        terminal = self._terminal(key)
        if terminal is not None:
            return terminal
        _, credential, _ = self._bound(key)
        publish_id = operation_ref[len("tiktok:publish:"):]
        try:
            response = self._request(
                method="POST",
                url=self._endpoint(
                    "/v2/post/publish/status/fetch/"
                ),
                credential=credential,
                json_body={"publish_id": publish_id},
                safe_retry=True,
            )
        except (ProviderTimeout, ProviderRateLimited):
            return self._unknown(key, "provider_status_timeout")
        data = (response.json_body or {}).get("data", {})
        if not isinstance(data, Mapping):
            return self._unknown(key, "provider_status_invalid")
        provider_state = str(data.get("status", ""))
        if provider_state == "FAILED":
            status = _r12_status(
                platform=self.platform,
                key=key,
                state="failed_terminal",
                phase="provider_processing",
                authoritative=True,
                operation_ref=operation_ref,
                post_id=None,
                published_at=None,
                captured_at=self.now_fn(),
            )
            self.journal.append("terminal_status", key, {
                "status": status,
                "postUrl": None,
            })
            return status
        if provider_state != "PUBLISH_COMPLETE":
            return _r12_status(
                platform=self.platform,
                key=key,
                state="processing",
                phase="provider_processing",
                authoritative=True,
                operation_ref=operation_ref,
                post_id=None,
                published_at=None,
                captured_at=self.now_fn(),
            )
        ids = data.get("publicaly_available_post_id")
        if not isinstance(ids, list) or not ids:
            ids = data.get("publicly_available_post_id")
        post_id = (
            str(ids[0])
            if isinstance(ids, list) and ids
            else publish_id
        )
        return self._commit_terminal(
            key=key,
            operation_ref=operation_ref,
            post_id=post_id,
            post_url=None,
        )

    def _key_for_ref(self, operation_ref: str) -> str:
        for event in reversed(self.journal.events):
            if (
                event["eventType"] == "provider_ref"
                and event["payload"].get("operationRef") == operation_ref
            ):
                return event["idempotencyKey"]
        raise ProviderRejected("unknown TikTok operation reference")


class YouTubeShortsProvider(ProductionPublishProvider):
    platform = "youtube_shorts"

    def _platform_preflight(
        self,
        request: Mapping[str, Any],
        credential: CredentialMaterial,
        asset: MediaAsset,
    ) -> tuple[bool, str]:
        if asset.size_bytes > 256 * 1024 * 1024 * 1024:
            return False, "youtube_video_exceeds_256gb"
        response = self._request(
            method="GET",
            url=(
                self.config.youtube_base_url.rstrip("/")
                + "/youtube/v3/channels?"
                + urllib.parse.urlencode(
                    {"part": "id", "mine": "true"}
                )
            ),
            credential=credential,
            safe_retry=True,
        )
        items = (response.json_body or {}).get("items")
        if not isinstance(items, list) or not items:
            return False, "youtube_authorized_channel_not_found"
        channel_id = str(items[0].get("id", ""))
        if channel_id != request["accountId"]:
            return False, "youtube_channel_binding_mismatch"
        return True, "supported"

    @staticmethod
    def _privacy(request: Mapping[str, Any]) -> str:
        destination = request["destination"]
        if not destination.startswith("privacy:"):
            raise ProviderRejected(
                "YouTube destination must be privacy:<status>"
            )
        privacy = destination[len("privacy:"):]
        if privacy not in {"public", "private", "unlisted"}:
            raise ProviderRejected("unsupported YouTube privacy status")
        return privacy

    def _submit_new(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        request, credential, asset = self._bound(
            request["idempotencyKey"]
        )
        key = request["idempotencyKey"]
        self.journal.append(
            "side_effect_intent",
            key,
            {
                "phase": "create_or_upload_session",
                "requestDigest": reels.sha256_json(request),
            },
        )
        response = self._request(
            method="POST",
            url=(
                self.config.youtube_base_url.rstrip("/")
                + "/upload/youtube/v3/videos?"
                + urllib.parse.urlencode(
                    {
                        "uploadType": "resumable",
                        "part": "snippet,status",
                    }
                )
            ),
            credential=credential,
            json_body={
                "snippet": {
                    "title": request["caption"][:100] or "Short",
                    "description": (
                        request["caption"]
                        + ("\n\n" + request["cta"] if request["cta"] else "")
                    )[:5000],
                },
                "status": {
                    "privacyStatus": self._privacy(request),
                },
            },
            headers={
                "X-Upload-Content-Length": str(asset.size_bytes),
                "X-Upload-Content-Type": "video/mp4",
            },
            safe_retry=False,
        )
        resume_url = next(
            (
                value
                for name, value in response.headers.items()
                if name.lower() == "location"
            ),
            None,
        )
        if not resume_url:
            raise ProviderTimeout(
                "YouTube resumable session acknowledgement missing Location"
            )
        operation_ref = (
            "youtube:session:"
            + hashlib.sha256(resume_url.encode("utf-8")).hexdigest()[:20]
        )
        self.journal.append(
            "provider_ref",
            key,
            {
                "operationRef": operation_ref,
                "phase": "provider_processing",
                "resumeEndpoint": resume_url,
            },
        )
        return self._upload_or_probe(
            key=key,
            operation_ref=operation_ref,
            credential=credential,
            asset=asset,
            resume_url=resume_url,
        )

    def _upload_or_probe(
        self,
        *,
        key: str,
        operation_ref: str,
        credential: CredentialMaterial,
        asset: MediaAsset,
        resume_url: str,
    ) -> dict[str, Any]:
        self.journal.append(
            "upload_attempt",
            key,
            {
                "operationRef": operation_ref,
                "sizeBytes": asset.size_bytes,
                "mediaSha256": asset.sha256,
            },
        )
        try:
            response = self._request(
                method="PUT",
                url=resume_url,
                credential=credential,
                body=asset.path.read_bytes(),
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(asset.size_bytes),
                    "Content-Range": (
                        f"bytes 0-{asset.size_bytes - 1}/{asset.size_bytes}"
                    ),
                },
                safe_retry=False,
            )
        except ProviderTimeout:
            return self._unknown(key, "upload_acknowledgement_unknown")
        if response.status == 308:
            return _r12_status(
                platform=self.platform,
                key=key,
                state="processing",
                phase="provider_processing",
                authoritative=True,
                operation_ref=operation_ref,
                post_id=None,
                published_at=None,
                captured_at=self.now_fn(),
            )
        video_id = str((response.json_body or {}).get("id", ""))
        if not video_id:
            return self._unknown(key, "upload_acknowledgement_unknown")
        video_ref = "youtube:video:" + video_id
        self.journal.append(
            "provider_ref",
            key,
            {
                "operationRef": video_ref,
                "phase": "provider_processing",
                "providerId": video_id,
            },
        )
        return _r12_status(
            platform=self.platform,
            key=key,
            state="processing",
            phase="provider_processing",
            authoritative=True,
            operation_ref=video_ref,
            post_id=None,
            published_at=None,
            captured_at=self.now_fn(),
        )

    def status(self, operation_ref: str) -> Mapping[str, Any]:
        key, ref = self._lookup_ref(operation_ref)
        terminal = self._terminal(key)
        if terminal is not None:
            return terminal
        _, credential, asset = self._bound(key)
        if operation_ref.startswith("youtube:session:"):
            resume_url = ref.get("resumeEndpoint")
            if not isinstance(resume_url, str) or not resume_url:
                return self._unknown(key, "resume_endpoint_unavailable")
            try:
                response = self._request(
                    method="PUT",
                    url=resume_url,
                    credential=credential,
                    body=b"",
                    headers={
                        "Content-Length": "0",
                        "Content-Range": f"bytes */{asset.size_bytes}",
                    },
                    safe_retry=True,
                )
            except PublishExecutionError:
                return self._unknown(key, "resumable_status_unknown")
            if response.status == 308:
                return _r12_status(
                    platform=self.platform,
                    key=key,
                    state="processing",
                    phase="provider_processing",
                    authoritative=True,
                    operation_ref=operation_ref,
                    post_id=None,
                    published_at=None,
                    captured_at=self.now_fn(),
                )
            video_id = str((response.json_body or {}).get("id", ""))
            if not video_id:
                return self._unknown(key, "resumable_status_unknown")
            operation_ref = "youtube:video:" + video_id
            self.journal.append(
                "provider_ref",
                key,
                {
                    "operationRef": operation_ref,
                    "phase": "provider_processing",
                    "providerId": video_id,
                },
            )
        video_id = operation_ref[len("youtube:video:"):]
        try:
            response = self._request(
                method="GET",
                url=(
                    self.config.youtube_base_url.rstrip("/")
                    + "/youtube/v3/videos?"
                    + urllib.parse.urlencode(
                        {
                            "part": "status,processingDetails",
                            "id": video_id,
                        }
                    )
                ),
                credential=credential,
                safe_retry=True,
            )
        except PublishExecutionError:
            return self._unknown(key, "provider_status_timeout")
        items = (response.json_body or {}).get("items")
        if not isinstance(items, list) or not items:
            return self._unknown(key, "youtube_video_status_missing")
        item = items[0]
        processing = (
            item.get("processingDetails", {})
            if isinstance(item, Mapping)
            else {}
        )
        upload_status = str(processing.get("processingStatus", ""))
        if upload_status == "failed":
            status = _r12_status(
                platform=self.platform,
                key=key,
                state="failed_terminal",
                phase="provider_processing",
                authoritative=True,
                operation_ref=operation_ref,
                post_id=None,
                published_at=None,
                captured_at=self.now_fn(),
            )
            self.journal.append(
                "terminal_status",
                key,
                {"status": status, "postUrl": None},
            )
            return status
        if upload_status not in {"succeeded", "processed"}:
            return _r12_status(
                platform=self.platform,
                key=key,
                state="processing",
                phase="provider_processing",
                authoritative=True,
                operation_ref=operation_ref,
                post_id=None,
                published_at=None,
                captured_at=self.now_fn(),
            )
        return self._commit_terminal(
            key=key,
            operation_ref=operation_ref,
            post_id=video_id,
            post_url="https://www.youtube.com/watch?v=" + video_id,
        )

    def _lookup_ref(
        self,
        operation_ref: str,
    ) -> tuple[str, dict[str, Any]]:
        for event in reversed(self.journal.events):
            if (
                event["eventType"] == "provider_ref"
                and event["payload"].get("operationRef") == operation_ref
            ):
                return event["idempotencyKey"], event["payload"]
        raise ProviderRejected("unknown YouTube operation reference")


class StaticCredentialResolver:
    """Tests/local harness only; never serialize this object."""

    def __init__(
        self,
        mapping: Mapping[str, CredentialMaterial],
    ) -> None:
        self._mapping = dict(mapping)

    def resolve(self, credential_ref: str) -> CredentialMaterial | None:
        return self._mapping.get(credential_ref)


class FakeHttpTransport:
    """Deterministic CI transport. It never opens a network connection."""

    def __init__(
        self,
        responses: Sequence[HttpResponse | BaseException],
    ) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        json_body: Mapping[str, Any] | None = None,
        body: bytes | None = None,
        timeout_seconds: float,
    ) -> HttpResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headerNames": sorted(
                    name for name in headers
                    if name.lower() != "authorization"
                ),
                "authorizationPresent": any(
                    name.lower() == "authorization"
                    for name in headers
                ),
                "jsonDigest": (
                    None
                    if json_body is None
                    else reels.sha256_json(json_body)
                ),
                "bodySha256": (
                    None
                    if body is None
                    else hashlib.sha256(body).hexdigest()
                ),
                "timeoutSeconds": timeout_seconds,
            }
        )
        if not self.responses:
            raise AssertionError("fake transport exhausted")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def production_provider(
    platform: str,
    *,
    credential_resolver: CredentialResolver,
    media_resolver: MediaResolver,
    transport: HttpTransport,
    journal_path: Path,
    config: RuntimeConfig | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    now_fn: Callable[[], str] = _utc_now,
) -> ProductionPublishProvider:
    kwargs = {
        "credential_resolver": credential_resolver,
        "media_resolver": media_resolver,
        "transport": transport,
        "journal_path": journal_path,
        "config": config,
        "sleep_fn": sleep_fn,
        "now_fn": now_fn,
    }
    if platform == "instagram_reels":
        return InstagramReelsProvider(**kwargs)
    if platform == "tiktok":
        return TikTokDirectPostProvider(**kwargs)
    if platform == "youtube_shorts":
        return YouTubeShortsProvider(**kwargs)
    raise ValueError("unsupported platform")


def sandbox_publish(
    *,
    media_path: Path,
    authorization_path: Path,
    platform: str,
    account_id: str,
    destination: str,
    credential_ref: str,
    caption: str,
    cta: str,
    out_dir: Path,
) -> dict[str, Any]:
    if platform not in r12.PLATFORMS:
        raise ValueError("unsupported platform")
    asset = probe_media(media_path)
    authorization = json.loads(
        authorization_path.read_text(encoding="utf-8")
    )
    media_binding = {
        "sourceClass": "synthetic_fixture",
        "contentId": "sha256:" + asset.sha256,
        "contentSha256": asset.sha256,
        "sizeBytes": asset.size_bytes,
        "contentType": "video/mp4",
        "durationSeconds": round(asset.duration_seconds, 6),
        "aspectRatio": "9:16",
        "manifestDigest": reels.sha256_json(
            {
                "source": "creator-r21-sandbox",
                "sha256": asset.sha256,
                "sizeBytes": asset.size_bytes,
                "durationSeconds": round(asset.duration_seconds, 6),
            }
        ),
    }
    request = r12.build_publish_request(
        platform=platform,
        account_id=account_id,
        destination=destination,
        credential_ref=credential_ref,
        authorization_lineage={
            "credentialRef": credential_ref,
            "authorizationRef": (
                "sandbox-auth-ref://"
                + hashlib.sha256(
                    authorization_path.read_bytes()
                ).hexdigest()[:24]
            ),
        },
        media=media_binding,
        caption=caption,
        cta=cta,
        release_authorization=authorization,
        allow_synthetic_fixture=True,
    )
    provider_cls = {
        "instagram_reels": r12.InstagramReelsMockProvider,
        "tiktok": r12.TikTokMockProvider,
        "youtube_shorts": r12.YouTubeShortsMockProvider,
    }[platform]
    provider = provider_cls(polls_before_publish=1)
    out_dir.mkdir(parents=True, exist_ok=True)
    coordinator = r12.DurablePublishCoordinator(
        out_dir / "publish-ledger.jsonl",
        request,
        allow_synthetic_fixture=True,
    )
    outcome: dict[str, Any] = {
        "state": "recoverable_unknown",
        "receipt": None,
    }
    for index in range(6):
        outcome = coordinator.drive(
            provider,
            now=f"2026-10-01T00:00:0{index}Z",
        )
        if outcome["state"] in {
            "published",
            "failed_terminal",
            "waiting_for_credentials",
        }:
            break
    if outcome["state"] != "published" or outcome["receipt"] is None:
        raise PublishExecutionError(
            "sandbox publish did not reach a terminal receipt"
        )
    receipt = r12.validate_provider_receipt(
        outcome["receipt"],
        request,
        allow_synthetic_fixture=True,
    )
    handoff = r12.build_growth_handoff(
        receipt,
        request,
        allow_synthetic_fixture=True,
    )
    report = {
        "contractVersion": SANDBOX_REPORT_VERSION,
        "executionVersion": EXECUTION_VERSION,
        "mode": "synthetic_sandbox",
        "networkUsed": False,
        "liveSideEffect": False,
        "request": request,
        "receipt": receipt,
        "growthHandoff": handoff,
        "providerAcceptedEffects": provider.accepted_effects,
        "providerSubmitCalls": provider.submit_calls,
        "state": outcome["state"],
    }
    report["reportDigest"] = reels.sha256_json(report)
    for name, value in (
        ("publish-request.json", request),
        ("provider-receipt.json", receipt),
        ("growth-handoff.json", handoff),
        ("sandbox-report.json", report),
    ):
        (out_dir / name).write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="creator-publish-sandbox",
        description=(
            "Run R12 publish prepare/submit/status/receipt/hand-off "
            "without network or live social side effects."
        ),
    )
    parser.add_argument("--media", required=True)
    parser.add_argument("--authorization", required=True)
    parser.add_argument(
        "--platform",
        required=True,
        choices=tuple(sorted(r12.PLATFORMS)),
    )
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--credential-ref", required=True)
    parser.add_argument("--caption", required=True)
    parser.add_argument("--cta", default="Learn more")
    parser.add_argument("--out", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = sandbox_publish(
            media_path=Path(args.media),
            authorization_path=Path(args.authorization),
            platform=args.platform,
            account_id=args.account_id,
            destination=args.destination,
            credential_ref=args.credential_ref,
            caption=args.caption,
            cta=args.cta,
            out_dir=Path(args.out),
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "contractVersion": SANDBOX_REPORT_VERSION,
                    "state": "BLOCKED",
                    "reason": type(exc).__name__,
                    "networkUsed": False,
                    "liveSideEffect": False,
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
