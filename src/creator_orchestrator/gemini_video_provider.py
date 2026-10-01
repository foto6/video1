from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from . import autonomous_reels as reels
from . import semantic_director as sd

GEMINI_PROVIDER_VERSION = "creator.gemini_native_video_provider.r18b.v1"
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
PROVIDER_UNAVAILABLE = "provider_unavailable"
PROVIDER_TIMEOUT = "provider_timeout"
PROVIDER_INVALID_OUTPUT = "provider_invalid_output"
PROVIDER_READY = "provider_ready"

_ALLOWED_EVENTS = (
    "hook",
    "setup",
    "proof_demo",
    "explanation",
    "punchline_payoff",
    "cta_candidate",
    "low_information",
)

_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "contractVersion",
        "transcriptSegments",
        "visualSubjects",
        "importantObjects",
        "semanticEvents",
    ],
    "properties": {
        "contractVersion": {
            "type": "string",
            "const": sd.SEMANTIC_ANALYSIS_VERSION,
        },
        "transcriptSegments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "startMs",
                    "endMs",
                    "text",
                    "confidence",
                ],
                "properties": {
                    "startMs": {"type": "integer", "minimum": 0},
                    "endMs": {"type": "integer", "minimum": 1},
                    "text": {"type": "string"},
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                },
            },
        },
        "visualSubjects": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "startMs",
                    "endMs",
                    "kind",
                    "label",
                    "box",
                    "confidence",
                ],
                "properties": {
                    "startMs": {"type": "integer", "minimum": 0},
                    "endMs": {"type": "integer", "minimum": 1},
                    "kind": {"type": "string"},
                    "label": {"type": "string"},
                    "box": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["x", "y", "width", "height"],
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "width": {"type": "number"},
                            "height": {"type": "number"},
                        },
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                },
            },
        },
        "importantObjects": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "startMs",
                    "endMs",
                    "kind",
                    "label",
                    "isReveal",
                    "confidence",
                ],
                "properties": {
                    "startMs": {"type": "integer", "minimum": 0},
                    "endMs": {"type": "integer", "minimum": 1},
                    "kind": {"type": "string"},
                    "label": {"type": "string"},
                    "isReveal": {"type": "boolean"},
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                },
            },
        },
        "semanticEvents": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "startMs",
                    "endMs",
                    "event",
                    "rationale",
                    "confidence",
                ],
                "properties": {
                    "startMs": {"type": "integer", "minimum": 0},
                    "endMs": {"type": "integer", "minimum": 1},
                    "event": {
                        "type": "string",
                        "enum": list(_ALLOWED_EVENTS),
                    },
                    "rationale": {"type": "string"},
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                },
            },
        },
    },
}


class GeminiTransportError(RuntimeError):
    pass


class GeminiTransportTimeout(GeminiTransportError):
    pass


@dataclass(frozen=True)
class GeminiUpload:
    name: str
    uri: str
    mime_type: str
    state: str


