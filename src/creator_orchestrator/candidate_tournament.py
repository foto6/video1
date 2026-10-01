from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import autonomous_reels as reels
from . import batch_campaign as r14

TOURNAMENT_VERSION = "creator.candidate_tournament.r15.v1"
TOURNAMENT_LEDGER_VERSION = "creator.candidate_tournament_ledger.r15.v1"
TOURNAMENT_CONFIG_VERSION = "creator.candidate_tournament_config.r15.v1"
CANDIDATE_REQUEST_VERSION = "creator.media_r12_candidate_request.r15.v1"
CANDIDATE_RESULT_VERSION = "creator.media_r12_candidate_result.r15.v1"
SELECTION_VERSION = "creator.candidate_selection.r15.v1"
REPLAY_REPORT_VERSION = "creator.candidate_tournament_replay.r15.v1"
CREATOR_R14_BASE_SHA = "6975917bb4f150936c76e749fb7248c8713b91cf"

MEDIA_R12_OBSERVED = {
    "repository": "foto6/video2",
    "branch": "agent/media-r12-creative-polish-20261001",
    "producerSha": "98f298b88faaef106fb412712d6c9824e2b926d9",
    "creativePlanManifestPath": "conformance/media.creative_edit_plan.r12.v1/manifest.json",
    "creativePlanManifestBlobSha": "d031a07f1d392c690942bd5f8288a1713f1af791",
    "creativePlanContractPath": "conformance/media.creative_edit_plan.r12.v1/contract.json",
    "creativePlanContractBlobSha": "5298aeb2a9e4e13ed31b1610ce88778b7a911592",
    "r11JobContractBlobSha": "96b252acae743f8fe059fd634ee320f92bd9c79c",
    "r11ArtifactManifestBlobSha": "42aed1ca4720cddd4a5e48af076bc73b663322b0",
    "creatorConsumerCompatibilityBlobSha": None,
    "exactHeadCiRunId": "36799818187",
    "exactHeadCiConclusion": "failure",
}

MEDIA_R12_HARD_GUARDRAILS = {
    "cutRatePerSecond": 1.25,
    "zoomRatePerSecond": 0.30,
    "transitionDensityPerSecond": 0.20,
    "textCharsPerSecond": 22.0,
    "musicGainDb": -10.0,
    "concurrentTextItems": 2.0,
    "motionZoom": 1.18,
}

DIMENSION_FIELDS = (
    "pacingPreset",
    "captionStyle",
    "brollDensity",
    "hookCut",
    "punchInPattern",
    "loopEnding",
    "ctaTreatment",
    "musicVoiceBalanceDb",
)

ALLOWED_DIMENSIONS = {
    "pacingPreset": {"steady", "tight", "aggressive", "breathable"},
    "captionStyle": {"minimal", "word_highlight", "kinetic"},
    "brollDensity": {"none", "light", "medium", "dense"},
    "hookCut": {"cold_open", "result_first", "pattern_interrupt", "question"},
    "punchInPattern": {"none", "subtle", "beat_punch"},
    "loopEnding": {"none", "soft_loop", "hard_loop"},
    "ctaTreatment": {"spoken", "text_endcard", "integrated", "none"},
}

CREATIVE_FIELDS = (
    "hookClarity",
    "pacingCoherence",
    "captionLegibility",
    "sourceEvidenceUse",
    "loopCoherence",
    "ctaClarity",
    "audioBalance",
)

CREATIVE_WEIGHTS = {
    "hookClarity": 0.20,
    "pacingCoherence": 0.20,
    "captionLegibility": 0.15,
    "sourceEvidenceUse": 0.20,
    "loopCoherence": 0.10,
    "ctaClarity": 0.10,
    "audioBalance": 0.05,
}


class CandidateTournamentError(ValueError):
    pass


class TournamentConflict(CandidateTournamentError):
    pass


class TournamentBudgetExceeded(CandidateTournamentError):
    pass


class TournamentConcurrencyExceeded(CandidateTournamentError):
    pass


class TournamentIncomplete(CandidateTournamentError):
    pass


class MediaR12Unavailable(CandidateTournamentError):
    pass


class InjectedTournamentCrash(RuntimeError):
    pass


def _clone(value: Any) -> Any:
    return json.loads(reels.canonical_json(value))


