from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from . import autonomous_reels as reels
from . import candidate_tournament as r15
from . import semantic_director as sd

LOOP_VERSION = "creator.autonomous_editor_loop.r22.v1"
LEDGER_VERSION = "creator.autonomous_editor_loop_ledger.r22.v1"
PLAN_VERSION = "creator.autonomous_edit_plan.r22.v1"
DECISION_VERSION = "creator.autonomous_edit_decision.r22.v1"
FINAL_BUNDLE_VERSION = "creator.autonomous_edit_final_bundle.r22.v1"
HUMAN_REVIEW_VERSION = "creator.autonomous_edit_human_review.r22.v1"
REHEARSAL_VERSION = "creator.autonomous_editor_loop_rehearsal.r22.v1"

MEDIA_RENDER_EXPORT_VERSION = "media.render_export.v1"
GROWTH_CRITIC_EXPORT_VERSION = "growth.critic_export.v1"

CREATOR_R21_BASE_SHA = "bad92b942e58ec885811dae1a048dc01ce86d2bd"

GROWTH_CRITIC_PIN = {
    "repository": "foto6/video3",
    "branch": "agent/growth-r16-benchmark-export-20261001",
    "producerSha": "cb50a3d78a18e6db1ebef1be69fdf11ff2e27385",
    "ciRunId": "36832188760",
    "ciConclusion": "success",
    "contractVersion": GROWTH_CRITIC_EXPORT_VERSION,
    "manifestBlobSha": "8f76d27c893658b3838eb2dcbe696a926a60dab3",
    "schemaBlobSha": "8b6f67dfaa015a824acd09e9a70121c8198ec72a",
    "implementationBlobSha": "be8342d3dd2d722855eaaf6902c9800da261b4c3",
}

MEDIA_RENDER_EXPORT_OBSERVED = {
    "repository": "foto6/video2",
    "branch": "agent/media-r15-benchmark-render-export-20261001",
    "observedHead": "e2b6af0d647c3677a13cdc4189bb8c85ffbca980",
    "ciRunId": "36832896059",
    "ciConclusion": "success",
    "requiredContract": MEDIA_RENDER_EXPORT_VERSION,
    "contractPresentAtObservedHead": False,
    "missingProducerPin": (
        "no media.render_export.v1 contract/schema/export exists at observed "
        "green head e2b6af0d647c3677a13cdc4189bb8c85ffbca980"
    ),
}

CRITIC_DIMENSIONS = (
    "hook",
    "pacing",
    "semantic_cut_correctness",
    "framing_crop",
    "broll_relevance",
    "captions",
    "continuity",
    "motion_appropriateness",
    "audio_balance",
    "payoff_cta_loop",
)

DIMENSION_WEIGHTS = {
    "hook": 0.14,
    "pacing": 0.12,
    "semantic_cut_correctness": 0.14,
    "framing_crop": 0.10,
    "broll_relevance": 0.08,
    "captions": 0.10,
    "continuity": 0.10,
    "motion_appropriateness": 0.07,
    "audio_balance": 0.07,
    "payoff_cta_loop": 0.08,
}


class EditorLoopError(ValueError):
    pass


class EditorLoopConflict(EditorLoopError):
    pass


class ProducerUnavailable(EditorLoopError):
    pass


class InjectedLostAck(RuntimeError):
    pass


def _clone(value: Any) -> Any:
    return json.loads(reels.canonical_json(value))


def _sha(value: Any) -> str:
    return reels.sha256_json(value)


def _nonempty(value: Any, field: str) -> str:
    return reels._nonempty(value, field)


def _hex64(value: Any, field: str) -> str:
    text = _nonempty(value, field)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise EditorLoopError(f"{field} must be lowercase sha256 hex")
    return text


def _hex40(value: Any, field: str) -> str:
    text = _nonempty(value, field)
    if len(text) != 40 or any(ch not in "0123456789abcdef" for ch in text):
        raise EditorLoopError(f"{field} must be lowercase git sha")
    return text


