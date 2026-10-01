from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import autonomous_reels as reels
from . import integration_acceptance as r13
from . import publish_providers as r12

BATCH_CAMPAIGN_VERSION = "creator.batch_campaign.r14.v1"
BATCH_LEDGER_VERSION = "creator.batch_campaign_ledger.r14.v1"
BATCH_CONFIG_VERSION = "creator.batch_campaign_config.r14.v1"
BATCH_REPORT_VERSION = "creator.batch_campaign_report.r14.v1"
CREATOR_R13_BASE_SHA = "e8bc2ed365d6ca4c512079ff9cccd7543575f052"

PLATFORM_ORDER = ("instagram_reels", "tiktok", "youtube_shorts")
BUDGET_CATEGORIES = ("generation_units", "render_seconds", "provider_actions")
CONCURRENCY_KINDS = ("generation", "media", "provider")
SUMMARY_STATES = (
    "ready",
    "blocked_media",
    "qa_failed",
    "awaiting_release",
    "published",
    "analytics_pending",
)

_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "in", "is", "it", "of", "on", "or", "that", "the", "this", "to", "with",
    "your", "you",
})


class BatchCampaignError(ValueError):
    pass


class BatchConflict(BatchCampaignError):
    pass


class CampaignPaused(BatchCampaignError):
    pass


class CampaignCanceled(BatchCampaignError):
    pass


class BudgetExceeded(BatchCampaignError):
    pass


class ConcurrencyLimitExceeded(BatchCampaignError):
    pass


class SemanticDuplicate(BatchCampaignError):
    pass


class HookDiversityViolation(BatchCampaignError):
    pass


class PublishWindowBlocked(BatchCampaignError):
    pass


class ReleaseRequired(BatchCampaignError):
    pass


class InjectedMediaFailure(RuntimeError):
    pass


def _clone(value: Any) -> Any:
    return json.loads(reels.canonical_json(value))