def _positive_int(value: Any, field: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CandidateTournamentError(f"{field} must be an integer >= 1")
    if maximum is not None and value > maximum:
        raise CandidateTournamentError(f"{field} must be <= {maximum}")
    return value


def _number(
    value: Any,
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateTournamentError(f"{field} must be numeric")
    number = float(value)
    if minimum is not None and number < minimum:
        raise CandidateTournamentError(f"{field} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise CandidateTournamentError(f"{field} must be <= {maximum}")
    return number


@dataclass(frozen=True)
class MediaR12ProducerPin:
    producer_sha: str
    creative_plan_manifest_blob_sha: str
    creative_plan_contract_blob_sha: str
    creator_consumer_compatibility_blob_sha: str
    exact_head_ci_run_id: str
    exact_head_ci_conclusion: str

    def validate(self) -> "MediaR12ProducerPin":
        reels._git_sha(self.producer_sha, "Media R12 producer_sha")
        reels._git_sha(
            self.creative_plan_manifest_blob_sha,
            "Media R12 creative_plan_manifest_blob_sha",
        )
        reels._git_sha(
            self.creative_plan_contract_blob_sha,
            "Media R12 creative_plan_contract_blob_sha",
        )
        reels._git_sha(
            self.creator_consumer_compatibility_blob_sha,
            "Media R12 creator_consumer_compatibility_blob_sha",
        )
        reels._nonempty(self.exact_head_ci_run_id, "Media R12 exact_head_ci_run_id")
        if self.exact_head_ci_conclusion != "success":
            raise MediaR12Unavailable("Media R12 exact-head CI is not successful")
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "repository": MEDIA_R12_OBSERVED["repository"],
            "branch": MEDIA_R12_OBSERVED["branch"],
            "producerSha": self.producer_sha,
            "creativePlanManifestBlobSha": self.creative_plan_manifest_blob_sha,
            "creativePlanContractBlobSha": self.creative_plan_contract_blob_sha,
            "creatorConsumerCompatibilityBlobSha": self.creator_consumer_compatibility_blob_sha,
            "exactHeadCiRunId": self.exact_head_ci_run_id,
            "exactHeadCiConclusion": self.exact_head_ci_conclusion,
        }


def media_r12_readiness(pin: MediaR12ProducerPin | None = None) -> dict[str, Any]:
    if pin is None:
        report = {
            "state": "BLOCKED_MEDIA_R12",
            "productionReady": False,
            "acceptedPin": None,
            "observedCandidate": dict(MEDIA_R12_OBSERVED),
            "missingOrFailed": [
                "creatorConsumerCompatibilityBlobSha",
                "exactHeadCiSuccess",
            ],
            "reason": (
                "Media R12 candidate lacks a Creator-consumer compatibility pin "
                "and exact-head CI run 36799818187 concluded failure"
            ),
        }
    else:
        try:
            pin.validate()
        except (CandidateTournamentError, reels.AutonomousReelsError) as exc:
            report = {
                "state": "BLOCKED_MEDIA_R12",
                "productionReady": False,
                "acceptedPin": None,
                "observedCandidate": dict(MEDIA_R12_OBSERVED),
                "missingOrFailed": ["compatibleAcceptedPin"],
                "reason": str(exc),
            }
        else:
            report = {
                "state": "MEDIA_R12_PIN_ACCEPTED",
                "productionReady": True,
                "acceptedPin": pin.as_dict(),
                "observedCandidate": dict(MEDIA_R12_OBSERVED),
                "missingOrFailed": [],
                "reason": "exact compatible Media R12 producer pin supplied",
            }
    report["readinessDigest"] = reels.sha256_json(report)
    return report


@dataclass(frozen=True)
class TournamentConfig:
    variant_count: int
    max_variants: int
    max_concurrency: int
    render_budget_seconds: float
    media_action_budget: int
    estimated_render_seconds: float = 30.0
    min_valid_candidates: int = 2
    tie_epsilon: float = 0.01

    def validate(self) -> "TournamentConfig":
        count = _positive_int(self.variant_count, "variant_count", maximum=8)
        maximum = _positive_int(self.max_variants, "max_variants", maximum=8)
        if count > maximum:
            raise CandidateTournamentError("variant_count exceeds max_variants")
        _positive_int(self.max_concurrency, "max_concurrency", maximum=8)
        _number(self.render_budget_seconds, "render_budget_seconds", minimum=0.001)
        _positive_int(self.media_action_budget, "media_action_budget", maximum=64)
        render = _number(
            self.estimated_render_seconds,
            "estimated_render_seconds",
            minimum=0.001,
        )
        minimum_valid = _positive_int(
            self.min_valid_candidates,
            "min_valid_candidates",
            maximum=maximum,
        )
        if minimum_valid > count:
            raise CandidateTournamentError(
                "min_valid_candidates cannot exceed variant_count"
            )
        _number(self.tie_epsilon, "tie_epsilon", minimum=0.0, maximum=1.0)
        if count * render > float(self.render_budget_seconds) + 1e-9:
            raise CandidateTournamentError(
                "configured variants cannot fit render budget"
            )
        if count > self.media_action_budget:
            raise CandidateTournamentError(
                "configured variants cannot fit media-action budget"
            )
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "contractVersion": TOURNAMENT_CONFIG_VERSION,
            "variantCount": self.variant_count,
            "maxVariants": self.max_variants,
            "maxConcurrency": self.max_concurrency,
            "renderBudgetSeconds": float(self.render_budget_seconds),
            "mediaActionBudget": self.media_action_budget,
            "estimatedRenderSeconds": float(self.estimated_render_seconds),
            "minValidCandidates": self.min_valid_candidates,
            "tieEpsilon": float(self.tie_epsilon),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TournamentConfig":
        if value.get("contractVersion") != TOURNAMENT_CONFIG_VERSION:
            raise CandidateTournamentError("unsupported tournament config")
        return cls(
            variant_count=value["variantCount"],
            max_variants=value["maxVariants"],
            max_concurrency=value["maxConcurrency"],
            render_budget_seconds=value["renderBudgetSeconds"],
            media_action_budget=value["mediaActionBudget"],
            estimated_render_seconds=value["estimatedRenderSeconds"],
            min_valid_candidates=value["minValidCandidates"],
            tie_epsilon=value["tieEpsilon"],
        ).validate()


def validate_variant_spec(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(DIMENSION_FIELDS):
        raise CandidateTournamentError("variant dimension fields must match exactly")
    result = {}
    for field in DIMENSION_FIELDS[:-1]:
        choice = value[field]
        if choice not in ALLOWED_DIMENSIONS[field]:
            raise CandidateTournamentError(f"unsupported {field} value")
        result[field] = choice
    result["musicVoiceBalanceDb"] = _number(
        value["musicVoiceBalanceDb"],
        "musicVoiceBalanceDb",
        minimum=-24.0,
        maximum=-6.0,
    )
    return result


def default_four_variants() -> list[dict[str, Any]]:
    return [
        {
            "pacingPreset": "tight",
            "captionStyle": "word_highlight",
            "brollDensity": "light",
            "hookCut": "cold_open",
            "punchInPattern": "subtle",
            "loopEnding": "soft_loop",
            "ctaTreatment": "integrated",
            "musicVoiceBalanceDb": -14.0,
        },
        {
            "pacingPreset": "aggressive",
            "captionStyle": "kinetic",
            "brollDensity": "dense",
            "hookCut": "pattern_interrupt",
            "punchInPattern": "beat_punch",
            "loopEnding": "hard_loop",
            "ctaTreatment": "text_endcard",
            "musicVoiceBalanceDb": -11.0,
        },
        {
            "pacingPreset": "steady",
            "captionStyle": "minimal",
            "brollDensity": "medium",
            "hookCut": "result_first",
            "punchInPattern": "subtle",
            "loopEnding": "soft_loop",
            "ctaTreatment": "spoken",
            "musicVoiceBalanceDb": -15.0,
        },
        {
            "pacingPreset": "tight",
            "captionStyle": "word_highlight",
            "brollDensity": "medium",
            "hookCut": "result_first",
            "punchInPattern": "beat_punch",
            "loopEnding": "soft_loop",
            "ctaTreatment": "integrated",
            "musicVoiceBalanceDb": -14.0,
        },
    ]


def _candidate_identity(
    *,
    tournament_id: str,
    ordinal: int,
    creative_item_digest: str,
    variant: Mapping[str, Any],
) -> tuple[str, str]:
    identity = {
        "tournamentId": tournament_id,
        "ordinal": ordinal,
        "creativeItemDigest": creative_item_digest,
        "variant": validate_variant_spec(variant),
    }
    digest = reels.sha256_json(identity)
    return "candidate15:" + digest, "mcr15:" + reels.sha256_json(
        {"candidateDigest": digest}
    )


class CandidateTournamentLedger:
    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        tournament_id: str,
        creative_item: Mapping[str, Any],
        config: TournamentConfig,
        media_pin: MediaR12ProducerPin | None = None,
        allow_synthetic_fixture: bool = False,
    ) -> None:
        self.path = Path(path)
        self.tournament_id = reels._nonempty(tournament_id, "tournament_id")
        self.creative_item = _clone(creative_item)
        reels._reject_secrets(self.creative_item)
        self.config = config.validate()
        self.media_pin = media_pin
        self.allow_synthetic_fixture = bool(allow_synthetic_fixture)
        self.events: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        self.candidates: dict[str, dict[str, Any]] = {}
        self.render_seconds_spent = 0.0
        self.media_actions_spent = 0
        self.inflight: set[str] = set()
        self.max_observed_concurrency = 0
        self.decision: dict[str, Any] | None = None
        self.override: dict[str, Any] | None = None
        if self.path.exists():
            self._load()
            if self.events[0]["payload"] != self._created_payload():
                raise TournamentConflict(
                    "tournament identity/config/creative item changed after creation"
                )
        else:
            self._append_once(
                "tournament:create",
                "tournament_created",
                self._created_payload(),
            )

    def _created_payload(self) -> dict[str, Any]:
        return {
            "tournamentId": self.tournament_id,
            "creativeItem": self.creative_item,
            "creativeItemDigest": reels.sha256_json(self.creative_item),
            "config": self.config.as_dict(),
            "mediaReadiness": media_r12_readiness(self.media_pin),
            "allowSyntheticFixture": self.allow_synthetic_fixture,
        }

    def _event(
        self,
        event_key: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        body = {
            "ledgerVersion": TOURNAMENT_LEDGER_VERSION,
            "sequence": len(self.events) + 1,
            "eventKey": event_key,
            "eventType": event_type,
            "payload": _clone(payload),
        }
        body["eventDigest"] = reels.sha256_json(body)
        return body

    def _append_once(
        self,
        event_key: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> str:
        reels._reject_secrets(payload)
        existing = self.by_key.get(event_key)
        normalized = _clone(payload)
        if existing is not None:
            if (
                existing["eventType"] != event_type
                or existing["payload"] != normalized
            ):
                raise TournamentConflict(
                    f"conflicting durable replay for {event_key}"
                )
            return "duplicate"
        event = self._event(event_key, event_type, normalized)
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
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TournamentConflict(
                    f"invalid tournament ledger JSON line {line_number}"
                ) from exc
            if set(event) != {
                "ledgerVersion",
                "sequence",
                "eventKey",
                "eventType",
                "payload",
                "eventDigest",
            }:
                raise TournamentConflict("tournament ledger fields invalid")
            if event["ledgerVersion"] != TOURNAMENT_LEDGER_VERSION:
                raise TournamentConflict("tournament ledger version mismatch")
            if event["sequence"] != len(self.events) + 1:
                raise TournamentConflict("tournament ledger sequence mismatch")
            material = dict(event)
            digest = material.pop("eventDigest")
            if reels.sha256_json(material) != digest:
                raise TournamentConflict("tournament event digest mismatch")
            if event["eventKey"] in self.by_key:
                raise TournamentConflict("duplicate event key in durable ledger")
            self.events.append(event)
            self.by_key[event["eventKey"]] = event
            self._apply(event)
        if not self.events or self.events[0]["eventType"] != "tournament_created":
            raise TournamentConflict("tournament ledger missing creation event")

    def _apply(self, event: Mapping[str, Any]) -> None:
        event_type = event["eventType"]
        payload = event["payload"]
        if event_type == "tournament_created":
            return
        if event_type == "candidate_planned":
            self.candidates[payload["candidateId"]] = _clone(payload)
        elif event_type == "budget_reserved":
            self.render_seconds_spent += float(payload["renderSeconds"])
            self.media_actions_spent += int(payload["mediaActions"])
        elif event_type == "media_started":
            self.inflight.add(payload["candidateId"])
            self.max_observed_concurrency = max(
                self.max_observed_concurrency,
                len(self.inflight),
            )
        elif event_type == "media_finished":
            self.inflight.discard(payload["candidateId"])
        elif event_type == "candidate_result":
            candidate = self.candidates[payload["candidateId"]]
            candidate["mediaResult"] = _clone(payload["result"])
            candidate["status"] = "media_ready"
        elif event_type == "candidate_evaluated":
            candidate = self.candidates[payload["candidateId"]]
            candidate["evaluation"] = _clone(payload["evaluation"])
            candidate["status"] = payload["evaluation"]["state"]
        elif event_type == "decision_committed":
            self.decision = _clone(payload)
        elif event_type == "decision_overridden":
            self.override = _clone(payload)
        else:
            raise TournamentConflict(
                f"unknown tournament event type {event_type!r}"
            )

    def plan_candidates(
        self,
        variants: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        if self.candidates:
            return sorted(
                (_clone(v) for v in self.candidates.values()),
                key=lambda item: item["ordinal"],
            )
        if len(variants) != self.config.variant_count:
            raise CandidateTournamentError(
                "variant list length must equal configured variant_count"
            )
        seen = set()
        creative_digest = reels.sha256_json(self.creative_item)
        planned = []
        for ordinal, raw in enumerate(variants):
            variant = validate_variant_spec(raw)
            variant_digest = reels.sha256_json(variant)
            if variant_digest in seen:
                raise CandidateTournamentError(
                    "duplicate candidate variant specification"
                )
            seen.add(variant_digest)
            candidate_id, idempotency_key = _candidate_identity(
                tournament_id=self.tournament_id,
                ordinal=ordinal,
                creative_item_digest=creative_digest,
                variant=variant,
            )
            value = {
                "candidateId": candidate_id,
                "ordinal": ordinal,
                "idempotencyKey": idempotency_key,
                "variant": variant,
                "variantDigest": variant_digest,
                "status": "planned",
                "mediaResult": None,
                "evaluation": None,
            }
            self._append_once(
                f"candidate:{candidate_id}:plan",
                "candidate_planned",
                value,
            )
            planned.append(_clone(value))
        return planned

    def reserve_candidate_budget(self, candidate_id: str) -> str:
        candidate = self.candidates[candidate_id]
        key = f"candidate:{candidate_id}:budget"
        existing = self.by_key.get(key)
        payload = {
            "candidateId": candidate_id,
            "renderSeconds": float(self.config.estimated_render_seconds),
            "mediaActions": 1,
        }
        if existing is not None:
            if existing["payload"] != payload:
                raise TournamentConflict("candidate budget replay conflict")
            return "duplicate"
        render_after = (
            self.render_seconds_spent
            + float(self.config.estimated_render_seconds)
        )
        actions_after = self.media_actions_spent + 1
        if render_after > float(self.config.render_budget_seconds) + 1e-9:
            raise TournamentBudgetExceeded(
                "candidate render budget would be exceeded"
            )
        if actions_after > self.config.media_action_budget:
            raise TournamentBudgetExceeded(
                "candidate Media action budget would be exceeded"
            )
        return self._append_once(key, "budget_reserved", payload)

    def begin_media(self, candidate_id: str) -> str:
        start_key = f"candidate:{candidate_id}:media:start"
        if start_key in self.by_key:
            return "duplicate"
        if len(self.inflight) >= self.config.max_concurrency:
            raise TournamentConcurrencyExceeded(
                "candidate Media concurrency ceiling reached"
            )
        return self._append_once(
            start_key,
            "media_started",
            {"candidateId": candidate_id},
        )

    def finish_media(self, candidate_id: str, outcome: str) -> str:
        if f"candidate:{candidate_id}:media:start" not in self.by_key:
            raise TournamentConflict("cannot finish Media before start")
        return self._append_once(
            f"candidate:{candidate_id}:media:finish",
            "media_finished",
            {
                "candidateId": candidate_id,
                "outcome": reels._nonempty(outcome, "Media outcome"),
            },
        )

    def record_media_result(
        self,
        candidate_id: str,
        result: Mapping[str, Any],
    ) -> str:
        candidate = self.candidates[candidate_id]
        validated = validate_media_result(
            result,
            candidate=candidate,
            media_pin=self.media_pin,
            allow_synthetic_fixture=self.allow_synthetic_fixture,
        )
        return self._append_once(
            f"candidate:{candidate_id}:result",
            "candidate_result",
            {"candidateId": candidate_id, "result": validated},
        )

    def evaluate_candidate(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.candidates[candidate_id]
        existing = candidate.get("evaluation")
        if existing is not None:
            return _clone(existing)
        result = candidate.get("mediaResult")
        if result is None:
            raise TournamentIncomplete("candidate Media result is missing")
        evaluation = evaluate_media_result(result)
        self._append_once(
            f"candidate:{candidate_id}:evaluation",
            "candidate_evaluated",
            {"candidateId": candidate_id, "evaluation": evaluation},
        )
        return _clone(evaluation)

    def select_winner(self) -> dict[str, Any]:
        if self.decision is not None:
            return _clone(self.decision)
        ordered = sorted(
            self.candidates.values(),
            key=lambda item: item["ordinal"],
        )
        if len(ordered) != self.config.variant_count:
            raise TournamentIncomplete("candidate planning is incomplete")
        if any(item.get("evaluation") is None for item in ordered):
            raise TournamentIncomplete("all candidates must be evaluated first")
        valid = [
            item
            for item in ordered
            if item["evaluation"]["state"] == "valid"
            and item["evaluation"]["evidenceSufficient"] is True
        ]
        if len(valid) < self.config.min_valid_candidates:
            decision = {
                "contractVersion": SELECTION_VERSION,
                "state": "insufficient_evidence",
                "winnerCandidateId": None,
                "qualityCertaintyClaimed": False,
                "selectionBasis": "objective_gates_then_source_bound_heuristic",
                "validCandidateCount": len(valid),
                "candidateEvidenceDigests": {
                    item["candidateId"]: item["evaluation"]["evaluationDigest"]
                    for item in ordered
                },
                "reason": "not enough hard-gate-passing candidates with sufficient evidence",
            }
        else:
            ranked = sorted(
                valid,
                key=lambda item: (
                    -float(item["evaluation"]["preferenceScore"]),
                    item["candidateId"],
                ),
            )
            top = ranked[0]
            second = ranked[1]
            delta = (
                float(top["evaluation"]["preferenceScore"])
                - float(second["evaluation"]["preferenceScore"])
            )
            if delta <= float(self.config.tie_epsilon) + 1e-12:
                decision = {
                    "contractVersion": SELECTION_VERSION,
                    "state": "tie",
                    "winnerCandidateId": None,
                    "qualityCertaintyClaimed": False,
                    "selectionBasis": "objective_gates_then_source_bound_heuristic",
                    "validCandidateCount": len(valid),
                    "tiedCandidateIds": [
                        top["candidateId"],
                        second["candidateId"],
                    ],
                    "scoreDelta": round(delta, 8),
                    "candidateEvidenceDigests": {
                        item["candidateId"]:
                            item["evaluation"]["evaluationDigest"]
                        for item in ordered
                    },
                    "reason": "top heuristic preference scores are within tie epsilon",
                }
            else:
                decision = {
                    "contractVersion": SELECTION_VERSION,
                    "state": "selected",
                    "winnerCandidateId": top["candidateId"],
                    "qualityCertaintyClaimed": False,
                    "selectionBasis": "objective_gates_then_source_bound_heuristic",
                    "validCandidateCount": len(valid),
                    "preferenceScore": top["evaluation"]["preferenceScore"],
                    "scoreDeltaToRunnerUp": round(delta, 8),
                    "candidateEvidenceDigests": {
                        item["candidateId"]:
                            item["evaluation"]["evaluationDigest"]
                        for item in ordered
                    },
                    "reason": "deterministic heuristic preference among hard-gate-passing candidates",
                }
        decision["decisionDigest"] = reels.sha256_json(decision)
        self._append_once(
            "decision:selection",
            "decision_committed",
            decision,
        )
        return _clone(decision)

    def human_override(
        self,
        *,
        candidate_id: str,
        actor_ref: str,
        reason: str,
    ) -> dict[str, Any]:
        reels._nonempty(actor_ref, "actor_ref")
        reels._nonempty(reason, "override reason")
        if self.decision is None:
            self.select_winner()
        candidate = self.candidates.get(candidate_id)
        if candidate is None or candidate.get("evaluation") is None:
            raise CandidateTournamentError(
                "override candidate must have evaluation provenance"
            )
        evaluation = candidate["evaluation"]
        if (
            evaluation["technicalQaPassed"] is not True
            or evaluation["hardGuardrailsPassed"] is not True
        ):
            raise CandidateTournamentError(
                "human override cannot bypass technical QA or hard guardrails"
            )
        payload = {
            "contractVersion": SELECTION_VERSION,
            "state": "human_override",
            "winnerCandidateId": candidate_id,
            "qualityCertaintyClaimed": False,
            "selectionBasis": "explicit_human_override_after_objective_hard_gates",
            "actorRef": actor_ref,
            "reason": reason,
            "priorDecisionDigest": self.decision["decisionDigest"],
            "winnerEvaluationDigest": evaluation["evaluationDigest"],
        }
        payload["decisionDigest"] = reels.sha256_json(payload)
        self._append_once(
            "decision:override",
            "decision_overridden",
            payload,
        )
        return _clone(payload)

    def effective_decision(self) -> dict[str, Any] | None:
        if self.override is not None:
            return _clone(self.override)
        if self.decision is not None:
            return _clone(self.decision)
        return None

    def selected_artifact(self) -> dict[str, Any]:
        decision = self.effective_decision()
        if decision is None or decision["state"] not in {
            "selected",
            "human_override",
        }:
            raise TournamentIncomplete(
                "tournament has no selected candidate artifact"
            )
        candidate = self.candidates[decision["winnerCandidateId"]]
        result = candidate["mediaResult"]
        evaluation = candidate["evaluation"]
        if (
            evaluation["technicalQaPassed"] is not True
            or evaluation["hardGuardrailsPassed"] is not True
        ):
            raise CandidateTournamentError(
                "selected artifact does not pass hard gates"
            )
        artifact = {
            "contractVersion": SELECTION_VERSION,
            "tournamentId": self.tournament_id,
            "candidateId": candidate["candidateId"],
            "variantDigest": candidate["variantDigest"],
            "mediaProducer": _clone(result["source"]),
            "timelineDigest": result["artifact"]["timelineDigest"],
            "artifactManifestDigest": result["artifact"]["artifactManifestDigest"],
            "contentId": result["artifact"]["contentId"],
            "contentSha256": result["artifact"]["contentSha256"],
            "contentSizeBytes": result["artifact"]["contentSizeBytes"],
            "renderFingerprint": result["artifact"]["renderFingerprint"],
            "technicalQaDigest": result["technicalQa"]["qaDigest"],
            "creativeEvidenceDigest":
                result["creativeEvidence"]["evidenceDigest"],
            "evaluationDigest": evaluation["evaluationDigest"],
            "decisionDigest": decision["decisionDigest"],
            "sourceClass": result["sourceClass"],
        }
        artifact["selectionDigest"] = reels.sha256_json(artifact)
        return artifact

    def report(self) -> dict[str, Any]:
        counts = {
            "planned": 0,
            "media_ready": 0,
            "rejected_technical": 0,
            "rejected_guardrail": 0,
            "insufficient_evidence": 0,
            "valid": 0,
        }
        for candidate in self.candidates.values():
            state = candidate["status"]
            if state in counts:
                counts[state] += 1
        report = {
            "contractVersion": TOURNAMENT_VERSION,
            "tournamentId": self.tournament_id,
            "candidateCount": len(self.candidates),
            "states": counts,
            "budget": {
                "renderSeconds": {
                    "spent": self.render_seconds_spent,
                    "ceiling": float(self.config.render_budget_seconds),
                },
                "mediaActions": {
                    "spent": self.media_actions_spent,
                    "ceiling": self.config.media_action_budget,
                },
            },
            "maxObservedConcurrency": self.max_observed_concurrency,
            "decision": self.effective_decision(),
            "mediaReadiness": media_r12_readiness(self.media_pin),
            "eventCount": len(self.events),
            "ledgerDigest": reels.sha256_json(self.events),
            "productionReadinessClaim": False if self.allow_synthetic_fixture else (
                media_r12_readiness(self.media_pin)["productionReady"]
            ),
        }
        report["reportDigest"] = reels.sha256_json(report)
        return report


def build_candidate_request(
    *,
    ledger: CandidateTournamentLedger,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    request = {
        "contractVersion": CANDIDATE_REQUEST_VERSION,
        "tournamentId": ledger.tournament_id,
        "candidateId": candidate["candidateId"],
        "idempotencyKey": candidate["idempotencyKey"],
        "creativeItemDigest": reels.sha256_json(ledger.creative_item),
        "variant": _clone(candidate["variant"]),
        "variantDigest": candidate["variantDigest"],
        "expectedMediaContract": "media.creative_edit_plan.r12.v1",
    }
    request["requestDigest"] = reels.sha256_json(request)
    return request


def _source_for_result(
    *,
    media_pin: MediaR12ProducerPin | None,
    source_class: str,
) -> dict[str, Any]:
    if source_class == "synthetic_fixture":
        return {
            "repository": MEDIA_R12_OBSERVED["repository"],
            "branch": MEDIA_R12_OBSERVED["branch"],
            "producerSha": MEDIA_R12_OBSERVED["producerSha"],
            "creativePlanManifestBlobSha":
                MEDIA_R12_OBSERVED["creativePlanManifestBlobSha"],
            "creativePlanContractBlobSha":
                MEDIA_R12_OBSERVED["creativePlanContractBlobSha"],
            "creatorConsumerCompatibilityBlobSha": None,
            "producerCompatibilityAccepted": False,
        }
    if source_class == "provider":
        if media_pin is None:
            raise MediaR12Unavailable(
                "provider Media R12 evidence requires an accepted exact producer pin"
            )
        pin = media_pin.validate()
        return {
            "repository": MEDIA_R12_OBSERVED["repository"],
            "branch": MEDIA_R12_OBSERVED["branch"],
            "producerSha": pin.producer_sha,
            "creativePlanManifestBlobSha":
                pin.creative_plan_manifest_blob_sha,
            "creativePlanContractBlobSha":
                pin.creative_plan_contract_blob_sha,
            "creatorConsumerCompatibilityBlobSha":
                pin.creator_consumer_compatibility_blob_sha,
            "producerCompatibilityAccepted": True,
        }
    raise CandidateTournamentError("unsupported candidate result sourceClass")


def validate_media_result(
    value: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
    media_pin: MediaR12ProducerPin | None,
    allow_synthetic_fixture: bool,
) -> dict[str, Any]:
    expected = {
        "contractVersion",
        "sourceClass",
        "source",
        "candidateId",
        "idempotencyKey",
        "requestDigest",
        "variant",
        "artifact",
        "technicalQa",
        "creativeEvidence",
        "resultDigest",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise CandidateTournamentError(
            "Media candidate result fields must match exactly"
        )
    if value["contractVersion"] != CANDIDATE_RESULT_VERSION:
        raise CandidateTournamentError(
            "unsupported Media candidate result version"
        )
    source_class = value["sourceClass"]
    if source_class == "synthetic_fixture" and not allow_synthetic_fixture:
        raise MediaR12Unavailable(
            "synthetic Media R12 tournament evidence is conformance-only"
        )
    expected_source = _source_for_result(
        media_pin=media_pin,
        source_class=source_class,
    )
    if value["source"] != expected_source:
        raise CandidateTournamentError("Media R12 source pin mismatch")
    reels._sha64(value["requestDigest"], "candidate requestDigest")
    if (
        value["candidateId"] != candidate["candidateId"]
        or value["idempotencyKey"] != candidate["idempotencyKey"]
        or value["variant"] != candidate["variant"]
    ):
        raise CandidateTournamentError(
            "Media candidate identity/variant mismatch"
        )
    artifact = value["artifact"]
    if set(artifact) != {
        "contentId",
        "contentSha256",
        "contentSizeBytes",
        "artifactManifestDigest",
        "timelineDigest",
        "renderFingerprint",
        "durationSeconds",
    }:
        raise CandidateTournamentError("candidate artifact fields invalid")
    digest = reels._sha64(
        artifact["contentSha256"], "candidate contentSha256"
    )
    if artifact["contentId"] != f"sha256:{digest}":
        raise CandidateTournamentError(
            "candidate contentId does not bind contentSha256"
        )
    reels._sha64(
        artifact["artifactManifestDigest"],
        "candidate artifactManifestDigest",
    )
    reels._sha64(
        artifact["timelineDigest"], "candidate timelineDigest"
    )
    reels._sha64(
        artifact["renderFingerprint"], "candidate renderFingerprint"
    )
    if (
        isinstance(artifact["contentSizeBytes"], bool)
        or not isinstance(artifact["contentSizeBytes"], int)
        or artifact["contentSizeBytes"] <= 0
    ):
        raise CandidateTournamentError(
            "candidate contentSizeBytes must be positive"
        )
    _number(
        artifact["durationSeconds"],
        "candidate durationSeconds",
        minimum=15.0,
        maximum=60.0,
    )
    qa = value["technicalQa"]
    if set(qa) != {"passed", "checks", "qaDigest"}:
        raise CandidateTournamentError("technical QA fields invalid")
    qa_material = {"passed": qa["passed"], "checks": qa["checks"]}
    if reels.sha256_json(qa_material) != qa["qaDigest"]:
        raise CandidateTournamentError("technical QA digest mismatch")
    evidence = value["creativeEvidence"]
    if set(evidence) != {
        "sourceBound",
        "sourceRefs",
        "guardrailMetrics",
        "creativeSignals",
        "evidenceDigest",
    }:
        raise CandidateTournamentError("creative evidence fields invalid")
    evidence_material = dict(evidence)
    evidence_digest = evidence_material.pop("evidenceDigest")
    if reels.sha256_json(evidence_material) != evidence_digest:
        raise CandidateTournamentError("creative evidence digest mismatch")
    if not isinstance(evidence["sourceBound"], bool):
        raise CandidateTournamentError("creative sourceBound must be boolean")
    if (
        not isinstance(evidence["sourceRefs"], Sequence)
        or isinstance(evidence["sourceRefs"], (str, bytes))
    ):
        raise CandidateTournamentError("creative sourceRefs must be an array")
    for ref in evidence["sourceRefs"]:
        reels._sha64(ref, "creative source ref")
    metrics = evidence["guardrailMetrics"]
    if set(metrics) != set(MEDIA_R12_HARD_GUARDRAILS):
        raise CandidateTournamentError(
            "guardrail metrics must match Media R12 hard guardrails"
        )
    for name, metric in metrics.items():
        _number(metric, f"guardrail metric {name}")
    signals = evidence["creativeSignals"]
    if set(signals) != set(CREATIVE_FIELDS):
        raise CandidateTournamentError(
            "creative signal fields must match exactly"
        )
    for name, signal in signals.items():
        _number(signal, f"creative signal {name}", minimum=0.0, maximum=1.0)
    material = dict(value)
    result_digest = material.pop("resultDigest")
    if reels.sha256_json(material) != result_digest:
        raise CandidateTournamentError("candidate result digest mismatch")
    reels._reject_secrets(value)
    return _clone(value)


def evaluate_media_result(result: Mapping[str, Any]) -> dict[str, Any]:
    qa = result["technicalQa"]
    evidence = result["creativeEvidence"]
    if qa["passed"] is not True:
        evaluation = {
            "state": "rejected_technical",
            "technicalQaPassed": False,
            "hardGuardrailsPassed": False,
            "evidenceSufficient": False,
            "preferenceScore": None,
            "qualityCertaintyClaimed": False,
            "hardGateFailures": ["media_technical_qa"],
            "creativeComparisonPerformed": False,
            "creativeEvidenceDigest": evidence["evidenceDigest"],
            "reason": "Media technical QA failed; creative comparison was skipped",
        }
    else:
        metrics = evidence["guardrailMetrics"]
        failures = []
        for name, ceiling in MEDIA_R12_HARD_GUARDRAILS.items():
            value = float(metrics[name])
            if name == "musicGainDb":
                if value > ceiling:
                    failures.append(name)
            elif value > ceiling:
                failures.append(name)
        if failures:
            evaluation = {
                "state": "rejected_guardrail",
                "technicalQaPassed": True,
                "hardGuardrailsPassed": False,
                "evidenceSufficient": False,
                "preferenceScore": None,
                "qualityCertaintyClaimed": False,
                "hardGateFailures": failures,
                "creativeComparisonPerformed": False,
                "creativeEvidenceDigest": evidence["evidenceDigest"],
                "reason": "candidate violated objective Media R12 over-editing guardrail",
            }
        elif (
            evidence["sourceBound"] is not True
            or len(evidence["sourceRefs"]) < 2
        ):
            evaluation = {
                "state": "insufficient_evidence",
                "technicalQaPassed": True,
                "hardGuardrailsPassed": True,
                "evidenceSufficient": False,
                "preferenceScore": None,
                "qualityCertaintyClaimed": False,
                "hardGateFailures": [],
                "creativeComparisonPerformed": False,
                "creativeEvidenceDigest": evidence["evidenceDigest"],
                "reason": "source-bound creative evidence is insufficient",
            }
        else:
            score = sum(
                float(evidence["creativeSignals"][name])
                * CREATIVE_WEIGHTS[name]
                for name in CREATIVE_FIELDS
            )
            evaluation = {
                "state": "valid",
                "technicalQaPassed": True,
                "hardGuardrailsPassed": True,
                "evidenceSufficient": True,
                "preferenceScore": round(score, 8),
                "qualityCertaintyClaimed": False,
                "hardGateFailures": [],
                "creativeComparisonPerformed": True,
                "creativeEvidenceDigest": evidence["evidenceDigest"],
                "heuristicInterpretation": (
                    "source-bound deterministic preference heuristic; "
                    "not a claim of objective creative quality"
                ),
                "reason": "candidate passed objective gates and has sufficient source-bound evidence",
            }
    evaluation["evaluationDigest"] = reels.sha256_json(evaluation)
    return evaluation


class MockMediaR12TournamentProvider:
    def __init__(
        self,
        *,
        scenario: str = "default",
        crash_after_effect_ordinal: int | None = None,
    ) -> None:
        if scenario not in {"default", "tie", "insufficient"}:
            raise ValueError("unsupported mock tournament scenario")
        self.scenario = scenario
        self.crash_after_effect_ordinal = crash_after_effect_ordinal
        self._crashed = False
        self._results: dict[str, dict[str, Any]] = {}
        self.submit_calls = 0
        self.recover_calls = 0
        self.accepted_effects = 0

    def recover(self, idempotency_key: str) -> Mapping[str, Any] | None:
        self.recover_calls += 1
        result = self._results.get(idempotency_key)
        return None if result is None else _clone(result)

    def submit(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.submit_calls += 1
        key = request["idempotencyKey"]
        existing = self._results.get(key)
        if existing is not None:
            return _clone(existing)
        self.accepted_effects += 1
        result = self._build_result(request)
        self._results[key] = result
        requested_ordinal = result["creativeEvidence"]["guardrailMetrics"].pop(
            "_fixtureOrdinal", None
        )
        # _fixtureOrdinal is removed before result durability.
        result["creativeEvidence"]["evidenceDigest"] = reels.sha256_json({
            key: value
            for key, value in result["creativeEvidence"].items()
            if key != "evidenceDigest"
        })
        result["resultDigest"] = reels.sha256_json({
            key: value for key, value in result.items() if key != "resultDigest"
        })
        self._results[key] = _clone(result)
        if (
            self.crash_after_effect_ordinal is not None
            and requested_ordinal == self.crash_after_effect_ordinal
            and not self._crashed
        ):
            self._crashed = True
            raise InjectedTournamentCrash(
                "after_media_candidate_effect_before_creator_ack"
            )
        return _clone(result)

    def _build_result(self, request: Mapping[str, Any]) -> dict[str, Any]:
        candidate_id = request["candidateId"]
        ordinal = _fixture_ordinal_from_request(request)
        qa_passed = ordinal != 0
        if self.scenario == "insufficient" and ordinal == 2:
            qa_passed = False
        metrics = {
            "cutRatePerSecond": 0.70,
            "zoomRatePerSecond": 0.12,
            "transitionDensityPerSecond": 0.10,
            "textCharsPerSecond": 14.0,
            "musicGainDb": -14.0,
            "concurrentTextItems": 1.0,
            "motionZoom": 1.10,
            "_fixtureOrdinal": ordinal,
        }
        if ordinal == 1:
            metrics["cutRatePerSecond"] = 1.60
        signals_by_ordinal = {
            0: [0.60, 0.62, 0.70, 0.70, 0.55, 0.60, 0.72],
            1: [0.90, 0.88, 0.82, 0.84, 0.80, 0.86, 0.75],
            2: [0.78, 0.80, 0.86, 0.81, 0.74, 0.76, 0.84],
            3: [0.90, 0.88, 0.91, 0.89, 0.82, 0.84, 0.88],
        }
        if self.scenario == "tie" and ordinal == 3:
            signals_by_ordinal[3] = list(signals_by_ordinal[2])
        if self.scenario == "insufficient" and ordinal == 3:
            signals_by_ordinal[3] = list(signals_by_ordinal[2])
        signals = {
            name: value
            for name, value in zip(
                CREATIVE_FIELDS,
                signals_by_ordinal.get(
                    ordinal,
                    [0.75, 0.75, 0.75, 0.75, 0.75, 0.75, 0.75],
                ),
            )
        }
        content_sha = reels.sha256_json(
            {"candidateId": candidate_id, "kind": "final-mp4"}
        )
        timeline_digest = reels.sha256_json(
            {"candidateId": candidate_id, "variant": request["variant"]}
        )
        manifest_digest = reels.sha256_json(
            {"contentSha": content_sha, "timeline": timeline_digest}
        )
        render_fp = reels.sha256_json(
            {"candidateId": candidate_id, "renderer": "media-r12-mock"}
        )
        qa_material = {
            "passed": qa_passed,
            "checks": [
                {
                    "name": "decodable_vertical_mp4",
                    "pass": qa_passed,
                    "source": "synthetic_media_probe",
                },
                {
                    "name": "duration_15_60_seconds",
                    "pass": True,
                    "source": "synthetic_media_probe",
                },
            ],
        }
        creative = {
            "sourceBound": True,
            "sourceRefs": [
                timeline_digest,
                reels.sha256_json(
                    {"candidateId": candidate_id, "source": "asset-plan"}
                ),
            ],
            "guardrailMetrics": metrics,
            "creativeSignals": signals,
        }
        creative["evidenceDigest"] = reels.sha256_json(creative)
        result = {
            "contractVersion": CANDIDATE_RESULT_VERSION,
            "sourceClass": "synthetic_fixture",
            "source": _source_for_result(
                media_pin=None,
                source_class="synthetic_fixture",
            ),
            "candidateId": candidate_id,
            "idempotencyKey": request["idempotencyKey"],
            "requestDigest": request["requestDigest"],
            "variant": _clone(request["variant"]),
            "artifact": {
                "contentId": f"sha256:{content_sha}",
                "contentSha256": content_sha,
                "contentSizeBytes": 1_000_000 + ordinal,
                "artifactManifestDigest": manifest_digest,
                "timelineDigest": timeline_digest,
                "renderFingerprint": render_fp,
                "durationSeconds": 30.0,
            },
            "technicalQa": {
                **qa_material,
                "qaDigest": reels.sha256_json(qa_material),
            },
            "creativeEvidence": creative,
        }
        result["resultDigest"] = reels.sha256_json(result)
        return result


def _fixture_ordinal_from_request(request: Mapping[str, Any]) -> int:
    variant = request["variant"]
    defaults = default_four_variants()
    for index, expected in enumerate(defaults):
        if variant == expected:
            return index
    digest = int(request["variantDigest"][:4], 16)
    return digest % 4


class CandidateTournamentRunner:
    def __init__(
        self,
        *,
        ledger: CandidateTournamentLedger,
        provider: MockMediaR12TournamentProvider,
    ) -> None:
        self.ledger = ledger
        self.provider = provider

    def process_candidate(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.ledger.candidates[candidate_id]
        if candidate.get("evaluation") is not None:
            return _clone(candidate["evaluation"])
        if candidate.get("mediaResult") is None:
            self.ledger.reserve_candidate_budget(candidate_id)
            self.ledger.begin_media(candidate_id)
            request = build_candidate_request(
                ledger=self.ledger,
                candidate=candidate,
            )
            recovered = self.provider.recover(candidate["idempotencyKey"])
            if recovered is None:
                result = self.provider.submit(request)
            else:
                result = recovered
            self.ledger.record_media_result(candidate_id, result)
            self.ledger.finish_media(candidate_id, "succeeded")
        return self.ledger.evaluate_candidate(candidate_id)

    def process_all(self) -> list[dict[str, Any]]:
        return [
            self.process_candidate(candidate["candidateId"])
            for candidate in sorted(
                self.ledger.candidates.values(),
                key=lambda item: item["ordinal"],
            )
        ]


def run_batch_item_tournament(
    batch_runner: r14.BatchCampaignRunner,
    item_id: str,
    *,
    config: TournamentConfig,
    provider: MockMediaR12TournamentProvider,
    variants: Sequence[Mapping[str, Any]] | None = None,
    media_pin: MediaR12ProducerPin | None = None,
    allow_synthetic_fixture: bool = False,
) -> dict[str, Any]:
    item = batch_runner.ledger._item(item_id)
    if item["script"] is None or item["assetPlan"] is None:
        raise CandidateTournamentError(
            "batch item tournament requires script and asset plan"
        )
    variants = list(variants or default_four_variants())
    if len(variants) != config.variant_count:
        raise CandidateTournamentError(
            "batch tournament variants must match configured count"
        )
    planning_key = f"{item_id}:r15:tournament-plan"
    batch_runner.ledger.reserve_budget(
        "generation_units",
        float(config.variant_count),
        operation_key=planning_key,
        item_id=item_id,
        detail="R15 candidate tournament planning/evaluation",
    )
    creative_item = {
        "campaignId": batch_runner.ledger.campaign_id,
        "itemId": item_id,
        "platform": item["platform"],
        "conceptDigest": reels.sha256_json(item["concept"]),
        "scriptDigest": item["script"]["sha256"],
        "assetPlanDigest": reels.sha256_json(item["assetPlan"]),
        "growthAdvisoryDigest": (
            None
            if batch_runner.ledger.growth_advisory is None
            else batch_runner.ledger.growth_advisory["evidenceDigest"]
        ),
    }
    tournament_id = "tournament15:" + reels.sha256_json(creative_item)
    path = (
        batch_runner.work_dir
        / "tournaments"
        / f"{reels.sha256_text(tournament_id)}.jsonl"
    )
    ledger = CandidateTournamentLedger(
        path,
        tournament_id=tournament_id,
        creative_item=creative_item,
        config=config,
        media_pin=media_pin,
        allow_synthetic_fixture=allow_synthetic_fixture,
    )
    candidates = ledger.plan_candidates(variants)
    runner = CandidateTournamentRunner(
        ledger=ledger,
        provider=provider,
    )
    for candidate in candidates:
        candidate_id = candidate["candidateId"]
        campaign_op = f"{item_id}:r15:{candidate_id}:media"
        batch_runner.ledger.reserve_budget(
            "render_seconds",
            float(config.estimated_render_seconds),
            operation_key=campaign_op,
            item_id=item_id,
            detail="R15 candidate Media render",
        )
        batch_runner.ledger.begin_operation(
            item_id=item_id,
            kind="media",
            operation_key=campaign_op,
        )
        try:
            runner.process_candidate(candidate_id)
        except InjectedTournamentCrash:
            raise
        else:
            batch_runner.ledger.finish_operation(
                operation_key=campaign_op,
                outcome="candidate_complete",
            )
    decision = ledger.select_winner()
    if decision["state"] == "selected":
        selection = ledger.selected_artifact()
        batch_runner.ledger.record_tournament_media(
            item_id,
            tournament_selection=selection,
        )
        batch_runner.ledger.record_qa(
            item_id,
            passed=True,
            checks=[
                {"name": "r15-selected-technical-qa", "pass": True},
                {"name": "r15-over-editing-guardrail", "pass": True},
                {"name": "r15-source-bound-selection", "pass": True},
            ],
        )
    return {
        "decision": decision,
        "selection": (
            ledger.selected_artifact()
            if decision["state"] == "selected"
            else None
        ),
        "report": ledger.report(),
    }


def default_config() -> TournamentConfig:
    return TournamentConfig(
        variant_count=4,
        max_variants=4,
        max_concurrency=2,
        render_budget_seconds=120.0,
        media_action_budget=4,
        estimated_render_seconds=30.0,
        min_valid_candidates=2,
        tie_epsilon=0.01,
    ).validate()


def run_deterministic_replay(
    work_dir: str | os.PathLike[str],
) -> dict[str, Any]:
    root = Path(work_dir)
    creative_item = {
        "campaignId": "r15-replay-campaign",
        "itemId": "r15-replay-item",
        "platform": "instagram_reels",
        "conceptDigest": "1" * 64,
        "scriptDigest": "2" * 64,
        "assetPlanDigest": "3" * 64,
        "growthAdvisoryDigest": "4" * 64,
    }
    config = default_config()
    path = root / "tournament.jsonl"
    ledger = CandidateTournamentLedger(
        path,
        tournament_id="creator-r15-deterministic-four",
        creative_item=creative_item,
        config=config,
        media_pin=None,
        allow_synthetic_fixture=True,
    )
    candidates = ledger.plan_candidates(default_four_variants())
    provider = MockMediaR12TournamentProvider(
        crash_after_effect_ordinal=3,
    )
    runner = CandidateTournamentRunner(
        ledger=ledger,
        provider=provider,
    )
    crash_count = 0
    for candidate in candidates:
        try:
            runner.process_candidate(candidate["candidateId"])
        except InjectedTournamentCrash:
            crash_count += 1
            ledger = CandidateTournamentLedger(
                path,
                tournament_id="creator-r15-deterministic-four",
                creative_item=creative_item,
                config=config,
                media_pin=None,
                allow_synthetic_fixture=True,
            )
            runner = CandidateTournamentRunner(
                ledger=ledger,
                provider=provider,
            )
            runner.process_candidate(candidate["candidateId"])
    decision = ledger.select_winner()
    selection = ledger.selected_artifact()
    report = ledger.report()
    replay = {
        "reportVersion": REPLAY_REPORT_VERSION,
        "state": "SYNTHETIC_REPLAY_GREEN",
        "candidateCount": 4,
        "technicalQaFailures": report["states"]["rejected_technical"],
        "guardrailFailures": report["states"]["rejected_guardrail"],
        "validCandidates": report["states"]["valid"],
        "lostAcknowledgementRestarts": crash_count,
        "mediaLogicalEffects": provider.accepted_effects,
        "mediaSubmitCalls": provider.submit_calls,
        "winnerCandidateId": decision["winnerCandidateId"],
        "winnerOrdinal": ledger.candidates[
            decision["winnerCandidateId"]
        ]["ordinal"],
        "selectionDigest": selection["selectionDigest"],
        "productionReadinessClaim": False,
        "mediaR12Readiness": media_r12_readiness(None),
    }
    replay["replayDigest"] = reels.sha256_json(replay)
    return replay


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Creator R15 deterministic edit-candidate tournament"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    replay = sub.add_parser("replay")
    replay.add_argument("--work-dir", required=True)
    sub.add_parser("readiness")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "readiness":
        print(json.dumps(media_r12_readiness(None), indent=2, sort_keys=True))
        return 2
    report = run_deterministic_replay(args.work_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