class GeminiVideoTransport(Protocol):
    def upload(
        self,
        *,
        path: Path,
        mime_type: str,
        timeout_seconds: float,
    ) -> GeminiUpload:
        ...

    def get_file(
        self,
        *,
        name: str,
        timeout_seconds: float,
    ) -> GeminiUpload:
        ...

    def analyze(
        self,
        *,
        upload: GeminiUpload,
        model: str,
        mode: str,
        prompt: str,
        response_schema: Mapping[str, Any],
        fps: float,
        clip_start_seconds: float,
        clip_end_seconds: float | None,
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        ...

    def delete_file(
        self,
        *,
        name: str,
        timeout_seconds: float,
    ) -> None:
        ...


@dataclass(frozen=True)
class GeminiNativeVideoConfig:
    enabled: bool = False
    model: str = DEFAULT_GEMINI_MODEL
    mode: str = "static"
    static_fps: float = 1.0
    clip_start_seconds: float = 0.0
    clip_end_seconds: float | None = None
    upload_timeout_seconds: float = 30.0
    poll_timeout_seconds: float = 90.0
    request_timeout_seconds: float = 90.0
    cleanup_timeout_seconds: float = 15.0
    poll_interval_seconds: float = 1.0
    max_poll_attempts: int = 90
    max_upload_bytes: int = 512 * 1024 * 1024
    max_retries: int = 2
    agentic_model_supported: bool = False

    def validate(self) -> "GeminiNativeVideoConfig":
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be boolean")
        if not self.model.strip():
            raise ValueError("Gemini model must be non-empty")
        if self.mode not in {"static", "agentic"}:
            raise ValueError("Gemini mode must be static or agentic")
        if self.mode == "agentic" and not self.agentic_model_supported:
            raise ValueError(
                "agentic mode requires an explicit supported-model capability flag"
            )
        if not 0.01 <= float(self.static_fps) <= 24.0:
            raise ValueError("static FPS must be between 0.01 and 24")
        if float(self.clip_start_seconds) < 0:
            raise ValueError("clip start cannot be negative")
        if (
            self.clip_end_seconds is not None
            and float(self.clip_end_seconds) <= float(self.clip_start_seconds)
        ):
            raise ValueError("clip end must exceed clip start")
        for name in (
            "upload_timeout_seconds",
            "poll_timeout_seconds",
            "request_timeout_seconds",
            "cleanup_timeout_seconds",
            "poll_interval_seconds",
        ):
            if float(getattr(self, name)) <= 0:
                raise ValueError(f"{name} must be positive")
        if not 1 <= int(self.max_poll_attempts) <= 600:
            raise ValueError("max_poll_attempts must be 1-600")
        if not 1 <= int(self.max_upload_bytes) <= 20 * 1024 * 1024 * 1024:
            raise ValueError("max_upload_bytes is out of bounds")
        if not 0 <= int(self.max_retries) <= 5:
            raise ValueError("max_retries must be 0-5")
        return self

    @classmethod
    def from_env(
        cls,
        *,
        explicitly_enabled: bool = False,
        mode: str | None = None,
        fps: float | None = None,
        clip_start_seconds: float | None = None,
        clip_end_seconds: float | None = None,
    ) -> "GeminiNativeVideoConfig":
        selected_mode = mode or os.environ.get(
            "GEMINI_VIDEO_MODE",
            "static",
        )
        supported = os.environ.get(
            "GEMINI_AGENTIC_MODEL_SUPPORTED",
            "",
        ).strip().lower() in {"1", "true", "yes"}
        config = cls(
            enabled=bool(explicitly_enabled),
            model=os.environ.get(
                "GEMINI_MODEL",
                DEFAULT_GEMINI_MODEL,
            ).strip(),
            mode=selected_mode,
            static_fps=float(
                fps
                if fps is not None
                else os.environ.get("GEMINI_VIDEO_FPS", "1.0")
            ),
            clip_start_seconds=float(
                clip_start_seconds
                if clip_start_seconds is not None
                else os.environ.get(
                    "GEMINI_VIDEO_CLIP_START_SECONDS",
                    "0",
                )
            ),
            clip_end_seconds=(
                clip_end_seconds
                if clip_end_seconds is not None
                else (
                    float(os.environ["GEMINI_VIDEO_CLIP_END_SECONDS"])
                    if os.environ.get("GEMINI_VIDEO_CLIP_END_SECONDS")
                    else None
                )
            ),
            agentic_model_supported=supported,
        )
        return config.validate()


class HttpGeminiVideoTransport:
    """Minimal stdlib transport. API key is retained only in memory."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def _request(
        self,
        request: urllib.request.Request,
        *,
        timeout_seconds: float,
    ) -> tuple[bytes, Mapping[str, str]]:
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout_seconds,
            ) as response:
                return response.read(), dict(response.headers.items())
        except TimeoutError as exc:
            raise GeminiTransportTimeout("Gemini request timed out") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise GeminiTransportTimeout(
                    "Gemini request timed out"
                ) from exc
            raise GeminiTransportError(
                f"Gemini transport failed: {type(exc).__name__}"
            ) from exc
        except urllib.error.HTTPError as exc:
            raise GeminiTransportError(
                f"Gemini HTTP request failed with status {exc.code}"
            ) from exc

    def _json_request(
        self,
        *,
        url: str,
        payload: Mapping[str, Any] | None,
        method: str,
        timeout_seconds: float,
        extra_headers: Mapping[str, str] | None = None,
    ) -> tuple[dict[str, Any], Mapping[str, str]]:
        data = None
        headers = {
            "x-goog-api-key": self._api_key,
        }
        if payload is not None:
            data = json.dumps(
                payload,
                separators=(",", ":"),
            ).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)
        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method,
        )
        body, response_headers = self._request(
            request,
            timeout_seconds=timeout_seconds,
        )
        if not body:
            return {}, response_headers
        try:
            return json.loads(body), response_headers
        except json.JSONDecodeError as exc:
            raise GeminiTransportError(
                "Gemini returned non-JSON transport response"
            ) from exc

    def upload(
        self,
        *,
        path: Path,
        mime_type: str,
        timeout_seconds: float,
    ) -> GeminiUpload:
        size = path.stat().st_size
        start_payload = {
            "file": {
                "display_name": (
                    "creator-r18b-"
                    + hashlib.sha256(path.read_bytes()).hexdigest()[:16]
                )
            }
        }
        _, headers = self._json_request(
            url=self._base_url + "/upload/v1beta/files",
            payload=start_payload,
            method="POST",
            timeout_seconds=timeout_seconds,
            extra_headers={
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(size),
                "X-Goog-Upload-Header-Content-Type": mime_type,
            },
        )
        upload_url = next(
            (
                value
                for key, value in headers.items()
                if key.lower() == "x-goog-upload-url"
            ),
            None,
        )
        if not upload_url:
            raise GeminiTransportError(
                "Gemini upload did not return resumable upload URL"
            )
        request = urllib.request.Request(
            upload_url,
            data=path.read_bytes(),
            headers={
                "Content-Length": str(size),
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
                "Content-Type": mime_type,
            },
            method="POST",
        )
        body, _ = self._request(
            request,
            timeout_seconds=timeout_seconds,
        )
        try:
            value = json.loads(body)
            file_value = value["file"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise GeminiTransportError(
                "Gemini upload returned malformed file metadata"
            ) from exc
        return GeminiUpload(
            name=str(file_value["name"]),
            uri=str(file_value["uri"]),
            mime_type=str(file_value.get("mimeType") or mime_type),
            state=str(
                (file_value.get("state") or {}).get("name")
                if isinstance(file_value.get("state"), Mapping)
                else file_value.get("state") or ""
            ),
        )

    def get_file(
        self,
        *,
        name: str,
        timeout_seconds: float,
    ) -> GeminiUpload:
        value, _ = self._json_request(
            url=self._base_url + "/v1beta/" + name,
            payload=None,
            method="GET",
            timeout_seconds=timeout_seconds,
        )
        return GeminiUpload(
            name=str(value["name"]),
            uri=str(value["uri"]),
            mime_type=str(value.get("mimeType") or "video/mp4"),
            state=str(
                (value.get("state") or {}).get("name")
                if isinstance(value.get("state"), Mapping)
                else value.get("state") or ""
            ),
        )

    @staticmethod
    def _extract_text(value: Mapping[str, Any]) -> str:
        if isinstance(value.get("output_text"), str):
            return str(value["output_text"])
        candidates = value.get("candidates")
        if isinstance(candidates, list):
            parts = (
                candidates[0]
                .get("content", {})
                .get("parts", [])
                if candidates
                else []
            )
            texts = [
                part["text"]
                for part in parts
                if isinstance(part, Mapping)
                and isinstance(part.get("text"), str)
            ]
            if texts:
                return "".join(texts)
        output = value.get("output")
        if isinstance(output, list):
            texts = []
            for item in output:
                if not isinstance(item, Mapping):
                    continue
                content = item.get("content")
                if isinstance(content, list):
                    for part in content:
                        if (
                            isinstance(part, Mapping)
                            and isinstance(part.get("text"), str)
                        ):
                            texts.append(part["text"])
            if texts:
                return "".join(texts)
        raise GeminiTransportError(
            "Gemini analysis response contained no text output"
        )

    def analyze(
        self,
        *,
        upload: GeminiUpload,
        model: str,
        mode: str,
        prompt: str,
        response_schema: Mapping[str, Any],
        fps: float,
        clip_start_seconds: float,
        clip_end_seconds: float | None,
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        if mode == "agentic":
            payload = {
                "model": model,
                "input": [
                    {
                        "type": "video",
                        "uri": upload.uri,
                        "mime_type": upload.mime_type,
                        "processing": "agentic",
                    },
                    {"type": "text", "text": prompt},
                ],
                "response_format": {
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": response_schema,
                },
            }
            value, _ = self._json_request(
                url=self._base_url + "/v1beta/interactions",
                payload=payload,
                method="POST",
                timeout_seconds=timeout_seconds,
            )
        else:
            video_metadata: dict[str, Any] = {
                "fps": fps,
                "startOffset": f"{clip_start_seconds}s",
            }
            if clip_end_seconds is not None:
                video_metadata["endOffset"] = f"{clip_end_seconds}s"
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "fileData": {
                                    "fileUri": upload.uri,
                                    "mimeType": upload.mime_type,
                                },
                                "videoMetadata": video_metadata,
                            },
                            {"text": prompt},
                        ],
                    }
                ],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseJsonSchema": response_schema,
                },
            }
            value, _ = self._json_request(
                url=(
                    self._base_url
                    + "/v1beta/models/"
                    + model
                    + ":generateContent"
                ),
                payload=payload,
                method="POST",
                timeout_seconds=timeout_seconds,
            )
        text = self._extract_text(value)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GeminiTransportError(
                "Gemini structured output was not valid JSON"
            ) from exc
        if not isinstance(parsed, Mapping):
            raise GeminiTransportError(
                "Gemini structured output must be an object"
            )
        return parsed

    def delete_file(
        self,
        *,
        name: str,
        timeout_seconds: float,
    ) -> None:
        self._json_request(
            url=self._base_url + "/v1beta/" + name,
            payload=None,
            method="DELETE",
            timeout_seconds=timeout_seconds,
        )


def _request_prompt(
    *,
    brief: str,
    duration_ms: int,
) -> str:
    return (
        "Analyze the uploaded native video directly using both visual and "
        "audio evidence. Return only JSON matching the supplied schema. "
        "All startMs/endMs are integer milliseconds within 0.."
        + str(duration_ms)
        + ". Do not infer an object, transcript, or event when evidence is "
        "not visible/audible. Important objects should emphasize products, "
        "screens, interfaces, devices, and reveal moments. Semantic events "
        "may only use hook, setup, proof_demo, explanation, "
        "punchline_payoff, cta_candidate, low_information. Confidence must "
        "be calibrated 0..1. Operator brief context: "
        + brief[:1200]
    )


def _validate_box(box: Any) -> dict[str, float]:
    if not isinstance(box, Mapping) or set(box) != {
        "x",
        "y",
        "width",
        "height",
    }:
        raise ValueError("subject box must have x/y/width/height")
    result = {}
    for key in ("x", "y", "width", "height"):
        value = box[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("subject box coordinate must be numeric")
        number = float(value)
        if not 0.0 <= number <= 1.0:
            raise ValueError("subject box coordinate outside 0..1")
        result[key] = number
    if result["width"] <= 0 or result["height"] <= 0:
        raise ValueError("subject box width/height must be positive")
    if result["x"] + result["width"] > 1.000001:
        raise ValueError("subject box exceeds normalized width")
    if result["y"] + result["height"] > 1.000001:
        raise ValueError("subject box exceeds normalized height")
    return result


def _validate_range(
    item: Mapping[str, Any],
    *,
    duration_ms: int,
) -> tuple[int, int, float]:
    start = item.get("startMs")
    end = item.get("endMs")
    confidence = item.get("confidence")
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
    ):
        raise ValueError("timestamps must be integer milliseconds")
    if start < 0 or end <= start or end > duration_ms:
        raise ValueError("timestamp range outside ffprobe duration")
    return start, end, sd._confidence(confidence)


def _strict_keys(
    value: Mapping[str, Any],
    keys: set[str],
    label: str,
) -> None:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"{label} fields do not match strict schema")


def validate_provider_output(
    value: Mapping[str, Any],
    *,
    duration_ms: int,
) -> dict[str, Any]:
    _strict_keys(
        value,
        {
            "contractVersion",
            "transcriptSegments",
            "visualSubjects",
            "importantObjects",
            "semanticEvents",
        },
        "Gemini output",
    )
    if value["contractVersion"] != sd.SEMANTIC_ANALYSIS_VERSION:
        raise ValueError("Gemini semantic contract version mismatch")
    for key in (
        "transcriptSegments",
        "visualSubjects",
        "importantObjects",
        "semanticEvents",
    ):
        if not isinstance(value[key], list):
            raise ValueError(f"{key} must be an array")

    transcript = []
    for item in value["transcriptSegments"]:
        _strict_keys(
            item,
            {"startMs", "endMs", "text", "confidence"},
            "transcript segment",
        )
        start, end, confidence = _validate_range(
            item,
            duration_ms=duration_ms,
        )
        text = item["text"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("transcript text must be non-empty")
        transcript.append(
            {
                "startMs": start,
                "endMs": end,
                "text": text.strip(),
                "confidence": confidence,
            }
        )

    subjects = []
    for item in value["visualSubjects"]:
        _strict_keys(
            item,
            {
                "startMs",
                "endMs",
                "kind",
                "label",
                "box",
                "confidence",
            },
            "visual subject",
        )
        start, end, confidence = _validate_range(
            item,
            duration_ms=duration_ms,
        )
        if not isinstance(item["kind"], str) or not item["kind"].strip():
            raise ValueError("subject kind must be non-empty")
        if not isinstance(item["label"], str):
            raise ValueError("subject label must be a string")
        subjects.append(
            {
                "startMs": start,
                "endMs": end,
                "kind": item["kind"].strip(),
                "label": item["label"].strip(),
                "box": _validate_box(item["box"]),
                "confidence": confidence,
            }
        )

    objects = []
    for item in value["importantObjects"]:
        _strict_keys(
            item,
            {
                "startMs",
                "endMs",
                "kind",
                "label",
                "isReveal",
                "confidence",
            },
            "important object",
        )
        start, end, confidence = _validate_range(
            item,
            duration_ms=duration_ms,
        )
        if not isinstance(item["kind"], str) or not item["kind"].strip():
            raise ValueError("object kind must be non-empty")
        if not isinstance(item["label"], str):
            raise ValueError("object label must be a string")
        if not isinstance(item["isReveal"], bool):
            raise ValueError("isReveal must be boolean")
        objects.append(
            {
                "startMs": start,
                "endMs": end,
                "kind": item["kind"].strip(),
                "label": item["label"].strip(),
                "isReveal": item["isReveal"],
                "confidence": confidence,
            }
        )

    events = []
    for item in value["semanticEvents"]:
        _strict_keys(
            item,
            {
                "startMs",
                "endMs",
                "event",
                "rationale",
                "confidence",
            },
            "semantic event",
        )
        start, end, confidence = _validate_range(
            item,
            duration_ms=duration_ms,
        )
        event = item["event"]
        if event not in _ALLOWED_EVENTS:
            raise ValueError("unsupported semantic event")
        if not isinstance(item["rationale"], str):
            raise ValueError("semantic rationale must be a string")
        events.append(
            {
                "startMs": start,
                "endMs": end,
                "event": event,
                "rationale": item["rationale"].strip()[:500],
                "confidence": confidence,
            }
        )

    return {
        "contractVersion": sd.SEMANTIC_ANALYSIS_VERSION,
        "transcriptSegments": transcript,
        "visualSubjects": subjects,
        "importantObjects": objects,
        "semanticEvents": events,
    }


@dataclass
class GeminiNativeVideoAdapter:
    config: GeminiNativeVideoConfig
    transport: GeminiVideoTransport | None = None
    api_key: str | None = None
    sleep_fn: Any = time.sleep
    name: str = "google_gemini_native_video"

    def _unavailable(
        self,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "contractVersion": sd.ADAPTER_RESULT_VERSION,
            "adapter": self.name,
            "status": "unavailable",
            "providerMode": "unavailable",
            "evidence": [],
            "unavailableCategories": [
                "transcriptSegments",
                "sentenceBoundaries",
                "visualSubjects",
                "importantObjects",
                "semanticEvents",
            ],
            "reason": reason,
        }

    def analyze(
        self,
        video_path: Path,
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        try:
            config = self.config.validate()
        except ValueError:
            return self._unavailable(PROVIDER_UNAVAILABLE)
        if not config.enabled:
            return self._unavailable(PROVIDER_UNAVAILABLE)
        api_key = self.api_key or os.environ.get("GEMINI_API_KEY")
        if self.transport is None and not api_key:
            return self._unavailable(PROVIDER_UNAVAILABLE)
        path = Path(video_path)
        if not path.is_file():
            return self._unavailable(PROVIDER_UNAVAILABLE)
        try:
            size = path.stat().st_size
        except OSError:
            return self._unavailable(PROVIDER_UNAVAILABLE)
        if size <= 0 or size > config.max_upload_bytes:
            return self._unavailable(PROVIDER_UNAVAILABLE)

        duration_ms = int(context["durationMs"])
        input_sha = str(context["inputSha256"])
        brief = str(context.get("brief") or "")
        clip_end = (
            config.clip_end_seconds
            if config.clip_end_seconds is not None
            else duration_ms / 1000.0
        )
        if config.clip_start_seconds * 1000 >= duration_ms:
            return self._unavailable(PROVIDER_INVALID_OUTPUT)
        clip_end = min(clip_end, duration_ms / 1000.0)
        if clip_end <= config.clip_start_seconds:
            return self._unavailable(PROVIDER_INVALID_OUTPUT)

        request_identity = {
            "providerVersion": GEMINI_PROVIDER_VERSION,
            "provider": "google_gemini",
            "model": config.model,
            "mode": config.mode,
            "staticFps": config.static_fps,
            "clipStartSeconds": config.clip_start_seconds,
            "clipEndSeconds": clip_end,
            "inputSha256": input_sha,
            "durationMs": duration_ms,
            "schemaDigest": reels.sha256_json(_OUTPUT_SCHEMA),
            "promptDigest": reels.sha256_text(
                _request_prompt(brief=brief, duration_ms=duration_ms)
            ),
        }
        request_digest = reels.sha256_json(request_identity)
        transport = self.transport or HttpGeminiVideoTransport(
            api_key=api_key or ""
        )
        mime_type = mimetypes.guess_type(str(path))[0] or "video/mp4"
        upload: GeminiUpload | None = None
        cleanup_state = "not_uploaded"
        try:
            upload = transport.upload(
                path=path,
                mime_type=mime_type,
                timeout_seconds=config.upload_timeout_seconds,
            )
            deadline = time.monotonic() + config.poll_timeout_seconds
            attempts = 0
            while upload.state.upper() != "ACTIVE":
                if upload.state.upper() in {
                    "FAILED",
                    "ERROR",
                    "CANCELLED",
                }:
                    return self._unavailable(PROVIDER_UNAVAILABLE)
                attempts += 1
                if (
                    attempts >= config.max_poll_attempts
                    or time.monotonic() >= deadline
                ):
                    return self._unavailable(PROVIDER_TIMEOUT)
                self.sleep_fn(config.poll_interval_seconds)
                upload = transport.get_file(
                    name=upload.name,
                    timeout_seconds=min(
                        config.upload_timeout_seconds,
                        max(1.0, deadline - time.monotonic()),
                    ),
                )
            upload_identity = {
                "remoteNameDigest": reels.sha256_text(upload.name),
                "inputSha256": input_sha,
                "size": size,
                "mimeType": upload.mime_type,
            }
            upload_identity_digest = reels.sha256_json(upload_identity)
            prompt = _request_prompt(
                brief=brief,
                duration_ms=duration_ms,
            )
            raw: Mapping[str, Any] | None = None
            for attempt in range(config.max_retries + 1):
                try:
                    raw = transport.analyze(
                        upload=upload,
                        model=config.model,
                        mode=config.mode,
                        prompt=prompt,
                        response_schema=_OUTPUT_SCHEMA,
                        fps=config.static_fps,
                        clip_start_seconds=config.clip_start_seconds,
                        clip_end_seconds=clip_end,
                        timeout_seconds=config.request_timeout_seconds,
                    )
                    break
                except GeminiTransportTimeout:
                    if attempt >= config.max_retries:
                        return self._unavailable(PROVIDER_TIMEOUT)
                except GeminiTransportError:
                    if attempt >= config.max_retries:
                        return self._unavailable(PROVIDER_UNAVAILABLE)
            if raw is None:
                return self._unavailable(PROVIDER_UNAVAILABLE)
            try:
                validated = validate_provider_output(
                    raw,
                    duration_ms=duration_ms,
                )
            except (ValueError, sd.SemanticDirectorError):
                return self._unavailable(PROVIDER_INVALID_OUTPUT)

            provenance = {
                "provider": "google_gemini",
                "providerVersion": GEMINI_PROVIDER_VERSION,
                "model": config.model,
                "mode": config.mode,
                "requestDigest": request_digest,
                "uploadIdentityDigest": upload_identity_digest,
                "staticFps": (
                    config.static_fps
                    if config.mode == "static"
                    else None
                ),
                "clipStartSeconds": config.clip_start_seconds,
                "clipEndSeconds": clip_end,
                "remoteCleanupRequired": True,
            }
            detail = reels.canonical_json(provenance)
            source = sd._source(
                adapter=self.name,
                mode="provider",
                input_sha256=input_sha,
                detail=detail,
            )
            evidence = []
            for item in validated["transcriptSegments"]:
                evidence.append(
                    sd.evidence_span(
                        evidence_type="transcript_segment",
                        start_ms=item["startMs"],
                        end_ms=item["endMs"],
                        value={
                            "text": item["text"],
                            "speechEnergy": 0.7,
                            "providerProvenance": provenance,
                        },
                        confidence=item["confidence"],
                        source=source,
                        duration_ms=duration_ms,
                    )
                )
            for item in validated["visualSubjects"]:
                evidence.append(
                    sd.evidence_span(
                        evidence_type="visual_subject",
                        start_ms=item["startMs"],
                        end_ms=item["endMs"],
                        value={
                            "kind": item["kind"],
                            "label": item["label"],
                            "box": item["box"],
                            "providerProvenance": provenance,
                        },
                        confidence=item["confidence"],
                        source=source,
                        duration_ms=duration_ms,
                    )
                )
            for item in validated["importantObjects"]:
                evidence.append(
                    sd.evidence_span(
                        evidence_type="important_object",
                        start_ms=item["startMs"],
                        end_ms=item["endMs"],
                        value={
                            "kind": item["kind"],
                            "label": item["label"],
                            "isReveal": item["isReveal"],
                            "providerProvenance": provenance,
                        },
                        confidence=item["confidence"],
                        source=source,
                        duration_ms=duration_ms,
                    )
                )
            for item in validated["semanticEvents"]:
                evidence.append(
                    sd.evidence_span(
                        evidence_type="semantic_event",
                        start_ms=item["startMs"],
                        end_ms=item["endMs"],
                        value={
                            "event": item["event"],
                            "basis": "gemini_native_video_observation",
                            "rationale": item["rationale"],
                            "providerProvenance": provenance,
                        },
                        confidence=item["confidence"],
                        source=source,
                        duration_ms=duration_ms,
                    )
                )
            cleanup_state = "pending"
            return {
                "contractVersion": sd.ADAPTER_RESULT_VERSION,
                "adapter": self.name,
                "status": "available",
                "providerMode": (
                    "gemini_agentic"
                    if config.mode == "agentic"
                    else "gemini_static"
                ),
                "evidence": evidence,
                "unavailableCategories": [],
                "reason": PROVIDER_READY,
            }
        except GeminiTransportTimeout:
            return self._unavailable(PROVIDER_TIMEOUT)
        except GeminiTransportError:
            return self._unavailable(PROVIDER_UNAVAILABLE)
        finally:
            if upload is not None:
                try:
                    transport.delete_file(
                        name=upload.name,
                        timeout_seconds=config.cleanup_timeout_seconds,
                    )
                    cleanup_state = "deleted"
                except Exception:
                    cleanup_state = "cleanup_failed"


class FakeGeminiVideoTransport:
    """CI-only fake; no network, auth, or paid calls."""

    def __init__(
        self,
        *,
        output: Mapping[str, Any],
        poll_states: Sequence[str] = ("PROCESSING", "ACTIVE"),
        timeout_on_analyze: bool = False,
    ):
        self.output = json.loads(reels.canonical_json(output))
        self.poll_states = list(poll_states)
        self.timeout_on_analyze = timeout_on_analyze
        self.calls: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self._poll_index = 0

    def upload(
        self,
        *,
        path: Path,
        mime_type: str,
        timeout_seconds: float,
    ) -> GeminiUpload:
        self.calls.append(
            {
                "op": "upload",
                "pathSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "mimeType": mime_type,
                "timeout": timeout_seconds,
            }
        )
        state = self.poll_states[0] if self.poll_states else "ACTIVE"
        return GeminiUpload(
            name="files/fake-native-video",
            uri="gemini://fake-native-video",
            mime_type=mime_type,
            state=state,
        )

    def get_file(
        self,
        *,
        name: str,
        timeout_seconds: float,
    ) -> GeminiUpload:
        self._poll_index += 1
        index = min(self._poll_index, len(self.poll_states) - 1)
        state = self.poll_states[index] if self.poll_states else "ACTIVE"
        self.calls.append(
            {"op": "get", "name": name, "timeout": timeout_seconds}
        )
        return GeminiUpload(
            name=name,
            uri="gemini://fake-native-video",
            mime_type="video/mp4",
            state=state,
        )

    def analyze(
        self,
        *,
        upload: GeminiUpload,
        model: str,
        mode: str,
        prompt: str,
        response_schema: Mapping[str, Any],
        fps: float,
        clip_start_seconds: float,
        clip_end_seconds: float | None,
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        self.calls.append(
            {
                "op": "analyze",
                "model": model,
                "mode": mode,
                "promptDigest": reels.sha256_text(prompt),
                "schemaDigest": reels.sha256_json(response_schema),
                "fps": fps,
                "clipStart": clip_start_seconds,
                "clipEnd": clip_end_seconds,
                "timeout": timeout_seconds,
            }
        )
        if self.timeout_on_analyze:
            raise GeminiTransportTimeout("fake timeout")
        return json.loads(reels.canonical_json(self.output))

    def delete_file(
        self,
        *,
        name: str,
        timeout_seconds: float,
    ) -> None:
        self.deleted.append(name)
        self.calls.append(
            {"op": "delete", "name": name, "timeout": timeout_seconds}
        )


def build_semantic_adapters(
    *,
    config: GeminiNativeVideoConfig,
    transport: GeminiVideoTransport | None = None,
    api_key: str | None = None,
) -> sd.SemanticAdapters:
    local = sd.SemanticAdapters.local_default()
    return sd.SemanticAdapters(
        asr=local.asr,
        shot=local.shot,
        cv=local.cv,
        vlm=GeminiNativeVideoAdapter(
            config=config,
            transport=transport,
            api_key=api_key,
        ),
    )


def smoke(
    *,
    input_path: str | Path,
    live: bool,
    mode: str,
    fps: float,
    clip_start_seconds: float,
    clip_end_seconds: float | None,
) -> dict[str, Any]:
    path = Path(input_path).expanduser().resolve()
    key = os.environ.get("GEMINI_API_KEY")
    enabled = os.environ.get(
        "CREATOR_GEMINI_VIDEO_ENABLE",
        "",
    ).strip().lower() in {"1", "true", "yes"}
    if not live or not enabled or not key:
        return {
            "contractVersion": GEMINI_PROVIDER_VERSION,
            "state": "BLOCKED",
            "reason": (
                "live smoke requires --live, "
                "CREATOR_GEMINI_VIDEO_ENABLE=1, and GEMINI_API_KEY"
            ),
            "networkAttempted": False,
        }
    if not path.is_file():
        return {
            "contractVersion": GEMINI_PROVIDER_VERSION,
            "state": "BLOCKED",
            "reason": "input video does not exist",
            "networkAttempted": False,
        }
    probe = subprocess_probe(path)
    config = GeminiNativeVideoConfig.from_env(
        explicitly_enabled=True,
        mode=mode,
        fps=fps,
        clip_start_seconds=clip_start_seconds,
        clip_end_seconds=clip_end_seconds,
    )
    adapter = GeminiNativeVideoAdapter(
        config=config,
        api_key=key,
    )
    result = adapter.analyze(
        path,
        {
            "inputSha256": probe["sha256"],
            "durationMs": probe["durationMs"],
            "width": probe["width"],
            "height": probe["height"],
            "fps": probe["fps"],
            "hasAudio": probe["hasAudio"],
            "brief": "Gemini R18B live smoke only; no quality claim.",
        },
    )
    return {
        "contractVersion": GEMINI_PROVIDER_VERSION,
        "state": (
            "SMOKE_OK"
            if result["status"] == "available"
            else "BLOCKED"
        ),
        "providerStatus": result["status"],
        "providerReason": result["reason"],
        "evidenceCount": len(result["evidence"]),
        "networkAttempted": True,
        "humanLevelQuality": sd.HUMAN_LEVEL_STATE,
    }


def subprocess_probe(path: Path) -> dict[str, Any]:
    import subprocess

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,width,height,r_frame_rate:format=duration",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise ValueError("ffprobe could not read smoke video")
    value = json.loads(result.stdout)
    video = next(
        item
        for item in value["streams"]
        if item["codec_type"] == "video"
    )
    numerator, denominator = video["r_frame_rate"].split("/", 1)
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "durationMs": int(round(float(value["format"]["duration"]) * 1000)),
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": float(numerator) / float(denominator),
        "hasAudio": any(
            item["codec_type"] == "audio"
            for item in value["streams"]
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="creator-gemini-video-smoke",
        description="Opt-in Gemini native-video semantic provider smoke test.",
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--mode",
        choices=("static", "agentic"),
        default="static",
    )
    parser.add_argument("--fps", type=float, default=1.0)
    parser.add_argument("--clip-start", type=float, default=0.0)
    parser.add_argument("--clip-end", type=float)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = smoke(
            input_path=args.input,
            live=args.live,
            mode=args.mode,
            fps=args.fps,
            clip_start_seconds=args.clip_start,
            clip_end_seconds=args.clip_end,
        )
    except Exception as exc:
        report = {
            "contractVersion": GEMINI_PROVIDER_VERSION,
            "state": "BLOCKED",
            "reason": type(exc).__name__,
            "networkAttempted": bool(args.live),
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["state"] == "SMOKE_OK" else 2


if __name__ == "__main__":
    raise SystemExit(main())