def _number(value: Any, field: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BatchCampaignError(f"{field} must be numeric")
    result = float(value)
    if result < minimum:
        raise BatchCampaignError(f"{field} must be >= {minimum}")
    return result


def _positive_int(value: Any, field: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BatchCampaignError(f"{field} must be an integer >= 1")
    if maximum is not None and value > maximum:
        raise BatchCampaignError(f"{field} must be <= {maximum}")
    return value


def _iso_utc(value) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _semantic_words(text: str) -> tuple[str, ...]:
    if not isinstance(text, str) or not text.strip():
        raise BatchCampaignError("semantic text must be non-empty")
    words: list[str] = []
    for raw in re.findall(r"[a-z0-9]+", text.lower()):
        if raw in _STOPWORDS:
            continue
        word = raw
        if len(word) > 5 and word.endswith("ing"):
            word = word[:-3]
        elif len(word) > 4 and word.endswith("ed"):
            word = word[:-2]
        elif len(word) > 4 and word.endswith("s"):
            word = word[:-1]
        if word:
            words.append(word)
    return tuple(words)


def semantic_similarity(left: str, right: str) -> float:
    a = set(_semantic_words(left))
    b = set(_semantic_words(right))
    if not a or not b:
        return 1.0 if a == b else 0.0
    return len(a & b) / len(a | b)


def hook_signature(hook: str) -> str:
    words = _semantic_words(hook)
    if not words:
        raise HookDiversityViolation("hook has no semantic tokens")
    return "|".join(words[:3])


def hook_family(hook: str) -> str:
    words = _semantic_words(hook)
    if not words:
        raise HookDiversityViolation("hook has no semantic tokens")
    return words[0]


@dataclass(frozen=True)
class BatchCampaignConfig:
    batch_size: int
    platform_mix: Mapping[str, int]
    max_concurrency: Mapping[str, int]
    budget: Mapping[str, float]
    publish_window_start: str
    publish_window_end: str
    stagger_seconds: float
    concept_similarity_threshold: float = 0.75
    script_similarity_threshold: float = 0.90
    max_hook_family_reuse: int = 2

    def validate(self) -> "BatchCampaignConfig":
        _positive_int(self.batch_size, "batch_size", maximum=50)
        if (
            not isinstance(self.platform_mix, Mapping)
            or set(self.platform_mix) - set(PLATFORM_ORDER)
        ):
            raise BatchCampaignError("platform_mix contains an unsupported platform")
        for platform, count in self.platform_mix.items():
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise BatchCampaignError(f"platform_mix[{platform}] must be a non-negative integer")
        if sum(self.platform_mix.values()) != self.batch_size:
            raise BatchCampaignError("platform_mix counts must sum to batch_size")
        if set(self.max_concurrency) != set(CONCURRENCY_KINDS):
            raise BatchCampaignError("max_concurrency must contain generation/media/provider")
        for kind, limit in self.max_concurrency.items():
            _positive_int(limit, f"max_concurrency[{kind}]", maximum=32)
        if set(self.budget) != set(BUDGET_CATEGORIES):
            raise BatchCampaignError("budget must contain generation_units/render_seconds/provider_actions")
        for category, ceiling in self.budget.items():
            _number(ceiling, f"budget[{category}]", minimum=0.0)
        start = reels._parse_time(self.publish_window_start, "publish_window_start")
        end = reels._parse_time(self.publish_window_end, "publish_window_end")
        if start >= end:
            raise BatchCampaignError("publish window start must be before end")
        stagger = _number(self.stagger_seconds, "stagger_seconds", minimum=0.001)
        if start + timedelta(seconds=stagger * max(0, self.batch_size - 1)) > end:
            raise BatchCampaignError("publish window cannot contain the staggered batch")
        for threshold, field in (
            (self.concept_similarity_threshold, "concept_similarity_threshold"),
            (self.script_similarity_threshold, "script_similarity_threshold"),
        ):
            value = _number(threshold, field, minimum=0.0)
            if value > 1.0:
                raise BatchCampaignError(f"{field} must be <= 1")
        _positive_int(self.max_hook_family_reuse, "max_hook_family_reuse", maximum=10)
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "contractVersion": BATCH_CONFIG_VERSION,
            "batchSize": self.batch_size,
            "platformMix": {p: int(self.platform_mix.get(p, 0)) for p in PLATFORM_ORDER},
            "maxConcurrency": {kind: int(self.max_concurrency[kind]) for kind in CONCURRENCY_KINDS},
            "budget": {category: float(self.budget[category]) for category in BUDGET_CATEGORIES},
            "publishWindow": {
                "start": self.publish_window_start,
                "end": self.publish_window_end,
                "staggerSeconds": float(self.stagger_seconds),
            },
            "dedup": {
                "conceptSimilarityThreshold": float(self.concept_similarity_threshold),
                "scriptSimilarityThreshold": float(self.script_similarity_threshold),
                "maxHookFamilyReuse": int(self.max_hook_family_reuse),
            },
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BatchCampaignConfig":
        if not isinstance(payload, Mapping) or payload.get("contractVersion") != BATCH_CONFIG_VERSION:
            raise BatchCampaignError("unsupported batch config")
        result = cls(
            batch_size=payload["batchSize"],
            platform_mix=payload["platformMix"],
            max_concurrency=payload["maxConcurrency"],
            budget=payload["budget"],
            publish_window_start=payload["publishWindow"]["start"],
            publish_window_end=payload["publishWindow"]["end"],
            stagger_seconds=payload["publishWindow"]["staggerSeconds"],
            concept_similarity_threshold=payload["dedup"]["conceptSimilarityThreshold"],
            script_similarity_threshold=payload["dedup"]["scriptSimilarityThreshold"],
            max_hook_family_reuse=payload["dedup"]["maxHookFamilyReuse"],
        )
        return result.validate()


def sanitize_growth_advisory(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise BatchCampaignError("Growth advisory must be an object")
    reels._reject_secrets(value)
    recommendations = value.get("recommendations", [])
    if not isinstance(recommendations, Sequence) or isinstance(recommendations, (str, bytes)):
        raise BatchCampaignError("Growth advisory recommendations must be an array")
    authority = value.get("authority")
    authority_attempted = False
    if isinstance(authority, Mapping):
        authority_attempted = any(v is True for v in authority.values())
    return {
        "sourceContractVersion": str(value.get("contract_version") or value.get("contractVersion") or "unknown"),
        "sourceClass": str(value.get("source_class") or value.get("sourceClass") or "unknown"),
        "evidenceDigest": reels.sha256_json(value),
        "recommendations": _clone(list(recommendations)),
        "publicationAuthorityAccepted": False,
        "publicationAuthorityIgnored": authority_attempted,
    }


class BatchCampaignLedger:
    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        campaign_id: str,
        brief: Mapping[str, Any],
        config: BatchCampaignConfig,
        growth_advisory: Mapping[str, Any] | None = None,
    ) -> None:
        self.path = Path(path)
        self.campaign_id = reels._nonempty(campaign_id, "campaign_id")
        self.brief = _clone(brief)
        reels._reject_secrets(self.brief)
        self.config = config.validate()
        self.growth_advisory = sanitize_growth_advisory(growth_advisory)
        self.events: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        self.control_state = "active"
        self.items: dict[str, dict[str, Any]] = {}
        self.rejected_candidates: list[dict[str, Any]] = []
        self.budget_spent = {category: 0.0 for category in BUDGET_CATEGORIES}
        self.budget_reservations: list[dict[str, Any]] = []
        self.inflight: dict[str, dict[str, Any]] = {}
        self.max_observed_concurrency = {kind: 0 for kind in CONCURRENCY_KINDS}
        if self.path.exists():
            self._load()
            created = self.events[0]["payload"]
            expected = self._created_payload()
            if created != expected:
                raise BatchConflict("batch campaign identity/config/brief changed after creation")
        else:
            self._append_once("campaign:create", "campaign_created", self._created_payload())

    def _created_payload(self) -> dict[str, Any]:
        return {
            "campaignId": self.campaign_id,
            "brief": self.brief,
            "config": self.config.as_dict(),
            "growthAdvisory": self.growth_advisory,
        }

    def _event(self, event_key: str, event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = {
            "ledgerVersion": BATCH_LEDGER_VERSION,
            "sequence": len(self.events) + 1,
            "eventKey": event_key,
            "eventType": event_type,
            "payload": _clone(payload),
        }
        body["eventDigest"] = reels.sha256_json(body)
        return body

    def _append_once(self, event_key: str, event_type: str, payload: Mapping[str, Any]) -> str:
        reels._nonempty(event_key, "event_key")
        reels._reject_secrets(payload)
        existing = self.by_key.get(event_key)
        if existing is not None:
            if existing["eventType"] != event_type or existing["payload"] != _clone(payload):
                raise BatchConflict(f"conflicting durable replay for {event_key}")
            return "duplicate"
        event = self._event(event_key, event_type, payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(reels.canonical_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.events.append(event)
        self.by_key[event_key] = event
        self._apply(event)
        return "committed"

    def _load(self) -> None:
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BatchConflict(f"invalid batch ledger JSON line {line_number}") from exc
            if set(event) != {
                "ledgerVersion", "sequence", "eventKey", "eventType", "payload", "eventDigest"
            }:
                raise BatchConflict("batch ledger event fields invalid")
            if event["ledgerVersion"] != BATCH_LEDGER_VERSION:
                raise BatchConflict("batch ledger version mismatch")
            if event["sequence"] != len(self.events) + 1:
                raise BatchConflict("batch ledger sequence mismatch")
            material = dict(event)
            digest = material.pop("eventDigest")
            if reels.sha256_json(material) != digest:
                raise BatchConflict("batch ledger event digest mismatch")
            if event["eventKey"] in self.by_key:
                raise BatchConflict("duplicate event key in durable ledger")
            self.events.append(event)
            self.by_key[event["eventKey"]] = event
            self._apply(event)
        if not self.events or self.events[0]["eventType"] != "campaign_created":
            raise BatchConflict("batch ledger missing campaign_created")

    def _apply(self, event: Mapping[str, Any]) -> None:
        event_type = event["eventType"]
        payload = event["payload"]
        if event_type == "campaign_created":
            self.control_state = "active"
        elif event_type == "campaign_control":
            self.control_state = payload["state"]
        elif event_type == "budget_reserved":
            category = payload["category"]
            self.budget_spent[category] += float(payload["amount"])
            self.budget_reservations.append(_clone(payload))
        elif event_type == "candidate_rejected":
            self.rejected_candidates.append(_clone(payload))
        elif event_type == "item_created":
            item = _clone(payload)
            self.items[item["itemId"]] = item
        elif event_type == "item_stage":
            item = self.items[payload["itemId"]]
            item[payload["field"]] = _clone(payload["value"])
            item["state"] = payload["state"]
        elif event_type == "operation_started":
            operation_key = payload["operationKey"]
            self.inflight[operation_key] = _clone(payload)
            kind = payload["kind"]
            active = sum(1 for op in self.inflight.values() if op["kind"] == kind)
            self.max_observed_concurrency[kind] = max(
                self.max_observed_concurrency[kind], active
            )
        elif event_type == "operation_finished":
            self.inflight.pop(payload["operationKey"], None)
        else:
            raise BatchConflict(f"unknown batch ledger event type {event_type!r}")

    def _require_active(self) -> None:
        if self.control_state == "paused":
            raise CampaignPaused("batch campaign is paused")
        if self.control_state == "canceled":
            raise CampaignCanceled("batch campaign is canceled")

    def pause(self) -> str:
        if self.control_state == "canceled":
            raise CampaignCanceled("canceled campaign cannot be paused")
        if self.control_state == "paused":
            return "duplicate"
        return self._append_once(
            f"control:{len([e for e in self.events if e['eventType'] == 'campaign_control']) + 1}:paused",
            "campaign_control",
            {"state": "paused"},
        )

    def resume(self) -> str:
        if self.control_state == "canceled":
            raise CampaignCanceled("canceled campaign cannot resume")
        if self.control_state == "active":
            return "duplicate"
        return self._append_once(
            f"control:{len([e for e in self.events if e['eventType'] == 'campaign_control']) + 1}:active",
            "campaign_control",
            {"state": "active"},
        )

    def cancel(self) -> str:
        if self.control_state == "canceled":
            return "duplicate"
        return self._append_once(
            f"control:{len([e for e in self.events if e['eventType'] == 'campaign_control']) + 1}:canceled",
            "campaign_control",
            {"state": "canceled"},
        )

    def reserve_budget(
        self,
        category: str,
        amount: float,
        *,
        operation_key: str,
        item_id: str | None = None,
        detail: str,
    ) -> str:
        self._require_active()
        if category not in BUDGET_CATEGORIES:
            raise BatchCampaignError("unsupported budget category")
        amount = _number(amount, "budget amount", minimum=0.000001)
        event_key = f"budget:{category}:{operation_key}"
        payload = {
            "category": category,
            "amount": amount,
            "operationKey": operation_key,
            "itemId": item_id,
            "detail": reels._nonempty(detail, "budget detail"),
        }
        existing = self.by_key.get(event_key)
        if existing is not None:
            if existing["eventType"] != "budget_reserved" or existing["payload"] != payload:
                raise BatchConflict(f"budget reservation conflict for {operation_key}")
            return "duplicate"
        ceiling = float(self.config.budget[category])
        if self.budget_spent[category] + amount > ceiling + 1e-9:
            raise BudgetExceeded(
                f"{category} budget would exceed ceiling {ceiling}: "
                f"{self.budget_spent[category]} + {amount}"
            )
        return self._append_once(event_key, "budget_reserved", payload)

    def next_provider_action_key(self, item_id: str, action: str) -> str:
        count = sum(
            1
            for reservation in self.budget_reservations
            if reservation["category"] == "provider_actions"
            and reservation["itemId"] == item_id
        )
        return f"{item_id}:provider-action:{count + 1}:{action}"

    def begin_operation(self, *, item_id: str | None, kind: str, operation_key: str) -> str:
        self._require_active()
        if kind not in CONCURRENCY_KINDS:
            raise BatchCampaignError("unsupported concurrency kind")
        start_key = f"operation:{operation_key}:start"
        if start_key in self.by_key:
            return "duplicate"
        active = sum(1 for op in self.inflight.values() if op["kind"] == kind)
        limit = int(self.config.max_concurrency[kind])
        if active >= limit:
            raise ConcurrencyLimitExceeded(f"{kind} concurrency ceiling {limit} reached")
        return self._append_once(
            start_key,
            "operation_started",
            {"operationKey": operation_key, "itemId": item_id, "kind": kind},
        )

    def finish_operation(
        self,
        *,
        operation_key: str,
        outcome: str,
    ) -> str:
        start_key = f"operation:{operation_key}:start"
        if start_key not in self.by_key:
            raise BatchConflict("cannot finish an operation that was never started")
        return self._append_once(
            f"operation:{operation_key}:finish",
            "operation_finished",
            {"operationKey": operation_key, "outcome": reels._nonempty(outcome, "outcome")},
        )

    def _platform_slots(self) -> list[str]:
        remaining = {p: int(self.config.platform_mix.get(p, 0)) for p in PLATFORM_ORDER}
        result: list[str] = []
        while len(result) < self.config.batch_size:
            progressed = False
            for platform in PLATFORM_ORDER:
                if remaining[platform] > 0:
                    result.append(platform)
                    remaining[platform] -= 1
                    progressed = True
            if not progressed:
                break
        if len(result) != self.config.batch_size:
            raise BatchCampaignError("platform mix did not produce expected slots")
        return result

    def select_concepts(self, candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        self._require_active()
        if self.items:
            return sorted((_clone(v) for v in self.items.values()), key=lambda x: x["ordinal"])
        if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
            raise BatchCampaignError("concept candidates must be an array")
        selected: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        hook_families: Counter[str] = Counter()
        platform_slots = self._platform_slots()
        start = reels._parse_time(self.config.publish_window_start, "publish_window_start")
        for candidate_index, raw in enumerate(candidates):
            if len(selected) >= self.config.batch_size:
                break
            if not isinstance(raw, Mapping):
                raise BatchCampaignError("concept candidate must be an object")
            title = reels._nonempty(raw.get("title"), "concept title")
            hook = reels._nonempty(raw.get("hook"), "concept hook")
            angle = reels._nonempty(raw.get("angle"), "concept angle")
            concept_text = f"{title} {angle}"
            duplicate_of = None
            for prior in selected:
                prior_text = f"{prior['concept']['title']} {prior['concept']['angle']}"
                if semantic_similarity(concept_text, prior_text) >= self.config.concept_similarity_threshold:
                    duplicate_of = prior["itemId"]
                    break
            signature = hook_signature(hook)
            family = hook_family(hook)
            hook_duplicate = any(prior["concept"]["hookSignature"] == signature for prior in selected)
            family_full = hook_families[family] >= self.config.max_hook_family_reuse
            if duplicate_of is not None or hook_duplicate or family_full:
                reason = (
                    "semantic_duplicate"
                    if duplicate_of is not None
                    else "hook_signature_duplicate"
                    if hook_duplicate
                    else "hook_family_limit"
                )
                rejection = {
                    "candidateIndex": candidate_index,
                    "title": title,
                    "hook": hook,
                    "angle": angle,
                    "reason": reason,
                    "duplicateOf": duplicate_of,
                }
                self._append_once(
                    f"candidate-rejected:{candidate_index}:{reels.sha256_json(rejection)}",
                    "candidate_rejected",
                    rejection,
                )
                rejected.append(rejection)
                continue
            ordinal = len(selected)
            platform = platform_slots[ordinal]
            planned = start + timedelta(seconds=float(self.config.stagger_seconds) * ordinal)
            item_id = "batchitem1:" + reels.sha256_json({
                "campaignId": self.campaign_id,
                "ordinal": ordinal,
                "title": title,
                "hook": hook,
                "angle": angle,
                "platform": platform,
            })
            item = {
                "itemId": item_id,
                "ordinal": ordinal,
                "platform": platform,
                "concept": {
                    "title": title,
                    "hook": hook,
                    "angle": angle,
                    "semanticDigest": reels.sha256_json({
                        "tokens": sorted(set(_semantic_words(concept_text)))
                    }),
                    "hookSignature": signature,
                    "hookFamily": family,
                },
                "schedule": {
                    "plannedAt": _iso_utc(planned),
                    "windowStart": self.config.publish_window_start,
                    "windowEnd": self.config.publish_window_end,
                    "staggerSeconds": float(self.config.stagger_seconds),
                },
                "state": "concept_selected",
                "script": None,
                "assetPlan": None,
                "media": None,
                "qa": None,
                "releaseAuthorization": None,
                "publishRequest": None,
                "publishReceipt": None,
                "growthHandoff": None,
                "growthAcknowledgement": None,
            }
            self._append_once(f"item:{item_id}:create", "item_created", item)
            selected.append(_clone(item))
            hook_families[family] += 1
        if len(selected) != self.config.batch_size:
            raise SemanticDuplicate(
                f"only {len(selected)} distinct concepts survived for batch size {self.config.batch_size}"
            )
        return selected

    def _item(self, item_id: str) -> dict[str, Any]:
        try:
            return self.items[item_id]
        except KeyError as exc:
            raise BatchCampaignError(f"unknown item {item_id}") from exc

    def record_script(self, item_id: str, script: Mapping[str, Any]) -> str:
        self._require_active()
        item = self._item(item_id)
        if item["state"] not in {"concept_selected", "scripted"}:
            raise BatchCampaignError("script can only be committed after concept selection")
        text = reels._nonempty(script.get("text"), "script text")
        revision = script.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise BatchCampaignError("script revision must be >= 1")
        digest = reels.sha256_text(text)
        normalized = {"revision": revision, "text": text, "sha256": digest}
        for other_id, other in self.items.items():
            if other_id == item_id or other["script"] is None:
                continue
            if semantic_similarity(text, other["script"]["text"]) >= self.config.script_similarity_threshold:
                raise SemanticDuplicate(f"script for {item_id} semantically duplicates {other_id}")
        return self._append_once(
            f"item:{item_id}:script",
            "item_stage",
            {"itemId": item_id, "field": "script", "value": normalized, "state": "scripted"},
        )

    def record_asset_plan(self, item_id: str, asset_plan: Mapping[str, Any]) -> str:
        self._require_active()
        item = self._item(item_id)
        if item["script"] is None:
            raise BatchCampaignError("asset plan requires script")
        return self._append_once(
            f"item:{item_id}:asset-plan",
            "item_stage",
            {"itemId": item_id, "field": "assetPlan", "value": _clone(asset_plan), "state": "asset_planned"},
        )

    def mark_blocked_media(self, item_id: str, reason: str) -> str:
        item = self._item(item_id)
        return self._append_once(
            f"item:{item_id}:blocked-media",
            "item_stage",
            {
                "itemId": item_id,
                "field": "media",
                "value": {"state": "blocked_media", "reason": reels._nonempty(reason, "reason")},
                "state": "blocked_media",
            },
        )

    def record_media(
        self,
        item_id: str,
        media: Mapping[str, Any],
        *,
        media_pin: r13.MediaAcceptancePin,
        profile_digest: str,
        allow_synthetic_fixture: bool,
    ) -> str:
        self._require_active()
        item = self._item(item_id)
        if item["assetPlan"] is None:
            raise BatchCampaignError("Media result requires asset plan")
        validated = reels.validate_media_r11_envelope(
            media,
            expected_producer_sha=media_pin.producer_sha,
            expected_job_contract_blob_sha=media_pin.job_contract_blob_sha,
            expected_manifest_contract_blob_sha=media_pin.artifact_manifest_contract_blob_sha,
            expected_profile_digest=profile_digest,
            allow_synthetic_fixture=allow_synthetic_fixture,
        )
        return self._append_once(
            f"item:{item_id}:media",
            "item_stage",
            {"itemId": item_id, "field": "media", "value": validated, "state": "media_ready"},
        )

    def record_qa(self, item_id: str, *, passed: bool, checks: Sequence[Mapping[str, Any]]) -> str:
        self._require_active()
        item = self._item(item_id)
        if not isinstance(item["media"], Mapping) or item["media"].get("state") == "blocked_media":
            raise BatchCampaignError("QA requires a successful Media result")
        qa = {
            "passed": bool(passed),
            "checks": _clone(list(checks)),
        }
        qa["qaDigest"] = reels.sha256_json(qa)
        state = "awaiting_release" if passed else "qa_failed"
        return self._append_once(
            f"item:{item_id}:qa",
            "item_stage",
            {"itemId": item_id, "field": "qa", "value": qa, "state": state},
        )

    def attach_release_authorization(self, item_id: str, authorization: Mapping[str, Any]) -> str:
        self._require_active()
        item = self._item(item_id)
        if not isinstance(item["qa"], Mapping) or item["qa"].get("passed") is not True:
            raise ReleaseRequired("release authorization requires passing QA")
        media = item["media"]
        manifest = media["artifactManifest"]
        destination = f"fixture-{item['platform']}-destination"
        validated = reels._validate_release_authorization(
            authorization,
            manifest["content"]["contentId"],
            manifest["content"]["sha256"],
            item["platform"],
            destination,
        )
        return self._append_once(
            f"item:{item_id}:release",
            "item_stage",
            {
                "itemId": item_id,
                "field": "releaseAuthorization",
                "value": validated,
                "state": "ready",
            },
        )

    def record_publish_request(self, item_id: str, request: Mapping[str, Any]) -> str:
        self._require_active()
        item = self._item(item_id)
        if item["releaseAuthorization"] is None:
            raise ReleaseRequired("Growth advisory cannot substitute for release.authorization.v1")
        return self._append_once(
            f"item:{item_id}:publish-request",
            "item_stage",
            {"itemId": item_id, "field": "publishRequest", "value": _clone(request), "state": "ready"},
        )

    def record_publish_receipt(self, item_id: str, receipt: Mapping[str, Any]) -> str:
        self._require_active()
        item = self._item(item_id)
        if item["publishRequest"] is None:
            raise BatchCampaignError("publish receipt requires durable publish request")
        validated = r12.validate_provider_receipt(
            receipt,
            item["publishRequest"],
            allow_synthetic_fixture=(
                item["publishRequest"]["media"]["sourceClass"] == "synthetic_fixture"
            ),
        )
        return self._append_once(
            f"item:{item_id}:publish-receipt",
            "item_stage",
            {
                "itemId": item_id,
                "field": "publishReceipt",
                "value": validated,
                "state": "analytics_pending",
            },
        )

    def record_growth_handoff(self, item_id: str, handoff: Mapping[str, Any]) -> str:
        self._require_active()
        item = self._item(item_id)
        if item["publishReceipt"] is None:
            raise BatchCampaignError("Growth handoff requires provider receipt")
        expected_live = (
            item["publishReceipt"]["sourceClass"] == "provider_receipt"
            and item["publishRequest"]["media"]["sourceClass"] == "provider"
        )
        if handoff.get("livePerformanceClaimEligible") is not expected_live:
            raise BatchCampaignError("Growth handoff live/synthetic provenance mismatch")
        return self._append_once(
            f"item:{item_id}:growth-handoff",
            "item_stage",
            {
                "itemId": item_id,
                "field": "growthHandoff",
                "value": _clone(handoff),
                "state": "analytics_pending",
            },
        )

    def acknowledge_growth_handoff(self, item_id: str, acknowledgement: Mapping[str, Any]) -> str:
        self._require_active()
        item = self._item(item_id)
        if item["growthHandoff"] is None:
            raise BatchCampaignError("Growth acknowledgement requires handoff")
        value = {
            "sourceBound": True,
            "handoffDigest": item["growthHandoff"]["handoffDigest"],
            "acknowledgementDigest": reels.sha256_json(acknowledgement),
        }
        return self._append_once(
            f"item:{item_id}:growth-ack",
            "item_stage",
            {
                "itemId": item_id,
                "field": "growthAcknowledgement",
                "value": value,
                "state": "published",
            },
        )

    def assert_publish_window(self, item_id: str, *, now: str) -> None:
        item = self._item(item_id)
        current = reels._parse_time(now, "now")
        start = reels._parse_time(item["schedule"]["windowStart"], "windowStart")
        end = reels._parse_time(item["schedule"]["windowEnd"], "windowEnd")
        planned = reels._parse_time(item["schedule"]["plannedAt"], "plannedAt")
        if current < start or current > end:
            raise PublishWindowBlocked("current time is outside campaign publish window")
        if current < planned:
            raise PublishWindowBlocked("item staggered publish time has not arrived")

    def summary(self) -> dict[str, Any]:
        counts = {state: 0 for state in SUMMARY_STATES}
        for item in self.items.values():
            state = item["state"]
            if state in counts:
                counts[state] += 1
        budget = {}
        for category in BUDGET_CATEGORIES:
            ceiling = float(self.config.budget[category])
            spent = float(self.budget_spent[category])
            budget[category] = {
                "spent": spent,
                "ceiling": ceiling,
                "remaining": round(ceiling - spent, 8),
            }
        report = {
            "contractVersion": BATCH_REPORT_VERSION,
            "campaignId": self.campaign_id,
            "controlState": self.control_state,
            "batchSize": self.config.batch_size,
            "itemCount": len(self.items),
            "states": counts,
            "rejectedCandidateCount": len(self.rejected_candidates),
            "budget": budget,
            "maxObservedConcurrency": dict(self.max_observed_concurrency),
            "inflightOperations": sorted(self.inflight),
            "growthAdvisory": self.growth_advisory,
            "eventCount": len(self.events),
            "ledgerDigest": reels.sha256_json(self.events),
        }
        report["reportDigest"] = reels.sha256_json(report)
        return report


class DeterministicBatchSynthesizer:
    _angles = (
        "pacing reset", "caption hierarchy", "visual proof", "audio contrast",
        "pattern interrupt", "before-after", "micro tutorial", "myth correction",
        "workflow shortcut", "mistake teardown", "checklist reveal", "result first",
        "timeline cleanup", "CTA placement", "retention beat", "proof stack",
    )
    _hooks = (
        "Stop wasting your opening second.",
        "Watch how one cut changes the pace.",
        "Three seconds decide whether viewers stay.",
        "Before you add effects fix this first.",
        "Most creators hide the proof too late.",
        "Try this pacing reset on your next short.",
        "Here is the edit viewers actually notice.",
        "Your first caption can do more work.",
        "Cut this dead space before you publish.",
        "Notice what happens when proof comes first.",
        "Use one visual change to reset attention.",
        "The fastest edit is often the cleanest.",
        "Fix the audio contrast before adding motion.",
        "Lead with the result then explain the method.",
        "Show the mistake before showing the fix.",
        "Compare these two cuts and pick the clearer one.",
    )

    def generate_candidates(
        self,
        *,
        brief: Mapping[str, Any],
        count: int,
        inject_duplicates: bool = False,
    ) -> list[dict[str, str]]:
        topic = reels._nonempty(brief.get("topic"), "brief topic")
        _positive_int(count, "candidate count", maximum=100)
        unique: list[dict[str, str]] = []
        for index in range(count):
            angle = self._angles[index % len(self._angles)]
            hook = self._hooks[index % len(self._hooks)]
            unique.append({
                "title": f"{topic}: {angle} #{index + 1}",
                "hook": hook,
                "angle": f"{angle} with deterministic example {index + 1}",
            })
        if inject_duplicates and len(unique) >= 3:
            duplicate_exact = dict(unique[1])
            duplicate_near = {
                "title": unique[2]["title"].upper(),
                "hook": unique[2]["hook"],
                "angle": unique[2]["angle"] + "!",
            }
            return [duplicate_exact, unique[0], unique[1], duplicate_near, *unique[2:]]
        return unique

    def script_for(self, item: Mapping[str, Any]) -> dict[str, Any]:
        concept = item["concept"]
        text = (
            f"{concept['hook']} "
            f"Segment {item['ordinal'] + 1} demonstrates {concept['angle']}. "
            f"Show evidence unique to reel {item['ordinal'] + 1}, then close with one concrete action."
        )
        return {"revision": 1, "text": text}

    def asset_plan_for(self, item: Mapping[str, Any]) -> dict[str, Any]:
        ordinal = item["ordinal"] + 1
        return {
            "assets": [{
                "assetId": f"r14-asset-{ordinal}",
                "sourceUri": f"fixture://r14/assets/{ordinal}",
                "sha256": reels.sha256_json({"asset": ordinal}),
                "rightsRef": f"fixture-rights-r14-{ordinal}",
            }]
        }

    def edit_request_for(self, item: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
        ordinal = item["ordinal"] + 1
        return {
            "voice": {"mode": "voiceover", "sourceRef": f"fixture://r14/voice/{ordinal}"},
            "music": {"assetRef": f"fixture://r14/music/{ordinal}", "duckUnderVoiceDb": -9},
            "subtitles": {"enabled": True, "language": "en", "burnIn": True},
            "edit": {
                "trim": True,
                "cuts": "beat-aligned",
                "reframe": "center-subject",
                "transitions": "requested-only",
                "ctaOutroSeconds": 2.0,
            },
            "profileDigest": profile["profileDigest"],
        }


class TerminalMediaFailureProvider:
    def __init__(self) -> None:
        self.submit_calls = 0
        self.accepted_effects = 0

    def submit(self, request: Mapping[str, Any], profile: Mapping[str, Any]) -> Mapping[str, Any]:
        self.submit_calls += 1
        self.accepted_effects += 1
        raise InjectedMediaFailure("injected deterministic Media terminal failure")


class BudgetedPublishProvider:
    def __init__(
        self,
        *,
        ledger: BatchCampaignLedger,
        item_id: str,
        provider: Any,
    ) -> None:
        self.ledger = ledger
        self.item_id = item_id
        self.provider = provider
        self.platform = provider.platform
        self.source_class = provider.source_class

    def _charge(self, action: str) -> None:
        key = self.ledger.next_provider_action_key(self.item_id, action)
        self.ledger.reserve_budget(
            "provider_actions",
            1.0,
            operation_key=key,
            item_id=self.item_id,
            detail=f"publish-provider:{action}",
        )

    def prepare(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self._charge("prepare")
        return self.provider.prepare(request)

    def recover(self, idempotency_key: str) -> Mapping[str, Any]:
        self._charge("recover")
        return self.provider.recover(idempotency_key)

    def submit(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self._charge("submit")
        return self.provider.submit(request)

    def status(self, operation_ref: str) -> Mapping[str, Any]:
        self._charge("status")
        return self.provider.status(operation_ref)


def build_release_authorization(
    *,
    campaign_id: str,
    item: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = item["media"]["artifactManifest"]
    item_token = reels.sha256_json({
        "campaignId": campaign_id,
        "itemId": item["itemId"],
        "artifact": manifest["content"]["contentId"],
        "platform": item["platform"],
    })[:20]
    destination = f"fixture-{item['platform']}-destination"
    return {
        "contractVersion": reels.RELEASE_AUTHORIZATION_VERSION,
        "decisionId": f"r14-decision-{item_token}",
        "idempotencyKey": f"r14-release-auth-{item_token}",
        "requestId": f"r14-release-request-{item_token}",
        "campaignId": campaign_id,
        "candidateId": item["itemId"],
        "artifactId": manifest["content"]["contentId"],
        "artifactHash": f"sha256:{manifest['content']['sha256']}",
        "lineageHash": "sha256:" + reels.sha256_json({
            "campaignId": campaign_id,
            "itemId": item["itemId"],
            "script": item["script"]["sha256"],
        }),
        "destinationScope": {
            "provider": item["platform"],
            "destination": destination,
            "action": "release",
        },
        "decision": "approved",
        "authorizationId": f"r14-authorization-{item_token}",
        "expiresAt": "2026-10-02T00:00:00Z",
        "decidedAt": "2026-10-01T00:00:00Z",
        "decisionSource": "external",
        "approverRef": "fixture-human-approver-r14",
    }


class BatchCampaignRunner:
    def __init__(
        self,
        *,
        ledger: BatchCampaignLedger,
        work_dir: str | os.PathLike[str],
        media_pin: r13.MediaAcceptancePin | None,
        allow_synthetic_media: bool = False,
    ) -> None:
        self.ledger = ledger
        self.work_dir = Path(work_dir)
        self.media_pin = media_pin
        self.allow_synthetic_media = allow_synthetic_media

    def plan_concepts(
        self,
        synthesizer: DeterministicBatchSynthesizer,
        *,
        candidate_count: int,
        inject_duplicates: bool = False,
    ) -> list[dict[str, Any]]:
        if self.ledger.items:
            return sorted((_clone(v) for v in self.ledger.items.values()), key=lambda x: x["ordinal"])
        op = f"{self.ledger.campaign_id}:concept-generation"
        self.ledger.begin_operation(item_id=None, kind="generation", operation_key=op)
        predicted_candidates = candidate_count + (2 if inject_duplicates else 0)
        self.ledger.reserve_budget(
            "generation_units",
            float(predicted_candidates),
            operation_key=op,
            detail="concept-candidate-generation",
        )
        candidates = synthesizer.generate_candidates(
            brief=self.ledger.brief,
            count=candidate_count,
            inject_duplicates=inject_duplicates,
        )
        items = self.ledger.select_concepts(candidates)
        self.ledger.finish_operation(operation_key=op, outcome="selected")
        return items

    def generate_script_and_assets(
        self,
        item_id: str,
        synthesizer: DeterministicBatchSynthesizer,
    ) -> None:
        item = self.ledger._item(item_id)
        if item["assetPlan"] is not None:
            return
        op = f"{item_id}:creative-generation"
        self.ledger.begin_operation(item_id=item_id, kind="generation", operation_key=op)
        if item["script"] is None:
            self.ledger.reserve_budget(
                "generation_units",
                1.0,
                operation_key=f"{item_id}:script-generation",
                item_id=item_id,
                detail="script-generation",
            )
            self.ledger.record_script(item_id, synthesizer.script_for(item))
        if self.ledger._item(item_id)["assetPlan"] is None:
            self.ledger.reserve_budget(
                "generation_units",
                1.0,
                operation_key=f"{item_id}:asset-plan-generation",
                item_id=item_id,
                detail="asset-plan-generation",
            )
            self.ledger.record_asset_plan(item_id, synthesizer.asset_plan_for(self.ledger._item(item_id)))
        self.ledger.finish_operation(operation_key=op, outcome="planned")

    def render_item(
        self,
        item_id: str,
        *,
        media_provider: Any,
        synthesizer: DeterministicBatchSynthesizer,
        render_seconds: float = 30.0,
    ) -> str:
        item = self.ledger._item(item_id)
        if item["state"] in {"blocked_media", "media_ready", "awaiting_release", "ready", "analytics_pending", "published", "qa_failed"}:
            return item["state"]
        if self.media_pin is None:
            self.ledger.mark_blocked_media(item_id, "BLOCKED_MEDIA: exact compatible Media R11 pin unavailable")
            return "blocked_media"
        readiness = r13.readiness_report(self.media_pin)
        if readiness["overall"] == "BLOCKED_MEDIA":
            self.ledger.mark_blocked_media(item_id, "BLOCKED_MEDIA: " + readiness["gates"]["mediaR11"]["reason"])
            return "blocked_media"
        self.media_pin.validate()
        if item["assetPlan"] is None or item["script"] is None:
            raise BatchCampaignError("render requires script and asset plan")
        profile = r13._profile(item["platform"])
        edit_request = synthesizer.edit_request_for(item, profile)
        media_request = r13.build_media_request(
            cycle_id=f"{self.ledger.campaign_id}:{item_id}",
            profile=profile,
            script=item["script"],
            asset_plan=item["assetPlan"],
            edit_request=edit_request,
        )
        operation_key = f"{item_id}:media-render"
        self.ledger.begin_operation(item_id=item_id, kind="media", operation_key=operation_key)
        self.ledger.reserve_budget(
            "render_seconds",
            float(render_seconds),
            operation_key=operation_key,
            item_id=item_id,
            detail="media-render",
        )
        try:
            result = media_provider.submit(media_request, profile)
        except InjectedMediaFailure as exc:
            self.ledger.mark_blocked_media(item_id, f"Media terminal failure: {exc}")
            self.ledger.finish_operation(operation_key=operation_key, outcome="failed")
            return "blocked_media"
        self.ledger.record_media(
            item_id,
            result,
            media_pin=self.media_pin,
            profile_digest=profile["profileDigest"],
            allow_synthetic_fixture=self.allow_synthetic_media,
        )
        self.ledger.finish_operation(operation_key=operation_key, outcome="succeeded")
        return "media_ready"

    def qa_item(self, item_id: str, *, passed: bool) -> str:
        item = self.ledger._item(item_id)
        if item["qa"] is not None:
            return item["state"]
        checks = [
            {"name": "batch-hook-diversity", "pass": True},
            {"name": "media-source-bound", "pass": True},
            {"name": "campaign-qa", "pass": bool(passed)},
        ]
        self.ledger.record_qa(item_id, passed=passed, checks=checks)
        return self.ledger._item(item_id)["state"]

    def authorize_item(self, item_id: str) -> str:
        item = self.ledger._item(item_id)
        if item["releaseAuthorization"] is not None:
            return "ready"
        if item["state"] != "awaiting_release":
            raise ReleaseRequired("item is not awaiting an external release decision")
        auth = build_release_authorization(
            campaign_id=self.ledger.campaign_id,
            item=item,
        )
        self.ledger.attach_release_authorization(item_id, auth)
        return "ready"

    def _publish_request(self, item_id: str) -> dict[str, Any]:
        item = self.ledger._item(item_id)
        if item["releaseAuthorization"] is None:
            raise ReleaseRequired("publication requires external release.authorization.v1")
        if item["publishRequest"] is not None:
            return _clone(item["publishRequest"])
        manifest = item["media"]["artifactManifest"]
        profile = r13._profile(item["platform"])
        request = r12.build_publish_request(
            platform=item["platform"],
            account_id=f"fixture-{item['platform']}-account",
            destination=f"fixture-{item['platform']}-destination",
            credential_ref=f"vault-ref://{item['platform']}/r14-fixture",
            authorization_lineage={
                "credentialRef": f"vault-ref://{item['platform']}/r14-fixture",
                "authorizationRef": f"oauth-grant-ref://{item['platform']}/r14-fixture",
            },
            media={
                "sourceClass": item["media"]["sourceClass"],
                "contentId": manifest["content"]["contentId"],
                "contentSha256": manifest["content"]["sha256"],
                "sizeBytes": manifest["content"]["size"],
                "contentType": "video/mp4",
                "durationSeconds": float(manifest["probeEvidence"]["value"]["durationMs"]) / 1000.0,
                "aspectRatio": "9:16",
                "manifestDigest": reels.sha256_json(manifest),
            },
            caption=profile["metadata"]["caption"],
            cta=profile["metadata"]["cta"],
            release_authorization=item["releaseAuthorization"],
            allow_synthetic_fixture=self.allow_synthetic_media,
        )
        self.ledger.record_publish_request(item_id, request)
        return request

    def publish_item(self, item_id: str, *, provider: Any, now: str) -> dict[str, Any]:
        self.ledger._require_active()
        item = self.ledger._item(item_id)
        if item["publishReceipt"] is not None:
            return {"state": item["state"], "receipt": _clone(item["publishReceipt"])}
        if item["releaseAuthorization"] is None:
            raise ReleaseRequired("Growth advisory is non-authoritative; release.authorization.v1 is required")
        self.ledger.assert_publish_window(item_id, now=now)
        request = self._publish_request(item_id)
        operation_key = f"{item_id}:provider-publish"
        self.ledger.begin_operation(item_id=item_id, kind="provider", operation_key=operation_key)
        coordinator = r12.DurablePublishCoordinator(
            self.work_dir / "publish" / f"{reels.sha256_text(item_id)}.jsonl",
            request,
            allow_synthetic_fixture=self.allow_synthetic_media,
        )
        budgeted = BudgetedPublishProvider(
            ledger=self.ledger,
            item_id=item_id,
            provider=provider,
        )
        outcome: dict[str, Any] = {"state": "recoverable_unknown", "receipt": None}
        for attempt in range(8):
            outcome = coordinator.drive(
                budgeted,
                now=now,
            )
            if outcome["state"] in {"published", "failed_terminal", "waiting_for_credentials"}:
                break
        if outcome["state"] == "published" and outcome["receipt"] is not None:
            self.ledger.record_publish_receipt(item_id, outcome["receipt"])
            handoff = r12.build_growth_handoff(
                outcome["receipt"],
                request,
                allow_synthetic_fixture=self.allow_synthetic_media,
            )
            self.ledger.record_growth_handoff(item_id, handoff)
            self.ledger.finish_operation(operation_key=operation_key, outcome="published")
        elif outcome["state"] == "failed_terminal":
            self.ledger.finish_operation(operation_key=operation_key, outcome="failed_terminal")
        return outcome

    def acknowledge_growth(self, item_id: str) -> str:
        item = self.ledger._item(item_id)
        if item["growthHandoff"] is None:
            raise BatchCampaignError("item has no Growth handoff")
        self.ledger.acknowledge_growth_handoff(
            item_id,
            {
                "consumer": "growth-r11-synthetic-acceptance",
                "sourceDigest": item["growthHandoff"]["handoffDigest"],
                "publicationAuthority": False,
            },
        )
        return "published"

    def report(self) -> dict[str, Any]:
        report = self.ledger.summary()
        report["creatorR13BaseSha"] = CREATOR_R13_BASE_SHA
        report["growthR11Source"] = r13.growth_r11_source_pin()
        report["mediaReadiness"] = r13.readiness_report(self.media_pin)
        report["livePublishing"] = False
        report["credentialsPresent"] = False
        report["reportDigest"] = reels.sha256_json({
            key: value for key, value in report.items() if key != "reportDigest"
        })
        return report


def default_synthetic_config() -> BatchCampaignConfig:
    return BatchCampaignConfig(
        batch_size=12,
        platform_mix={
            "instagram_reels": 4,
            "tiktok": 4,
            "youtube_shorts": 4,
        },
        max_concurrency={
            "generation": 3,
            "media": 2,
            "provider": 2,
        },
        budget={
            "generation_units": 50.0,
            "render_seconds": 360.0,
            "provider_actions": 80.0,
        },
        publish_window_start="2026-10-01T00:00:00Z",
        publish_window_end="2026-10-01T00:10:00Z",
        stagger_seconds=0.2,
        concept_similarity_threshold=0.75,
        script_similarity_threshold=0.90,
        max_hook_family_reuse=2,
    ).validate()


def synthetic_media_pin() -> r13.MediaAcceptancePin:
    observed = r13.MEDIA_OBSERVED_CANDIDATE
    return r13.MediaAcceptancePin(
        producer_sha=observed["producerSha"],
        job_contract_blob_sha=observed["jobContractBlobSha"],
        artifact_manifest_contract_blob_sha=observed["artifactManifestContractBlobSha"],
        conformance_manifest_blob_sha=observed["conformanceManifestBlobSha"],
        creator_consumer_blob_sha=observed["creatorConsumerBlobSha"],
        ci_run_id="creator-r14-synthetic-conformance-only",
        ci_conclusion="success",
    )


def _provider_for(platform: str, *, crash_after_effect_once: bool = False):
    if platform == "instagram_reels":
        return r12.InstagramReelsMockProvider(crash_after_effect_once=crash_after_effect_once)
    if platform == "tiktok":
        return r12.TikTokMockProvider(crash_after_effect_once=crash_after_effect_once)
    if platform == "youtube_shorts":
        return r12.YouTubeShortsMockProvider(crash_after_effect_once=crash_after_effect_once)
    raise BatchCampaignError("unsupported platform")


def run_synthetic_12_campaign(work_dir: str | os.PathLike[str]) -> dict[str, Any]:
    root = Path(work_dir)
    config = default_synthetic_config()
    brief = {
        "goal": "Produce a diverse deterministic batch of short-form editing education videos",
        "topic": "short-form editing",
        "audience": "creators",
        "constraints": {
            "noDuplicateIdeas": True,
            "noLivePublishing": True,
            "batchSize": 12,
        },
    }
    advisory = {
        "contract_version": "growth.reels_next_cycle_seed.v1",
        "source_class": "synthetic_fixture",
        "recommendations": [
            {
                "action": "test faster proof placement",
                "certainty": "directional_not_causal",
            }
        ],
        "authority": {
            "publish_authorized": True,
            "release_authorized": True,
        },
    }
    ledger = BatchCampaignLedger(
        root / "campaign.jsonl",
        campaign_id="creator-r14-synthetic-12",
        brief=brief,
        config=config,
        growth_advisory=advisory,
    )
    pin = synthetic_media_pin()
    runner = BatchCampaignRunner(
        ledger=ledger,
        work_dir=root,
        media_pin=pin,
        allow_synthetic_media=True,
    )
    synth = DeterministicBatchSynthesizer()
    items = runner.plan_concepts(
        synth,
        candidate_count=12,
        inject_duplicates=True,
    )
    # Two injected duplicates mean the generator returns 14 candidates; the budget reserves
    # all 14 candidate-generation units before generation and selection still yields 12.
    for item in items:
        runner.generate_script_and_assets(item["itemId"], synth)

    media_provider = r13.MockMediaAcceptanceProvider(pin)
    media_failure = TerminalMediaFailureProvider()
    for item in items:
        provider = media_failure if item["ordinal"] == 0 else media_provider
        runner.render_item(
            item["itemId"],
            media_provider=provider,
            synthesizer=synth,
        )

    for item in items:
        current = ledger._item(item["itemId"])
        if current["state"] == "blocked_media":
            continue
        runner.qa_item(item["itemId"], passed=item["ordinal"] != 1)

    for item in items:
        current = ledger._item(item["itemId"])
        if current["state"] != "awaiting_release":
            continue
        if item["ordinal"] == 2:
            continue
        runner.authorize_item(item["itemId"])

    providers: dict[str, Any] = {}
    lost_ack_restart_count = 0
    for item in items:
        ordinal = item["ordinal"]
        current = ledger._item(item["itemId"])
        if current["state"] != "ready" or ordinal == 3:
            continue
        crash = ordinal == 6
        provider = _provider_for(item["platform"], crash_after_effect_once=crash)
        providers[item["itemId"]] = provider
        try:
            runner.publish_item(
                item["itemId"],
                provider=provider,
                now=item["schedule"]["plannedAt"],
            )
        except reels.InjectedCrash:
            if not crash:
                raise
            lost_ack_restart_count += 1
            ledger = BatchCampaignLedger(
                root / "campaign.jsonl",
                campaign_id="creator-r14-synthetic-12",
                brief=brief,
                config=config,
                growth_advisory=advisory,
            )
            runner = BatchCampaignRunner(
                ledger=ledger,
                work_dir=root,
                media_pin=pin,
                allow_synthetic_media=True,
            )
            runner.publish_item(
                item["itemId"],
                provider=provider,
                now=item["schedule"]["plannedAt"],
            )

    published_ids = [
        item["itemId"]
        for item in sorted(ledger.items.values(), key=lambda value: value["ordinal"])
        if item["state"] == "analytics_pending"
    ]
    if not published_ids:
        raise BatchCampaignError("synthetic campaign produced no published receipts")
    analytics_pending_id = published_ids[-1]
    for item_id in published_ids:
        if item_id != analytics_pending_id:
            runner.acknowledge_growth(item_id)

    report = runner.report()
    report["syntheticReplay"] = {
        "requestedBatchSize": 12,
        "candidateCountWithInjectedDuplicates": 14,
        "duplicateCandidatesRejected": ledger.summary()["rejectedCandidateCount"],
        "mediaTerminalFailures": media_failure.accepted_effects,
        "qaFailures": sum(1 for item in ledger.items.values() if item["state"] == "qa_failed"),
        "lostPublishAcknowledgementRestarts": lost_ack_restart_count,
        "publishLogicalEffects": sum(provider.accepted_effects for provider in providers.values()),
        "publishSubmitCalls": sum(provider.submit_calls for provider in providers.values()),
        "mediaLogicalEffects": media_provider.accepted_effects + media_failure.accepted_effects,
        "analyticsPendingItemId": analytics_pending_id,
    }
    report["reportDigest"] = reels.sha256_json({
        key: value for key, value in report.items() if key != "reportDigest"
    })
    return report


def _cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Creator R14 durable batch campaign runner")
    sub = parser.add_subparsers(dest="command", required=True)
    synthetic = sub.add_parser("synthetic-12")
    synthetic.add_argument("--work-dir", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _cli_parser().parse_args(argv)
    if args.command == "synthetic-12":
        report = run_synthetic_12_campaign(args.work_dir)
        print(json.dumps(report, sort_keys=True, indent=2))
        return 0
    raise SystemExit("unsupported command")


if __name__ == "__main__":
    raise SystemExit(main())
