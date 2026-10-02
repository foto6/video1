from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

GROWTH_SHA = "2d3bf275c5b456d53384073fb7ec1ed992e6b996"

DIMENSIONS = {
    "hook": "hook_clarity_first_1_3s",
    "pacing": "pacing_coherence",
    "semantic_cut_correctness": "semantic_cut_correctness",
    "framing_crop": "subject_framing_crop_quality",
    "broll_relevance": "broll_relevance",
    "captions": "caption_readability_emphasis_relevance",
    "continuity": "visual_continuity",
    "motion_appropriateness": "motion_zoom_appropriateness",
    "audio_balance": "audio_voice_music_balance",
    "payoff_cta_loop": "payoff_cta_loop_coherence",
}


def _head(checkout: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=checkout,
        text=True,
    ).strip()


def _score_base(round_index: int, ordinal: int, scenario: str) -> float | None:
    if scenario == "insufficient_evidence":
        return 0.65
    if scenario in {"tie", "human_review_required"}:
        return {0: 0.72, 1: 0.82, 2: 0.88}.get(round_index, 0.72)
    if round_index == 0:
        return 0.72
    if round_index == 1:
        return 0.82
    return 0.92 if ordinal == 0 else 0.76


def _critic_export(
    *,
    source_id: str,
    render_sha: str,
    round_index: int,
    ordinal: int,
    scenario: str,
) -> dict:
    base = _score_base(round_index, ordinal, scenario)
    observations = {}
    for index, (rubric, source_dimension) in enumerate(DIMENSIONS.items()):
        available = not (
            scenario == "insufficient_evidence" and index >= 3
        )
        score = None
        confidence = 0.0
        evidence = []
        limitation = "intentionally unavailable in R24 insufficient-evidence fixture"
        unavailable = limitation
        if available:
            score = max(0.0, min(1.0, float(base) - (index % 3) * 0.01))
            confidence = 0.82
            evidence = [
                "r24:real_render_hash:" + render_sha,
                "r24:structural_fixture:" + rubric,
            ]
            limitation = None
            unavailable = None
        observations[rubric] = {
            "source_dimension": source_dimension,
            "rule_observation": {
                "available": available,
                "normalized_score": score,
                "confidence": confidence,
                "evidence": evidence,
                "limitation": limitation,
                "human_ground_truth": False,
            },
            "vlm_observations": [],
            "unavailable": unavailable,
        }
    timecoded = []
    for idx, rubric in enumerate(("hook", "pacing", "captions")):
        if observations[rubric]["rule_observation"]["available"]:
            timecoded.append({
                "start_ms": 300 + idx * 500,
                "end_ms": 900 + idx * 500,
                "evidence_kind": "structural_heuristic",
                "human_ground_truth": False,
                "note": "R24 bounded structural cue for targeted re-edit",
                "rubric_dimension": rubric,
                "severity": "warning",
                "source_dimension": DIMENSIONS[rubric],
            })
    return {
        "contract_version": "growth.critic_export.v1",
        "repository": "foto6/video3",
        "commit_sha": GROWTH_SHA,
        "source_id": source_id,
        "render_sha256": render_sha,
        "critic_mode": "structural_rule",
        "model_or_rule_identity": {
            "kind": "rule",
            "contract_version": "creator.r24.real_render_structural_fixture.v1",
            "mode": "deterministic_structural",
            "model": None,
            "provider": None,
        },
        "dimension_observations": observations,
        "timecoded_evidence": timecoded,
        "hard_failure_observations": [],
        "pairwise_if_used": None,
        "human_ground_truth": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--growth-checkout", required=True)
    parser.add_argument("--request", required=True)
    args = parser.parse_args()

    checkout = Path(args.growth_checkout).resolve()
    if _head(checkout) != GROWTH_SHA:
        raise SystemExit("Growth checkout HEAD mismatch")
    sys.path.insert(0, str(checkout))
    from growth_analytics.candidate_decision import build_candidate_decision
    from growth_analytics.critic_export import validate_critic_export

    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    if request.get("contractVersion") != "creator.growth_r18_decision_request.r24.v1":
        raise SystemExit("Growth request contract mismatch")
    if request.get("growthProducerSha") != GROWTH_SHA:
        raise SystemExit("Growth request producer SHA mismatch")
    scenario = request["scenario"]
    candidates = []
    critic_exports = {}
    for item in request["candidates"]:
        critic = validate_critic_export(_critic_export(
            source_id=request["sourceId"],
            render_sha=item["renderSha256"],
            round_index=request["roundIndex"],
            ordinal=item["ordinal"],
            scenario=scenario,
        ))
        critic_exports[item["candidateId"]] = critic
        candidates.append({
            "candidate_id": item["candidateId"],
            "source_id": request["sourceId"],
            "source_sha256": request["sourceSha256"],
            "render_sha256": item["renderSha256"],
            "critic_export": critic,
        })
    decision = build_candidate_decision(
        campaign_id=request["campaignId"],
        source_id=request["sourceId"],
        source_sha256=request["sourceSha256"],
        cycle_revision=1,
        decision_revision=request["decisionRevision"],
        expected_candidate_ids=[
            item["candidateId"] for item in request["candidates"]
        ],
        candidates=candidates,
    )
    print(json.dumps({
        "contractVersion": "creator.growth_r18_decision_result.r24.v1",
        "producerSha": GROWTH_SHA,
        "decision": decision,
        "criticExports": critic_exports,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