def validate_media_render_export(
    value: Mapping[str, Any],
    *,
    expected_source_id: str,
    expected_source_sha256: str,
    expected_candidate_id: str,
    expected_plan_digest: str,
    allow_synthetic: bool,
) -> dict[str, Any]:
    required = {
        "contract_version",
        "repository",
        "commit_sha",
        "source_class",
        "source_id",
        "source_sha256",
        "candidate_id",
        "round_index",
        "plan_digest",
        "render_sha256",
        "timeline_digest",
        "artifact_manifest_digest",
        "technical_qa",
        "render_provenance",
        "human_ground_truth",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise EditorLoopError("media.render_export.v1 fields must match exactly")
    if value["contract_version"] != MEDIA_RENDER_EXPORT_VERSION:
        raise EditorLoopError("media render export contract mismatch")
    if value["source_class"] not in {"provider", "synthetic_fixture"}:
        raise EditorLoopError("media render source_class invalid")
    if value["source_class"] == "synthetic_fixture" and not allow_synthetic:
        raise ProducerUnavailable("synthetic Media render export not allowed")
    if value["source_class"] == "provider":
        if MEDIA_RENDER_EXPORT_OBSERVED["contractPresentAtObservedHead"] is not True:
            raise ProducerUnavailable(
                MEDIA_RENDER_EXPORT_OBSERVED["missingProducerPin"]
            )
        if value["repository"] != MEDIA_RENDER_EXPORT_OBSERVED["repository"]:
            raise EditorLoopError("Media repository mismatch")
        _hex40(value["commit_sha"], "media.commit_sha")
    if value["source_id"] != expected_source_id:
        raise EditorLoopError("Media source_id mismatch")
    if value["source_sha256"] != expected_source_sha256:
        raise EditorLoopError("Media source SHA mismatch")
    if value["candidate_id"] != expected_candidate_id:
        raise EditorLoopError("Media candidate identity mismatch")
    if value["plan_digest"] != expected_plan_digest:
        raise EditorLoopError("Media plan digest mismatch")
    for key in (
        "source_sha256",
        "render_sha256",
        "timeline_digest",
        "artifact_manifest_digest",
        "plan_digest",
    ):
        _hex64(value[key], f"media.{key}")
    if (
        isinstance(value["round_index"], bool)
        or not isinstance(value["round_index"], int)
        or not 0 <= value["round_index"] <= 2
    ):
        raise EditorLoopError("Media round_index out of bounds")
    qa = value["technical_qa"]
    if not isinstance(qa, Mapping) or set(qa) != {
        "passed",
        "qa_digest",
        "checks",
    }:
        raise EditorLoopError("Media technical_qa invalid")
    if not isinstance(qa["passed"], bool) or not isinstance(qa["checks"], list):
        raise EditorLoopError("Media technical QA values invalid")
    _hex64(qa["qa_digest"], "media.technical_qa.qa_digest")
    if value["human_ground_truth"] is not False:
        raise EditorLoopError("Media render export cannot claim human ground truth")
    return _clone(value)


def validate_growth_critic_export(
    value: Mapping[str, Any],
    *,
    expected_source_id: str,
    expected_render_sha256: str,
    allow_synthetic: bool,
) -> dict[str, Any]:
    required = {
        "contract_version",
        "repository",
        "commit_sha",
        "source_id",
        "render_sha256",
        "critic_mode",
        "model_or_rule_identity",
        "dimension_observations",
        "timecoded_evidence",
        "hard_failure_observations",
        "pairwise_if_used",
        "human_ground_truth",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise EditorLoopError("growth.critic_export.v1 fields must match exactly")
    if value["contract_version"] != GROWTH_CRITIC_EXPORT_VERSION:
        raise EditorLoopError("Growth critic contract mismatch")
    if value["repository"] != GROWTH_CRITIC_PIN["repository"]:
        raise EditorLoopError("Growth critic repository mismatch")
    commit_sha = _hex40(value["commit_sha"], "growth.commit_sha")
    identity = value["model_or_rule_identity"]
    synthetic = bool(
        isinstance(identity, Mapping)
        and identity.get("kind") == "synthetic_fixture"
    )
    if synthetic:
        if not allow_synthetic:
            raise ProducerUnavailable("synthetic Growth critic not allowed")
    elif commit_sha != GROWTH_CRITIC_PIN["producerSha"]:
        raise ProducerUnavailable("Growth critic producer SHA is not pinned")
    if value["source_id"] != expected_source_id:
        raise EditorLoopError("Growth critic source_id mismatch")
    if value["render_sha256"] != expected_render_sha256:
        raise EditorLoopError("Growth critic render SHA mismatch")
    _hex64(value["render_sha256"], "growth.render_sha256")
    if value["critic_mode"] not in {
        "structural_rule",
        "vlm_augmented",
        "gemini_native_video",
    }:
        raise EditorLoopError("Growth critic mode invalid")
    dims = value["dimension_observations"]
    if not isinstance(dims, Mapping) or set(dims) != set(CRITIC_DIMENSIONS):
        raise EditorLoopError("Growth critic dimensions mismatch")
    for name in CRITIC_DIMENSIONS:
        obs = dims[name]
        if not isinstance(obs, Mapping) or set(obs) != {
            "source_dimension",
            "rule_observation",
            "vlm_observations",
            "unavailable",
        }:
            raise EditorLoopError(f"Growth critic {name} observation invalid")
        rule = obs["rule_observation"]
        if not isinstance(rule, Mapping):
            raise EditorLoopError("Growth rule observation must be object")
        if rule.get("human_ground_truth") is not False:
            raise EditorLoopError("Growth rule observation claims human ground truth")
        score = rule.get("normalized_score")
        if score is not None:
            if (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not 0 <= float(score) <= 1
            ):
                raise EditorLoopError("Growth normalized score out of bounds")
        conf = rule.get("confidence")
        if conf is not None:
            if (
                isinstance(conf, bool)
                or not isinstance(conf, (int, float))
                or not 0 <= float(conf) <= 1
            ):
                raise EditorLoopError("Growth confidence out of bounds")
    if not isinstance(value["timecoded_evidence"], list):
        raise EditorLoopError("Growth timecoded_evidence must be array")
    if not isinstance(value["hard_failure_observations"], list):
        raise EditorLoopError("Growth hard_failure_observations must be array")
    if value["human_ground_truth"] is not False:
        raise EditorLoopError("Growth critic cannot claim human ground truth")
    return _clone(value)


class MediaRenderExportAdapter(Protocol):
    def recover(self, idempotency_key: str) -> Mapping[str, Any] | None:
        ...

    def submit(
        self,
        *,
        idempotency_key: str,
        source: Mapping[str, Any],
        plan: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        ...


class GrowthCriticExportAdapter(Protocol):
    def recover(self, idempotency_key: str) -> Mapping[str, Any] | None:
        ...

    def submit(
        self,
        *,
        idempotency_key: str,
        source: Mapping[str, Any],
        render_export: Mapping[str, Any],
        semantic_analysis: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        ...


@dataclass(frozen=True)
class LoopConfig:
    candidate_count: int = 4
    max_rounds: int = 2
    tie_epsilon: float = 0.035
    minimum_dimensions: int = 7
    minimum_confidence: float = 0.55

    def validate(self) -> "LoopConfig":
        if not 2 <= self.candidate_count <= 4:
            raise EditorLoopError("candidate_count must be 2-4")
        if self.max_rounds != 2:
            raise EditorLoopError("R22 max_rounds must be exactly 2")
        if not 0 <= self.tie_epsilon <= 0.25:
            raise EditorLoopError("tie_epsilon out of bounds")
        if not 1 <= self.minimum_dimensions <= len(CRITIC_DIMENSIONS):
            raise EditorLoopError("minimum_dimensions out of bounds")
        if not 0 <= self.minimum_confidence <= 1:
            raise EditorLoopError("minimum_confidence out of bounds")
        return self


class LoopLedger:
    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        loop_id: str,
        source: Mapping[str, Any],
        brief_digest: str,
        semantic_digest: str,
        directives_digest: str,
        config: LoopConfig,
    ) -> None:
        self.path = Path(path)
        self.loop_id = _nonempty(loop_id, "loop_id")
        self.source = _clone(source)
        self.brief_digest = _hex64(brief_digest, "brief_digest")
        self.semantic_digest = _hex64(semantic_digest, "semantic_digest")
        self.directives_digest = _hex64(directives_digest, "directives_digest")
        self.config = config.validate()
        self.events: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            self._load()
            if self.events[0]["payload"] != self._created_payload():
                raise EditorLoopConflict("loop identity changed after durable creation")
        else:
            self.append_once(
                "loop:create",
                "loop_created",
                self._created_payload(),
            )

    def _created_payload(self) -> dict[str, Any]:
        return {
            "loopId": self.loop_id,
            "source": self.source,
            "briefDigest": self.brief_digest,
            "semanticDigest": self.semantic_digest,
            "directivesDigest": self.directives_digest,
            "config": {
                "candidateCount": self.config.candidate_count,
                "maxRounds": self.config.max_rounds,
                "tieEpsilon": self.config.tie_epsilon,
                "minimumDimensions": self.config.minimum_dimensions,
                "minimumConfidence": self.config.minimum_confidence,
            },
        }

    def _load(self) -> None:
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EditorLoopConflict(
                    f"invalid loop ledger line {line_number}"
                ) from exc
            if set(event) != {
                "ledgerVersion",
                "sequence",
                "eventKey",
                "eventType",
                "payload",
                "eventDigest",
            }:
                raise EditorLoopConflict("loop event fields invalid")
            if event["ledgerVersion"] != LEDGER_VERSION:
                raise EditorLoopConflict("loop ledger version mismatch")
            if event["sequence"] != len(self.events) + 1:
                raise EditorLoopConflict("loop ledger sequence mismatch")
            material = dict(event)
            digest = material.pop("eventDigest")
            if _sha(material) != digest:
                raise EditorLoopConflict("loop event digest mismatch")
            if event["eventKey"] in self.by_key:
                raise EditorLoopConflict("duplicate durable event key")
            reels._reject_secrets(event["payload"])
            self.events.append(event)
            self.by_key[event["eventKey"]] = event

    def append_once(
        self,
        event_key: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> str:
        reels._reject_secrets(payload)
        normalized = _clone(payload)
        existing = self.by_key.get(event_key)
        if existing is not None:
            if (
                existing["eventType"] != event_type
                or existing["payload"] != normalized
            ):
                raise EditorLoopConflict(
                    f"conflicting durable replay for {event_key}"
                )
            return "duplicate"
        event = {
            "ledgerVersion": LEDGER_VERSION,
            "sequence": len(self.events) + 1,
            "eventKey": event_key,
            "eventType": event_type,
            "payload": normalized,
        }
        event["eventDigest"] = _sha(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(reels.canonical_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.events.append(event)
        self.by_key[event_key] = event
        return "committed"

    def event_payload(self, event_key: str) -> dict[str, Any] | None:
        event = self.by_key.get(event_key)
        return None if event is None else _clone(event["payload"])

    def events_of(self, event_type: str) -> list[dict[str, Any]]:
        return [
            _clone(event["payload"])
            for event in self.events
            if event["eventType"] == event_type
        ]

    @property
    def digest(self) -> str:
        return _sha(self.events)


def _candidate_id(
    *,
    loop_id: str,
    ordinal: int,
    base_plan: Mapping[str, Any],
) -> str:
    return "candidate22:" + _sha(
        {
            "loopId": loop_id,
            "ordinal": ordinal,
            "basePlan": base_plan,
        }
    )


def _revision_candidate_id(
    *,
    parent_candidate_id: str,
    round_index: int,
    deltas: Sequence[Mapping[str, Any]],
) -> str:
    return "candidate22r:" + _sha(
        {
            "parentCandidateId": parent_candidate_id,
            "roundIndex": round_index,
            "deltas": list(deltas),
        }
    )


def build_initial_plans(
    *,
    loop_id: str,
    semantic_analysis: Mapping[str, Any],
    style_decision: Mapping[str, Any],
    directives: Mapping[str, Any],
    count: int,
) -> list[dict[str, Any]]:
    if not 2 <= count <= 4:
        raise EditorLoopError("initial plan count must be 2-4")
    variants = r15.default_four_variants()[:count]
    plans = []
    for ordinal, variant in enumerate(variants):
        material = {
            "contractVersion": PLAN_VERSION,
            "roundIndex": 0,
            "parentCandidateId": None,
            "ordinal": ordinal,
            "semanticAnalysisDigest": semantic_analysis["analysisDigest"],
            "editorialMode": style_decision["effectiveMode"],
            "semanticDirectivesDigest": directives["directivesDigest"],
            "variant": variant,
            "targetedDeltas": [],
        }
        candidate_id = _candidate_id(
            loop_id=loop_id,
            ordinal=ordinal,
            base_plan=material,
        )
        plan = {**material, "candidateId": candidate_id}
        plan["planDigest"] = _sha(plan)
        plans.append(plan)
    return plans


def _dimension_score(obs: Mapping[str, Any]) -> tuple[float, float] | None:
    rule = obs["rule_observation"]
    if rule.get("available") is not True:
        return None
    score = rule.get("normalized_score")
    confidence = rule.get("confidence")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return None
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return None
    return float(score), float(confidence)


def evaluate_critic(
    critic: Mapping[str, Any],
    *,
    config: LoopConfig,
) -> dict[str, Any]:
    if critic["hard_failure_observations"]:
        return {
            "eligible": False,
            "state": "hard_failure",
            "score": None,
            "confidence": 0.0,
            "availableDimensions": 0,
            "reason": "growth critic reported hard failure observations",
        }
    weighted = 0.0
    weight_total = 0.0
    conf_weighted = 0.0
    available = 0
    for name in CRITIC_DIMENSIONS:
        parsed = _dimension_score(critic["dimension_observations"][name])
        if parsed is None:
            continue
        score, confidence = parsed
        if confidence < config.minimum_confidence:
            continue
        weight = DIMENSION_WEIGHTS[name]
        weighted += score * weight
        conf_weighted += confidence * weight
        weight_total += weight
        available += 1
    if available < config.minimum_dimensions or weight_total <= 0:
        return {
            "eligible": False,
            "state": "insufficient_evidence",
            "score": None,
            "confidence": (
                0.0 if weight_total <= 0 else conf_weighted / weight_total
            ),
            "availableDimensions": available,
            "reason": "too few sufficiently confident critic dimensions",
        }
    score = weighted / weight_total
    confidence = conf_weighted / weight_total
    return {
        "eligible": True,
        "state": "eligible",
        "score": round(score, 6),
        "confidence": round(confidence, 6),
        "availableDimensions": available,
        "reason": "objective hard gates passed; heuristic critic evidence sufficient",
    }


def _pairwise_preference(
    critic: Mapping[str, Any],
) -> str | None:
    pairwise = critic.get("pairwise_if_used")
    if not isinstance(pairwise, Mapping):
        return None
    preferred = pairwise.get("preferred_candidate_id")
    return preferred if isinstance(preferred, str) and preferred else None


def select_round(
    records: Sequence[Mapping[str, Any]],
    *,
    config: LoopConfig,
    round_index: int,
) -> dict[str, Any]:
    normalized = []
    for record in records:
        evaluation = evaluate_critic(record["critic"], config=config)
        normalized.append(
            {
                "candidateId": record["candidateId"],
                "renderSha256": record["render"]["render_sha256"],
                "evaluation": evaluation,
                "pairwisePreferredCandidateId": _pairwise_preference(
                    record["critic"]
                ),
            }
        )
    eligible = [
        item for item in normalized if item["evaluation"]["eligible"]
    ]
    if len(eligible) < 2:
        state = "insufficient_evidence"
        winner = None
        reason = "fewer than two candidates have sufficient non-hard-failure evidence"
    else:
        eligible.sort(
            key=lambda item: (
                -float(item["evaluation"]["score"]),
                item["candidateId"],
            )
        )
        top, second = eligible[0], eligible[1]
        scalar_winner = top["candidateId"]
        pairwise_votes = {
            item["pairwisePreferredCandidateId"]
            for item in eligible
            if item["pairwisePreferredCandidateId"] is not None
        }
        contradictory = bool(
            pairwise_votes
            and (
                len(pairwise_votes) > 1
                or scalar_winner not in pairwise_votes
            )
        )
        if contradictory:
            state = "insufficient_evidence"
            winner = None
            reason = "pairwise and scalar critic evidence are contradictory"
        elif (
            float(top["evaluation"]["score"])
            - float(second["evaluation"]["score"])
            <= config.tie_epsilon
        ):
            state = "tie"
            winner = None
            reason = "top candidates fall within configured tie epsilon"
        else:
            state = "winner"
            winner = scalar_winner
            reason = "heuristic critic evidence separates top candidate beyond tie epsilon"
    decision = {
        "contractVersion": DECISION_VERSION,
        "roundIndex": round_index,
        "state": state,
        "winnerCandidateId": winner,
        "reason": reason,
        "evaluations": sorted(normalized, key=lambda item: item["candidateId"]),
        "humanLevelQualityClaimed": False,
        "aestheticSuperiorityClaimed": False,
    }
    decision["decisionDigest"] = _sha(decision)
    return decision


def targeted_deltas(
    critic: Mapping[str, Any],
) -> list[dict[str, Any]]:
    dims = critic["dimension_observations"]
    evidence = critic["timecoded_evidence"]
    spans: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        if not isinstance(item, Mapping):
            continue
        dimension = item.get("rubric_dimension")
        if isinstance(dimension, str):
            spans.setdefault(dimension, []).append(dict(item))

    def weakest() -> list[str]:
        scored = []
        for name in CRITIC_DIMENSIONS:
            parsed = _dimension_score(dims[name])
            if parsed is None:
                continue
            score, confidence = parsed
            scored.append((score, -confidence, name))
        return [item[2] for item in sorted(scored)[:3]]

    deltas: list[dict[str, Any]] = []
    for name in weakest():
        item_spans = spans.get(name, [])
        start_ms = next(
            (
                item.get("start_ms")
                for item in item_spans
                if isinstance(item.get("start_ms"), int)
            ),
            None,
        )
        end_ms = next(
            (
                item.get("end_ms")
                for item in item_spans
                if isinstance(item.get("end_ms"), int)
            ),
            None,
        )
        if name == "hook":
            deltas.append(
                {
                    "dimension": name,
                    "operation": "tighten_hook_window",
                    "startMs": 0,
                    "endMs": min(3000, end_ms or 3000),
                    "target": {
                        "maxLeadInMs": 350,
                        "resultOrClaimByMs": 1500,
                    },
                }
            )
        elif name == "pacing":
            deltas.append(
                {
                    "dimension": name,
                    "operation": "compress_span",
                    "startMs": start_ms or 1000,
                    "endMs": end_ms or 2500,
                    "target": {"durationReductionPct": 18},
                }
            )
        elif name == "semantic_cut_correctness":
            deltas.append(
                {
                    "dimension": name,
                    "operation": "move_cut_to_semantic_boundary",
                    "startMs": start_ms or 0,
                    "endMs": end_ms or ((start_ms or 0) + 250),
                    "target": {"boundaryToleranceMs": 120},
                }
            )
        elif name == "framing_crop":
            deltas.append(
                {
                    "dimension": name,
                    "operation": "reframe_subject",
                    "startMs": start_ms or 0,
                    "endMs": end_ms or 3000,
                    "target": {
                        "subjectCenterX": 0.5,
                        "subjectCenterY": 0.42,
                        "maxCropLossPct": 8,
                    },
                }
            )
        elif name == "broll_relevance":
            deltas.append(
                {
                    "dimension": name,
                    "operation": "remove_unmatched_broll",
                    "startMs": start_ms or 0,
                    "endMs": end_ms or 2000,
                    "target": {"semanticMatchMinimum": 0.7},
                }
            )
        elif name == "captions":
            deltas.append(
                {
                    "dimension": name,
                    "operation": "reduce_caption_density",
                    "startMs": start_ms or 0,
                    "endMs": end_ms or 3000,
                    "target": {
                        "maxCharsPerLine": 24,
                        "maxLines": 2,
                        "minOnscreenMs": 650,
                    },
                }
            )
        elif name == "continuity":
            deltas.append(
                {
                    "dimension": name,
                    "operation": "preserve_continuity_span",
                    "startMs": start_ms or 0,
                    "endMs": end_ms or 2500,
                    "target": {"forbidInsertCut": True},
                }
            )
        elif name == "motion_appropriateness":
            deltas.append(
                {
                    "dimension": name,
                    "operation": "reduce_motion_intensity",
                    "startMs": start_ms or 0,
                    "endMs": end_ms or 3000,
                    "target": {"maxZoom": 1.08, "maxPunchInsPer5s": 1},
                }
            )
        elif name == "audio_balance":
            deltas.append(
                {
                    "dimension": name,
                    "operation": "rebalance_voice_music",
                    "startMs": start_ms,
                    "endMs": end_ms,
                    "target": {
                        "musicGainDeltaDb": -3.0,
                        "voiceOverMusicMinimumDb": 8.0,
                    },
                }
            )
        elif name == "payoff_cta_loop":
            deltas.append(
                {
                    "dimension": name,
                    "operation": "retime_payoff_or_cta",
                    "startMs": start_ms or 0,
                    "endMs": end_ms,
                    "target": {
                        "payoffBeforeEndMs": 1800,
                        "ctaMaximumDurationMs": 1200,
                    },
                }
            )
    return deltas


def build_reedit_plan(
    *,
    parent_plan: Mapping[str, Any],
    critic: Mapping[str, Any],
    round_index: int,
) -> dict[str, Any]:
    if not 1 <= round_index <= 2:
        raise EditorLoopError("re-edit round must be 1 or 2")
    deltas = targeted_deltas(critic)
    if not deltas:
        raise EditorLoopError("critic supplied no concrete actionable deltas")
    candidate_id = _revision_candidate_id(
        parent_candidate_id=parent_plan["candidateId"],
        round_index=round_index,
        deltas=deltas,
    )
    plan = {
        "contractVersion": PLAN_VERSION,
        "roundIndex": round_index,
        "parentCandidateId": parent_plan["candidateId"],
        "ordinal": parent_plan["ordinal"],
        "semanticAnalysisDigest": parent_plan["semanticAnalysisDigest"],
        "editorialMode": parent_plan["editorialMode"],
        "semanticDirectivesDigest": parent_plan["semanticDirectivesDigest"],
        "variant": _clone(parent_plan["variant"]),
        "targetedDeltas": deltas,
        "candidateId": candidate_id,
    }
    plan["planDigest"] = _sha(plan)
    return plan


class SyntheticMediaRenderAdapter:
    def __init__(
        self,
        *,
        lost_ack_once_for: set[str] | None = None,
    ) -> None:
        self.results: dict[str, dict[str, Any]] = {}
        self.accepted_effects = 0
        self.submit_calls = 0
        self.lost_ack_once_for = set(lost_ack_once_for or ())
        self._crashed: set[str] = set()

    def recover(self, idempotency_key: str) -> Mapping[str, Any] | None:
        value = self.results.get(idempotency_key)
        return None if value is None else _clone(value)

    def submit(
        self,
        *,
        idempotency_key: str,
        source: Mapping[str, Any],
        plan: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.submit_calls += 1
        existing = self.results.get(idempotency_key)
        if existing is not None:
            return _clone(existing)
        ordinal = int(plan["ordinal"])
        round_index = int(plan["roundIndex"])
        render_sha = _sha(
            {
                "sourceSha256": source["sha256"],
                "planDigest": plan["planDigest"],
                "candidateId": plan["candidateId"],
            }
        )
        qa_material = {
            "passed": True,
            "checks": [
                {"name": "mp4", "pass": True},
                {"name": "aspect_9_16", "pass": True},
                {"name": "duration", "pass": True},
            ],
        }
        qa = {
            **qa_material,
            "qa_digest": _sha(qa_material),
        }
        value = {
            "contract_version": MEDIA_RENDER_EXPORT_VERSION,
            "repository": "foto6/video2",
            "commit_sha": "0" * 40,
            "source_class": "synthetic_fixture",
            "source_id": source["sourceId"],
            "source_sha256": source["sha256"],
            "candidate_id": plan["candidateId"],
            "round_index": round_index,
            "plan_digest": plan["planDigest"],
            "render_sha256": render_sha,
            "timeline_digest": _sha(
                {"render": render_sha, "kind": "timeline"}
            ),
            "artifact_manifest_digest": _sha(
                {"render": render_sha, "kind": "manifest"}
            ),
            "technical_qa": qa,
            "render_provenance": {
                "adapter": "SyntheticMediaRenderAdapter",
                "ordinal": ordinal,
                "roundIndex": round_index,
                "humanLevelQuality": "HUMAN_LEVEL_UNPROVEN",
            },
            "human_ground_truth": False,
        }
        self.results[idempotency_key] = _clone(value)
        self.accepted_effects += 1
        if (
            idempotency_key in self.lost_ack_once_for
            and idempotency_key not in self._crashed
        ):
            self._crashed.add(idempotency_key)
            raise InjectedLostAck("synthetic Media accepted before ACK")
        return _clone(value)


class SyntheticGrowthCriticAdapter:
    def __init__(
        self,
        *,
        scenario: str = "reedit_winner",
        lost_ack_once_for: set[str] | None = None,
    ) -> None:
        self.scenario = scenario
        self.results: dict[str, dict[str, Any]] = {}
        self.accepted_effects = 0
        self.submit_calls = 0
        self.lost_ack_once_for = set(lost_ack_once_for or ())
        self._crashed: set[str] = set()

    def recover(self, idempotency_key: str) -> Mapping[str, Any] | None:
        value = self.results.get(idempotency_key)
        return None if value is None else _clone(value)

    def _scores(
        self,
        *,
        ordinal: int,
        round_index: int,
    ) -> dict[str, float | None]:
        if self.scenario == "insufficient":
            return {
                name: (0.6 if index < 3 else None)
                for index, name in enumerate(CRITIC_DIMENSIONS)
            }
        if self.scenario == "contradictory":
            base = 0.72 + (0.03 if ordinal == 0 else 0.0)
            return {name: base for name in CRITIC_DIMENSIONS}
        if round_index == 0:
            base = {0: 0.72, 1: 0.718, 2: 0.64, 3: 0.60}.get(
                ordinal, 0.60
            )
        elif round_index == 1:
            base = {0: 0.82, 1: 0.815, 2: 0.72, 3: 0.70}.get(
                ordinal, 0.70
            )
        else:
            base = {0: 0.90, 1: 0.83, 2: 0.74, 3: 0.72}.get(
                ordinal, 0.72
            )
        return {
            name: max(
                0.0,
                min(1.0, base - (index % 3) * 0.015),
            )
            for index, name in enumerate(CRITIC_DIMENSIONS)
        }

    def submit(
        self,
        *,
        idempotency_key: str,
        source: Mapping[str, Any],
        render_export: Mapping[str, Any],
        semantic_analysis: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.submit_calls += 1
        existing = self.results.get(idempotency_key)
        if existing is not None:
            return _clone(existing)
        provenance = render_export["render_provenance"]
        ordinal = int(provenance["ordinal"])
        round_index = int(provenance["roundIndex"])
        scores = self._scores(ordinal=ordinal, round_index=round_index)
        dimensions = {}
        evidence = []
        for index, name in enumerate(CRITIC_DIMENSIONS):
            score = scores[name]
            available = score is not None
            dimensions[name] = {
                "source_dimension": name,
                "rule_observation": {
                    "available": available,
                    "confidence": 0.82 if available else 0.0,
                    "evidence": (
                        [f"synthetic:{name}:source_bound"]
                        if available
                        else []
                    ),
                    "human_ground_truth": False,
                    "limitation": (
                        None if available else "synthetic evidence unavailable"
                    ),
                    "normalized_score": score,
                },
                "vlm_observations": [],
                "unavailable": (
                    None if available else "synthetic evidence unavailable"
                ),
            }
            if available and score < 0.73:
                evidence.append(
                    {
                        "start_ms": 300 + index * 150,
                        "end_ms": 700 + index * 150,
                        "evidence_kind": "structural_heuristic",
                        "human_ground_truth": False,
                        "note": f"bounded synthetic weakness for {name}",
                        "rubric_dimension": name,
                        "severity": "warning",
                        "source_dimension": name,
                    }
                )
        pairwise = None
        if self.scenario == "contradictory":
            pairwise = {
                "preferred_candidate_id": (
                    "different-candidate-than-scalar"
                ),
                "human_ground_truth": False,
            }
        value = {
            "contract_version": GROWTH_CRITIC_EXPORT_VERSION,
            "repository": GROWTH_CRITIC_PIN["repository"],
            "commit_sha": "0" * 40,
            "source_id": source["sourceId"],
            "render_sha256": render_export["render_sha256"],
            "critic_mode": "structural_rule",
            "model_or_rule_identity": {
                "kind": "synthetic_fixture",
                "mode": "deterministic_r22_rehearsal",
                "contractVersion": GROWTH_CRITIC_EXPORT_VERSION,
                "humanLevelQuality": "HUMAN_LEVEL_UNPROVEN",
            },
            "dimension_observations": dimensions,
            "timecoded_evidence": evidence,
            "hard_failure_observations": [],
            "pairwise_if_used": pairwise,
            "human_ground_truth": False,
        }
        self.results[idempotency_key] = _clone(value)
        self.accepted_effects += 1
        if (
            idempotency_key in self.lost_ack_once_for
            and idempotency_key not in self._crashed
        ):
            self._crashed.add(idempotency_key)
            raise InjectedLostAck("synthetic Growth critic accepted before ACK")
        return _clone(value)


class AutonomousEditorLoop:
    def __init__(
        self,
        *,
        ledger: LoopLedger,
        semantic_analysis: Mapping[str, Any],
        style_decision: Mapping[str, Any],
        semantic_directives: Mapping[str, Any],
        media: MediaRenderExportAdapter,
        critic: GrowthCriticExportAdapter,
        allow_synthetic: bool,
    ) -> None:
        self.ledger = ledger
        self.semantic_analysis = _clone(semantic_analysis)
        self.style_decision = _clone(style_decision)
        self.semantic_directives = _clone(semantic_directives)
        self.media = media
        self.critic = critic
        self.allow_synthetic = allow_synthetic

    def _record_plans(
        self,
        plans: Sequence[Mapping[str, Any]],
    ) -> None:
        for plan in sorted(plans, key=lambda item: item["candidateId"]):
            self.ledger.append_once(
                f"plan:{plan['candidateId']}",
                "candidate_planned",
                {"plan": plan},
            )

    def _execute_candidate(
        self,
        plan: Mapping[str, Any],
    ) -> dict[str, Any]:
        candidate_id = plan["candidateId"]
        render_key = "render:" + candidate_id
        existing_render = self.ledger.event_payload(
            f"render-result:{candidate_id}"
        )
        if existing_render is None:
            self.ledger.append_once(
                f"render-intent:{candidate_id}",
                "render_intent",
                {
                    "candidateId": candidate_id,
                    "idempotencyKey": render_key,
                    "planDigest": plan["planDigest"],
                },
            )
            render = self.media.recover(render_key)
            if render is None:
                render = self.media.submit(
                    idempotency_key=render_key,
                    source=self.ledger.source,
                    plan=plan,
                )
            render = validate_media_render_export(
                render,
                expected_source_id=self.ledger.source["sourceId"],
                expected_source_sha256=self.ledger.source["sha256"],
                expected_candidate_id=candidate_id,
                expected_plan_digest=plan["planDigest"],
                allow_synthetic=self.allow_synthetic,
            )
            self.ledger.append_once(
                f"render-result:{candidate_id}",
                "render_result",
                {"render": render},
            )
        else:
            render = existing_render["render"]

        critic_key = "critic:" + candidate_id
        existing_critic = self.ledger.event_payload(
            f"critic-result:{candidate_id}"
        )
        if existing_critic is None:
            self.ledger.append_once(
                f"critic-intent:{candidate_id}",
                "critic_intent",
                {
                    "candidateId": candidate_id,
                    "idempotencyKey": critic_key,
                    "renderSha256": render["render_sha256"],
                },
            )
            critic = self.critic.recover(critic_key)
            if critic is None:
                critic = self.critic.submit(
                    idempotency_key=critic_key,
                    source=self.ledger.source,
                    render_export=render,
                    semantic_analysis=self.semantic_analysis,
                )
            critic = validate_growth_critic_export(
                critic,
                expected_source_id=self.ledger.source["sourceId"],
                expected_render_sha256=render["render_sha256"],
                allow_synthetic=self.allow_synthetic,
            )
            self.ledger.append_once(
                f"critic-result:{candidate_id}",
                "critic_result",
                {"critic": critic},
            )
        else:
            critic = existing_critic["critic"]
        return {
            "candidateId": candidate_id,
            "plan": _clone(plan),
            "render": _clone(render),
            "critic": _clone(critic),
        }

    def _round_records(
        self,
        round_index: int,
    ) -> list[dict[str, Any]]:
        plans = [
            event["plan"]
            for event in self.ledger.events_of("candidate_planned")
            if event["plan"]["roundIndex"] == round_index
        ]
        return [
            self._execute_candidate(plan)
            for plan in sorted(plans, key=lambda item: item["candidateId"])
        ]

    def _decision(
        self,
        *,
        round_index: int,
        records: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        decision = select_round(
            records,
            config=self.ledger.config,
            round_index=round_index,
        )
        self.ledger.append_once(
            f"decision:{round_index}",
            "round_decision",
            {"decision": decision},
        )
        return decision

    def run(self) -> dict[str, Any]:
        final = self.ledger.event_payload("loop:terminal")
        if final is not None:
            return _clone(final["result"])

        if not self.ledger.events_of("candidate_planned"):
            initial = build_initial_plans(
                loop_id=self.ledger.loop_id,
                semantic_analysis=self.semantic_analysis,
                style_decision=self.style_decision,
                directives=self.semantic_directives,
                count=self.ledger.config.candidate_count,
            )
            self._record_plans(initial)

        for round_index in range(0, self.ledger.config.max_rounds + 1):
            records = self._round_records(round_index)
            decision = self._decision(
                round_index=round_index,
                records=records,
            )
            if decision["state"] == "winner":
                winner = next(
                    item
                    for item in records
                    if item["candidateId"]
                    == decision["winnerCandidateId"]
                )
                result = self._final_bundle(
                    winner=winner,
                    decision=decision,
                )
                self.ledger.append_once(
                    "loop:terminal",
                    "loop_terminal",
                    {"result": result},
                )
                return result
            if round_index >= self.ledger.config.max_rounds:
                result = self._human_review_pack(
                    records=records,
                    decision=decision,
                )
                self.ledger.append_once(
                    "loop:terminal",
                    "loop_terminal",
                    {"result": result},
                )
                return result

            eligible_records = [
                record
                for record in records
                if evaluate_critic(
                    record["critic"],
                    config=self.ledger.config,
                )["state"]
                != "hard_failure"
            ]
            if not eligible_records:
                result = self._human_review_pack(
                    records=records,
                    decision=decision,
                )
                self.ledger.append_once(
                    "loop:terminal",
                    "loop_terminal",
                    {"result": result},
                )
                return result

            ranked_for_reedit = sorted(
                eligible_records,
                key=lambda item: (
                    -float(
                        evaluate_critic(
                            item["critic"],
                            config=self.ledger.config,
                        )["score"]
                        or -1.0
                    ),
                    item["candidateId"],
                ),
            )
            reedit_plans = []
            for record in ranked_for_reedit[:2]:
                reedit_plans.append(
                    build_reedit_plan(
                        parent_plan=record["plan"],
                        critic=record["critic"],
                        round_index=round_index + 1,
                    )
                )
            self._record_plans(reedit_plans)

        raise EditorLoopError("unreachable editor-loop state")

    def _lineage(self) -> dict[str, Any]:
        return {
            "loopId": self.ledger.loop_id,
            "sourceId": self.ledger.source["sourceId"],
            "sourceSha256": self.ledger.source["sha256"],
            "briefDigest": self.ledger.brief_digest,
            "semanticAnalysisDigest": self.ledger.semantic_digest,
            "semanticDirectivesDigest": self.ledger.directives_digest,
            "ledgerDigest": self.ledger.digest,
            "growthCriticPin": GROWTH_CRITIC_PIN,
            "mediaRenderExport": MEDIA_RENDER_EXPORT_OBSERVED,
        }

    def _final_bundle(
        self,
        *,
        winner: Mapping[str, Any],
        decision: Mapping[str, Any],
    ) -> dict[str, Any]:
        result = {
            "contractVersion": FINAL_BUNDLE_VERSION,
            "state": "final_bundle",
            "winnerCandidateId": winner["candidateId"],
            "roundIndex": decision["roundIndex"],
            "render": winner["render"],
            "critic": winner["critic"],
            "decision": decision,
            "lineage": self._lineage(),
            "humanReviewRequired": False,
            "humanLevelQualityClaimed": False,
        }
        result["bundleDigest"] = _sha(result)
        return result

    def _human_review_pack(
        self,
        *,
        records: Sequence[Mapping[str, Any]],
        decision: Mapping[str, Any],
    ) -> dict[str, Any]:
        result = {
            "contractVersion": HUMAN_REVIEW_VERSION,
            "state": "human_review",
            "reason": decision["reason"],
            "decisionState": decision["state"],
            "roundIndex": decision["roundIndex"],
            "candidates": sorted(
                [_clone(item) for item in records],
                key=lambda item: item["candidateId"],
            ),
            "decision": decision,
            "lineage": self._lineage(),
            "humanReviewRequired": True,
            "humanLevelQualityClaimed": False,
        }
        result["reviewPackDigest"] = _sha(result)
        return result


def synthetic_semantic_context() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    source_sha = "a" * 64
    adapters = sd.SemanticAdapters(
        asr=sd.FixtureAdapter(
            "r22_asr",
            (
                {
                    "evidenceType": "transcript_segment",
                    "startMs": 0,
                    "endMs": 2200,
                    "value": {
                        "text": "Here is the problem and the result.",
                        "speechEnergy": 0.8,
                    },
                    "confidence": 0.95,
                },
                {
                    "evidenceType": "transcript_segment",
                    "startMs": 2200,
                    "endMs": 6000,
                    "value": {
                        "text": "This proof shows why the change works.",
                        "speechEnergy": 0.82,
                    },
                    "confidence": 0.94,
                },
            ),
            ("transcriptSegments",),
        ),
        shot=sd.FixtureAdapter(
            "r22_shot",
            (
                {
                    "evidenceType": "shot_boundary",
                    "startMs": 2300,
                    "endMs": 2301,
                    "value": {"boundaryMs": 2300},
                    "confidence": 0.9,
                },
                {
                    "evidenceType": "motion_energy",
                    "startMs": 0,
                    "endMs": 6000,
                    "value": {
                        "normalizedEnergy": 0.45,
                        "basis": "synthetic fixture",
                    },
                    "confidence": 0.9,
                },
            ),
            ("shotBoundaries", "motionEnergy"),
        ),
        cv=sd.FixtureAdapter(
            "r22_cv",
            (
                {
                    "evidenceType": "important_object",
                    "startMs": 2500,
                    "endMs": 5200,
                    "value": {
                        "kind": "screen",
                        "label": "proof screen",
                        "isReveal": True,
                    },
                    "confidence": 0.91,
                },
            ),
            ("importantObjects",),
        ),
        vlm=sd.FixtureAdapter(
            "r22_vlm",
            (
                {
                    "evidenceType": "semantic_event",
                    "startMs": 0,
                    "endMs": 1600,
                    "value": {
                        "event": "hook",
                        "basis": "synthetic fixture",
                    },
                    "confidence": 0.9,
                },
                {
                    "evidenceType": "semantic_event",
                    "startMs": 2500,
                    "endMs": 5200,
                    "value": {
                        "event": "proof_demo",
                        "basis": "synthetic fixture",
                    },
                    "confidence": 0.92,
                },
            ),
            ("semanticEvents",),
        ),
    )
    analysis = sd.analyze_video(
        "synthetic-r22.mp4",
        input_sha256=source_sha,
        duration_ms=6000,
        width=1080,
        height=1920,
        fps=30.0,
        has_audio=True,
        brief="Make the proof clear and concise.",
        adapters=adapters,
    )
    style = sd.select_editorial_mode(analysis)
    directives = sd.generate_edit_directives(analysis, style)
    return analysis, style, directives


def run_synthetic_rehearsal(
    work_dir: str | os.PathLike[str],
    *,
    scenario: str = "reedit_winner",
    inject_lost_ack: bool = True,
) -> dict[str, Any]:
    root = Path(work_dir)
    root.mkdir(parents=True, exist_ok=True)
    analysis, style, directives = synthetic_semantic_context()
    source = {
        "sourceId": "r22-synthetic-source",
        "sha256": analysis["source"]["sha256"],
        "durationMs": analysis["source"]["durationMs"],
    }
    brief_digest = analysis["briefDigest"]
    loop_id = "editor-loop22:" + _sha(
        {
            "source": source,
            "briefDigest": brief_digest,
            "semanticDigest": analysis["analysisDigest"],
        }
    )
    config = LoopConfig().validate()
    initial = build_initial_plans(
        loop_id=loop_id,
        semantic_analysis=analysis,
        style_decision=style,
        directives=directives,
        count=config.candidate_count,
    )
    lost_render_key = "render:" + initial[0]["candidateId"]
    lost_critic_key = "critic:" + initial[1]["candidateId"]
    media = SyntheticMediaRenderAdapter(
        lost_ack_once_for={lost_render_key} if inject_lost_ack else set()
    )
    critic = SyntheticGrowthCriticAdapter(
        scenario=scenario,
        lost_ack_once_for={lost_critic_key} if inject_lost_ack else set(),
    )
    ledger_path = root / "editor-loop.jsonl"
    ledger = LoopLedger(
        ledger_path,
        loop_id=loop_id,
        source=source,
        brief_digest=brief_digest,
        semantic_digest=analysis["analysisDigest"],
        directives_digest=directives["directivesDigest"],
        config=config,
    )
    loop = AutonomousEditorLoop(
        ledger=ledger,
        semantic_analysis=analysis,
        style_decision=style,
        semantic_directives=directives,
        media=media,
        critic=critic,
        allow_synthetic=True,
    )
    restarts = 0
    while True:
        try:
            result = loop.run()
            break
        except InjectedLostAck:
            restarts += 1
            ledger = LoopLedger(
                ledger_path,
                loop_id=loop_id,
                source=source,
                brief_digest=brief_digest,
                semantic_digest=analysis["analysisDigest"],
                directives_digest=directives["directivesDigest"],
                config=config,
            )
            loop = AutonomousEditorLoop(
                ledger=ledger,
                semantic_analysis=analysis,
                style_decision=style,
                semantic_directives=directives,
                media=media,
                critic=critic,
                allow_synthetic=True,
            )
    report = {
        "reportVersion": REHEARSAL_VERSION,
        "state": "SYNTHETIC_REHEARSAL_GREEN",
        "scenario": scenario,
        "terminalState": result["state"],
        "terminalRoundIndex": result["roundIndex"],
        "restartCount": restarts,
        "mediaAcceptedEffects": media.accepted_effects,
        "mediaSubmitCalls": media.submit_calls,
        "criticAcceptedEffects": critic.accepted_effects,
        "criticSubmitCalls": critic.submit_calls,
        "source": source,
        "briefDigest": brief_digest,
        "semanticDigest": analysis["analysisDigest"],
        "directivesDigest": directives["directivesDigest"],
        "ledgerDigest": ledger.digest,
        "growthCriticPin": GROWTH_CRITIC_PIN,
        "mediaRenderExport": MEDIA_RENDER_EXPORT_OBSERVED,
        "humanLevelQualityClaimed": False,
        "productionMediaRenderExportReady": False,
    }
    if result["state"] == "final_bundle":
        report["winnerCandidateId"] = result["winnerCandidateId"]
        report["terminalDigest"] = result["bundleDigest"]
    else:
        report["winnerCandidateId"] = None
        report["terminalDigest"] = result["reviewPackDigest"]
    report["reportDigest"] = _sha(report)
    (root / "rehearsal-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "terminal-result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="creator-editor-loop-r22",
        description="R22 bounded autonomous editor synthetic rehearsal",
    )
    parser.add_argument("--work-dir", required=True)
    parser.add_argument(
        "--scenario",
        choices=("reedit_winner", "insufficient", "contradictory"),
        default="reedit_winner",
    )
    parser.add_argument(
        "--no-lost-ack",
        action="store_true",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_synthetic_rehearsal(
        args.work_dir,
        scenario=args.scenario,
        inject_lost_ack=not args.no_lost_ack,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
