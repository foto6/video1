from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import autonomous_editor_loop as r22
from . import autonomous_reels as reels
from . import editor_publish_handoff as r23
from . import publish_execution as r21

CONTRACT = "creator.closed_loop_rehearsal.v1"
LEDGER_VERSION = "creator.closed_loop_rehearsal_ledger.v1"
MEDIA_REQUEST = "creator.media_r15_render_request.r24.v1"
GROWTH_REQUEST = "creator.growth_r18_decision_request.r24.v1"

MEDIA_SHA = "a17f782da8144d1e890ac83195396a3192df93c2"
MEDIA_CI = "36860193113"
MEDIA_MANIFEST_BLOB = "945acb01ff0269d89b91463aa8d862f500e055b2"
MEDIA_SCHEMA_BLOB = "6353d32d785a2a1f1441bac4cfd0271b46b41d4a"

GROWTH_SHA = "2d3bf275c5b456d53384073fb7ec1ed992e6b996"
GROWTH_CI = "36859378847"
GROWTH_MANIFEST_BLOB = "05e778e7a67556b66cb407e2c65a2f7bb391dbab"
GROWTH_SCHEMA_BLOB = "75a3efbb8a4e14789508dae11ae8db92723d0e27"

CREATOR_R22_SHA = "351df0d455557fb20b47f0fd2ab806c4281ed5ee"
CREATOR_R23_SHA = "8914a1207241115a9cb9e1d666a3cf6955ec4190"

GROWTH_R18_DIMENSION_MAP = {
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
GROWTH_R18_CRITIC_MODES = {
    "structural_rule",
    "vlm_augmented",
    "gemini_native_video",
}


class ClosedLoopError(ValueError):
    pass


class PinMismatch(ClosedLoopError):
    pass


class StaleArtifact(ClosedLoopError):
    pass


class OutOfOrderDecision(ClosedLoopError):
    pass


def _clone(value: Any) -> Any:
    return json.loads(reels.canonical_json(value))


def _sha(value: Any) -> str:
    return reels.sha256_json(value)


def _git_head(path: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=path, text=True
    ).strip()


def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    ).hexdigest()


def verify_checkout_pins(media_checkout: Path, growth_checkout: Path) -> dict[str, Any]:
    media_checkout = media_checkout.resolve()
    growth_checkout = growth_checkout.resolve()
    if _git_head(media_checkout) != MEDIA_SHA:
        raise PinMismatch("Media checkout is not exact R15 producer SHA")
    if _git_head(growth_checkout) != GROWTH_SHA:
        raise PinMismatch("Growth checkout is not exact R18 producer SHA")
    media_manifest = media_checkout / "conformance" / "media.render_export.v1" / "manifest.json"
    media_schema = media_checkout / "conformance" / "media.render_export.v1" / "schema.json"
    growth_manifest = growth_checkout / "conformance" / "growth.candidate_decision.v1" / "manifest.json"
    growth_schema = growth_checkout / "conformance" / "growth.candidate_decision.v1" / "schema.json"
    observed = {
        "media": {
            "producerSha": _git_head(media_checkout),
            "ciRunId": MEDIA_CI,
            "manifestBlobSha": _git_blob_sha(media_manifest),
            "schemaBlobSha": _git_blob_sha(media_schema),
        },
        "growth": {
            "producerSha": _git_head(growth_checkout),
            "ciRunId": GROWTH_CI,
            "manifestBlobSha": _git_blob_sha(growth_manifest),
            "schemaBlobSha": _git_blob_sha(growth_schema),
        },
    }
    if observed["media"]["manifestBlobSha"] != MEDIA_MANIFEST_BLOB:
        raise PinMismatch("Media manifest blob drift")
    if observed["media"]["schemaBlobSha"] != MEDIA_SCHEMA_BLOB:
        raise PinMismatch("Media schema blob drift")
    if observed["growth"]["manifestBlobSha"] != GROWTH_MANIFEST_BLOB:
        raise PinMismatch("Growth manifest blob drift")
    if observed["growth"]["schemaBlobSha"] != GROWTH_SCHEMA_BLOB:
        raise PinMismatch("Growth schema blob drift")
    return observed


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.events: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            event = json.loads(line)
            material = dict(event)
            digest = material.pop("eventDigest", None)
            if event.get("ledgerVersion") != LEDGER_VERSION or _sha(material) != digest:
                raise ClosedLoopError("closed-loop ledger corruption")
            if event.get("sequence") != len(self.events) + 1:
                raise ClosedLoopError("closed-loop ledger sequence mismatch")
            if event["eventKey"] in self.by_key:
                raise ClosedLoopError("closed-loop duplicate durable key")
            self.events.append(event)
            self.by_key[event["eventKey"]] = event

    def append_once(self, key: str, event_type: str, payload: Mapping[str, Any]) -> str:
        reels._reject_secrets(payload)
        normalized = _clone(payload)
        prior = self.by_key.get(key)
        if prior is not None:
            if prior["eventType"] != event_type or prior["payload"] != normalized:
                raise ClosedLoopError("conflicting durable replay")
            return "duplicate"
        event = {
            "ledgerVersion": LEDGER_VERSION,
            "sequence": len(self.events) + 1,
            "eventKey": key,
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
        self.by_key[key] = event
        return "committed"

    @property
    def digest(self) -> str:
        return _sha(self.events)


def _source_context(source_path: Path, brief: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    asset = r21.probe_media(source_path)
    if asset.width * 16 != asset.height * 9:
        raise ClosedLoopError("source must be exact 9:16")
    if not 15 <= asset.duration_seconds <= 60:
        raise ClosedLoopError("source duration must be 15-60 seconds")
    analysis, style, directives = r22.synthetic_semantic_context()
    analysis = _clone(analysis)
    analysis["source"]["sourceId"] = "r24-source:" + asset.sha256[:16]
    analysis["source"]["sha256"] = asset.sha256
    analysis["source"]["durationMs"] = int(round(asset.duration_seconds * 1000))
    analysis["source"]["width"] = asset.width
    analysis["source"]["height"] = asset.height
    analysis["source"]["fps"] = asset.fps
    analysis["source"]["hasAudio"] = asset.audio_codec is not None
    analysis["briefDigest"] = _sha({"brief": brief.strip()})
    core = dict(analysis)
    core.pop("analysisDigest")
    analysis["analysisDigest"] = _sha(core)
    style = _clone(style)
    style["analysisDigest"] = analysis["analysisDigest"]
    directives = _clone(directives)
    directives["directivesDigest"] = _sha(
        {k: v for k, v in directives.items() if k != "directivesDigest"}
    )
    return analysis, style, directives


def _run_json(cmd: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
    proc = subprocess.run(
        cmd, cwd=cwd, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False
    )
    if proc.returncode != 0:
        raise ClosedLoopError(
            "external tool failed: " + " ".join(cmd[:3]) + "\n" + proc.stderr[-4000:]
        )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise ClosedLoopError("external tool returned no JSON")
    return json.loads(lines[-1])


def _media_request(
    *,
    source_path: Path, source: Mapping[str, Any],
    plan: Mapping[str, Any], directives: Mapping[str, Any],
) -> dict[str, Any]:
    request = {
        "contractVersion": MEDIA_REQUEST,
        "mediaProducerSha": MEDIA_SHA,
        "source": {
            "sourceId": source["sourceId"],
            "sha256": source["sha256"],
            "sizeBytes": source_path.stat().st_size,
            "durationMs": source["durationMs"],
            "path": str(source_path.resolve()),
        },
        "plan": _clone(plan),
        "mediaHints": _clone(directives.get("mediaHints", {})),
    }
    request["requestDigest"] = _sha(request)
    return request


def _adapt_media_export(
    result: Mapping[str, Any],
    *, source: Mapping[str, Any], plan: Mapping[str, Any],
) -> dict[str, Any]:
    if result.get("contractVersion") != "creator.media_r15_render_result.r24.v1":
        raise ClosedLoopError("Media helper result contract mismatch")
    if result.get("actualMediaProducerInvoked") is not True:
        raise ClosedLoopError("Media helper did not invoke real producer")
    bridge_cwd = Path(result.get("bridgeCwd", "")).resolve()
    sandbox_root = Path(result.get("sandboxRoot", "")).resolve()
    if bridge_cwd != sandbox_root:
        raise ClosedLoopError(
            "Media bridge cwd is not bound to candidate sandbox root"
        )
    if result.get("sourceUri") != "inputs/source.mp4":
        raise ClosedLoopError(
            "Media timeline source URI must remain sandbox-relative"
        )
    export = result["renderExport"]
    if export["contractVersion"] != "media.render_export.v1":
        raise ClosedLoopError("Media export contract mismatch")
    if export["producer"] != {"repository": "foto6/video2", "sha": MEDIA_SHA}:
        raise PinMismatch("Media export producer SHA mismatch")
    artifact = export["artifact"]
    final_path = Path(result["finalPath"])
    actual_sha = hashlib.sha256(final_path.read_bytes()).hexdigest()
    if artifact["sha256"] != actual_sha:
        raise StaleArtifact("Media export SHA does not match final.mp4 bytes")
    if export["qa"]["technical"]["passed"] is not True:
        raise ClosedLoopError("Media technical QA failed")
    if export["qa"]["creative"]["passed"] is not True:
        raise ClosedLoopError("Media creative QA failed")
    value = {
        "contract_version": r22.MEDIA_RENDER_EXPORT_VERSION,
        "repository": "foto6/video2",
        "commit_sha": MEDIA_SHA,
        "source_class": "synthetic_fixture",
        "source_id": source["sourceId"],
        "source_sha256": source["sha256"],
        "candidate_id": plan["candidateId"],
        "round_index": plan["roundIndex"],
        "plan_digest": plan["planDigest"],
        "render_sha256": actual_sha,
        "timeline_digest": export["provenance"]["timelineDigest"],
        "artifact_manifest_digest": export["artifact"]["artifactManifestDigest"],
        "technical_qa": {
            "passed": True,
            "qa_digest": export["qa"]["technical"]["sha256"],
            "checks": export["qa"]["technical"]["value"]["checks"],
        },
        "render_provenance": {
            "adapter": "creator-r24-exact-media-r15",
            "ordinal": plan["ordinal"],
            "roundIndex": plan["roundIndex"],
            "mediaR15ExportDigest": result["renderExportDigest"],
            "mediaR15ProducerSha": MEDIA_SHA,
            "actualMediaProducerInvoked": True,
            "bridgeCwdBoundToSandbox": True,
            "sourceUri": "inputs/source.mp4",
            "humanLevelQuality": "HUMAN_LEVEL_UNPROVEN",
        },
        "human_ground_truth": False,
    }
    # R22's old production check predates the accepted R15 pin; validate the same
    # exact shape in conformance mode, while preserving the real producer identity.
    return r22.validate_media_render_export(
        value,
        expected_source_id=source["sourceId"],
        expected_source_sha256=source["sha256"],
        expected_candidate_id=plan["candidateId"],
        expected_plan_digest=plan["planDigest"],
        allow_synthetic=True,
    )


def _growth_request(
    *, source: Mapping[str, Any], records: Sequence[Mapping[str, Any]],
    round_index: int, scenario: str,
) -> dict[str, Any]:
    return {
        "contractVersion": GROWTH_REQUEST,
        "growthProducerSha": GROWTH_SHA,
        "campaignId": "r24-exact-pin-rehearsal",
        "sourceId": source["sourceId"],
        "sourceSha256": source["sha256"],
        "roundIndex": round_index,
        "decisionRevision": round_index + 1,
        "scenario": scenario,
        "candidates": [
            {
                "candidateId": record["candidateId"],
                "ordinal": record["plan"]["ordinal"],
                "renderSha256": record["render"]["render_sha256"],
                "mediaRenderExportDigest": record["render"]["render_provenance"][
                    "mediaR15ExportDigest"
                ],
            }
            for record in records
        ],
    }


def _validate_growth_r18_critic_export(
    value: Mapping[str, Any],
    *,
    expected_source_id: str,
    expected_render_sha256: str,
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
        raise ClosedLoopError("Growth R18 critic export fields mismatch")
    if value["contract_version"] != "growth.critic_export.v1":
        raise ClosedLoopError("Growth R18 critic contract mismatch")
    if value["repository"] != "foto6/video3":
        raise PinMismatch("Growth R18 critic repository mismatch")
    if value["commit_sha"] != GROWTH_SHA:
        raise PinMismatch("Growth R18 critic producer SHA mismatch")
    if value["source_id"] != expected_source_id:
        raise ClosedLoopError("Growth R18 critic source mismatch")
    if value["render_sha256"] != expected_render_sha256:
        raise StaleArtifact("Growth R18 critic render SHA mismatch")
    if value["critic_mode"] not in GROWTH_R18_CRITIC_MODES:
        raise ClosedLoopError("Growth R18 critic mode mismatch")
    if value["human_ground_truth"] is not False:
        raise ClosedLoopError("Growth R18 critic cannot be human ground truth")

    identity = value["model_or_rule_identity"]
    if (
        not isinstance(identity, Mapping)
        or identity.get("kind") not in {"rule", "vlm"}
    ):
        raise ClosedLoopError("Growth R18 critic identity mismatch")

    dimensions = value["dimension_observations"]
    if (
        not isinstance(dimensions, Mapping)
        or set(dimensions) != set(GROWTH_R18_DIMENSION_MAP)
    ):
        raise ClosedLoopError("Growth R18 critic dimensions mismatch")
    for rubric, source_dimension in GROWTH_R18_DIMENSION_MAP.items():
        item = dimensions[rubric]
        if (
            not isinstance(item, Mapping)
            or set(item)
            != {
                "source_dimension",
                "rule_observation",
                "vlm_observations",
                "unavailable",
            }
        ):
            raise ClosedLoopError("Growth R18 critic dimension fields mismatch")
        if item["source_dimension"] != source_dimension:
            raise ClosedLoopError("Growth R18 critic dimension mapping drift")
        rule = item["rule_observation"]
        if (
            not isinstance(rule, Mapping)
            or set(rule)
            != {
                "available",
                "normalized_score",
                "confidence",
                "evidence",
                "limitation",
                "human_ground_truth",
            }
        ):
            raise ClosedLoopError("Growth R18 rule observation fields mismatch")
        if rule["human_ground_truth"] is not False:
            raise ClosedLoopError("Growth R18 rule cannot be human ground truth")
        confidence = rule["confidence"]
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= float(confidence) <= 1
        ):
            raise ClosedLoopError("Growth R18 rule confidence invalid")
        if not isinstance(rule["evidence"], list):
            raise ClosedLoopError("Growth R18 rule evidence invalid")
        if rule["available"]:
            score = rule["normalized_score"]
            if (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not 0 <= float(score) <= 1
                or item["unavailable"] is not None
            ):
                raise ClosedLoopError("Growth R18 available rule score invalid")
        else:
            if (
                rule["normalized_score"] is not None
                or not isinstance(item["unavailable"], str)
                or not item["unavailable"]
            ):
                raise ClosedLoopError("Growth R18 unavailable rule invalid")
        if not isinstance(item["vlm_observations"], list):
            raise ClosedLoopError("Growth R18 VLM observations invalid")
        for observation in item["vlm_observations"]:
            if (
                not isinstance(observation, Mapping)
                or observation.get("human_ground_truth") is not False
            ):
                raise ClosedLoopError("Growth R18 VLM human boundary invalid")

    if not isinstance(value["timecoded_evidence"], list):
        raise ClosedLoopError("Growth R18 timecoded evidence invalid")
    for evidence in value["timecoded_evidence"]:
        if (
            not isinstance(evidence, Mapping)
            or evidence.get("human_ground_truth") is not False
            or evidence.get("rubric_dimension") not in GROWTH_R18_DIMENSION_MAP
            or evidence.get("source_dimension")
            not in set(GROWTH_R18_DIMENSION_MAP.values())
        ):
            raise ClosedLoopError("Growth R18 timecoded evidence drift")

    if not isinstance(value["hard_failure_observations"], list):
        raise ClosedLoopError("Growth R18 hard failure evidence invalid")
    for item in value["hard_failure_observations"]:
        if (
            not isinstance(item, Mapping)
            or item.get("human_ground_truth") is not False
        ):
            raise ClosedLoopError("Growth R18 hard failure human boundary invalid")
    if value["pairwise_if_used"] is not None:
        raise ClosedLoopError("R24 does not consume pairwise critic evidence")
    return _clone(value)


def _validate_growth_result(
    result: Mapping[str, Any], *, source: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]], previous_revision: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if result.get("contractVersion") != "creator.growth_r18_decision_result.r24.v1":
        raise ClosedLoopError("Growth helper result contract mismatch")
    if result.get("producerSha") != GROWTH_SHA:
        raise PinMismatch("Growth producer SHA mismatch")
    decision = result["decision"]
    if decision["contract_version"] != "growth.candidate_decision.v1":
        raise ClosedLoopError("Growth decision contract mismatch")
    if decision["source_sha256"] != source["sha256"]:
        raise ClosedLoopError("Growth decision source SHA mismatch")
    if decision["decision_revision"] <= previous_revision:
        raise OutOfOrderDecision("Growth decision revision did not advance")
    expected = {record["candidateId"] for record in records}
    if set(decision["expected_candidate_ids"]) != expected:
        raise ClosedLoopError("Growth decision candidate set mismatch")
    critics = result["criticExports"]
    for record in records:
        critic = _validate_growth_r18_critic_export(
            critics[record["candidateId"]],
            expected_source_id=source["sourceId"],
            expected_render_sha256=record["render"]["render_sha256"],
        )
        record["critic"] = critic
    return _clone(decision), _clone(critics)


def _r22_decision_from_growth(
    growth: Mapping[str, Any], records: Sequence[Mapping[str, Any]],
    round_index: int,
) -> dict[str, Any]:
    state = growth["decision"]
    winner = growth["winner_candidate_id"]
    result = {
        "contractVersion": r22.DECISION_VERSION,
        "roundIndex": round_index,
        "state": state if state != "insufficient_evidence" else "insufficient_evidence",
        "winnerCandidateId": winner,
        "reason": growth["reason"],
        "evaluations": [
            {
                "candidateId": record["candidateId"],
                "renderSha256": record["render"]["render_sha256"],
                "evaluation": r22.evaluate_critic(
                    record["critic"], config=r22.LoopConfig()
                ),
                "pairwisePreferredCandidateId": None,
            }
            for record in sorted(records, key=lambda x: x["candidateId"])
        ],
        "humanLevelQualityClaimed": False,
        "aestheticSuperiorityClaimed": False,
    }
    result["decisionDigest"] = _sha(result)
    return result


def _final_bundle(
    *, winner: Mapping[str, Any], decision: Mapping[str, Any],
    source: Mapping[str, Any], analysis: Mapping[str, Any],
    directives: Mapping[str, Any], ledger: Ledger,
) -> dict[str, Any]:
    bundle = {
        "contractVersion": r22.FINAL_BUNDLE_VERSION,
        "state": "final_bundle",
        "winnerCandidateId": winner["candidateId"],
        "roundIndex": decision["roundIndex"],
        "render": winner["render"],
        "critic": winner["critic"],
        "decision": decision,
        "lineage": {
            "loopId": "r24:" + source["sha256"][:24],
            "sourceId": source["sourceId"],
            "sourceSha256": source["sha256"],
            "briefDigest": analysis["briefDigest"],
            "semanticAnalysisDigest": analysis["analysisDigest"],
            "semanticDirectivesDigest": directives["directivesDigest"],
            "ledgerDigest": ledger.digest,
            "growthCriticPin": {
                **r22.GROWTH_CRITIC_PIN,
                "growthR18ProducerSha": GROWTH_SHA,
            },
            "mediaRenderExport": {
                **r22.MEDIA_RENDER_EXPORT_OBSERVED,
                "acceptedMediaR15ProducerSha": MEDIA_SHA,
                "acceptedContract": "media.render_export.v1",
                "productionPinAvailable": True,
            },
        },
        "humanReviewRequired": False,
        "humanLevelQualityClaimed": False,
    }
    bundle["bundleDigest"] = _sha(bundle)
    # Keep R23/R22 terminal semantics; exact Media R15 producer validation was
    # already performed above against checkout HEAD, manifest/schema and bytes.
    return bundle


def _review_report(
    *, state: str, source: Mapping[str, Any], pins: Mapping[str, Any],
    ledger: Ledger, round_index: int,
) -> dict[str, Any]:
    report = {
        "contractVersion": CONTRACT,
        "state": state,
        "source": _clone(source),
        "dependencyEvidence": _clone(pins),
        "reeditRounds": min(round_index, 2),
        "finalBundleDigest": None,
        "publishHandoffDigest": None,
        "liveProviderMutation": False,
        "credentialsUsed": False,
        "humanLevelQualityClaimed": False,
        "ledgerDigest": ledger.digest,
    }
    report["reportDigest"] = _sha(report)
    return report


def run_closed_loop(
    *,
    source_path: Path, brief: str, media_checkout: Path,
    growth_checkout: Path, out_dir: Path, candidates: int = 4,
    scenario: str = "winner",
) -> dict[str, Any]:
    if not 2 <= candidates <= 4:
        raise ClosedLoopError("candidate count must be 2-4")
    pins = verify_checkout_pins(media_checkout, growth_checkout)
    source_path = source_path.resolve()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    analysis, style, directives = _source_context(source_path, brief)
    source = {
        "sourceId": analysis["source"]["sourceId"],
        "sha256": analysis["source"]["sha256"],
        "durationMs": analysis["source"]["durationMs"],
    }
    ledger = Ledger(out_dir / "closed-loop-ledger.jsonl")
    ledger.append_once("start", "run_started", {
        "source": source,
        "briefDigest": analysis["briefDigest"],
        "semanticDigest": analysis["analysisDigest"],
        "directivesDigest": directives["directivesDigest"],
        "dependencyEvidence": pins,
    })
    plans = r22.build_initial_plans(
        loop_id="r24:" + source["sha256"][:24],
        semantic_analysis=analysis,
        style_decision=style,
        directives=directives,
        count=candidates,
    )
    previous_revision = 0
    total_real_media_effects = 0
    final_record = None
    final_decision = None

    for round_index in range(3):
        records = []
        for plan in plans:
            candidate_dir = out_dir / "candidates" / plan["candidateId"].replace(":", "_")
            request_path = candidate_dir / "media-request.json"
            candidate_dir.mkdir(parents=True, exist_ok=True)
            request = _media_request(
                source_path=source_path, source=source, plan=plan,
                directives=directives,
            )
            request_path.write_text(
                json.dumps(request, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = _run_json([
                "node",
                str(Path(__file__).with_name("r24_media_bridge.mjs")),
                "--media-checkout", str(media_checkout.resolve()),
                "--request", str(request_path),
                "--out", str(candidate_dir),
            ])
            total_real_media_effects += int(result["logicalEffects"])
            render = _adapt_media_export(result, source=source, plan=plan)
            record = {
                "candidateId": plan["candidateId"],
                "plan": plan,
                "render": render,
                "renderPath": result["finalPath"],
                "mediaResultDigest": _sha(result),
            }
            records.append(record)
            ledger.append_once(
                "render:" + plan["candidateId"],
                "media_r15_render",
                {
                    "candidateId": plan["candidateId"],
                    "planDigest": plan["planDigest"],
                    "renderSha256": render["render_sha256"],
                    "mediaResultDigest": record["mediaResultDigest"],
                },
            )

        growth_request = _growth_request(
            source=source, records=records,
            round_index=round_index, scenario=scenario,
        )
        growth_path = out_dir / ("growth-request-r" + str(round_index) + ".json")
        growth_path.write_text(
            json.dumps(growth_request, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        growth_result = _run_json([
            sys.executable,
            str(Path(__file__).with_name("r24_growth_bridge.py")),
            "--growth-checkout", str(growth_checkout.resolve()),
            "--request", str(growth_path),
        ])
        growth_decision, _ = _validate_growth_result(
            growth_result, source=source, records=records,
            previous_revision=previous_revision,
        )
        previous_revision = growth_decision["decision_revision"]
        ledger.append_once(
            "decision:" + str(round_index),
            "growth_r18_decision",
            {
                "decisionId": growth_decision["decision_id"],
                "decisionDigest": growth_decision["decision_digest"],
                "decisionRevision": growth_decision["decision_revision"],
                "decision": growth_decision["decision"],
                "winnerCandidateId": growth_decision["winner_candidate_id"],
            },
        )

        if growth_decision["decision"] == "winner":
            final_record = next(
                record for record in records
                if record["candidateId"] == growth_decision["winner_candidate_id"]
            )
            final_decision = _r22_decision_from_growth(
                growth_decision, records, round_index
            )
            break

        if growth_decision["decision"] == "insufficient_evidence":
            report = _review_report(
                state="insufficient_evidence", source=source, pins=pins,
                ledger=ledger, round_index=round_index,
            )
            (out_dir / "closed_loop_rehearsal.v1.json").write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return report

        if round_index >= 2:
            state = (
                "human_review_required"
                if scenario == "human_review_required"
                else "tie"
            )
            report = _review_report(
                state=state, source=source, pins=pins,
                ledger=ledger, round_index=round_index,
            )
            (out_dir / "closed_loop_rehearsal.v1.json").write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return report

        ranked = sorted(
            records,
            key=lambda record: (
                -float(
                    r22.evaluate_critic(
                        record["critic"], config=r22.LoopConfig()
                    )["score"] or -1
                ),
                record["candidateId"],
            ),
        )[:2]
        plans = [
            r22.build_reedit_plan(
                parent_plan=record["plan"],
                critic=record["critic"],
                round_index=round_index + 1,
            )
            for record in ranked
        ]

    if final_record is None or final_decision is None:
        raise ClosedLoopError("winner path produced no terminal winner")
    if final_decision["roundIndex"] > 2:
        raise ClosedLoopError("re-edit round bound exceeded")

    bundle = _final_bundle(
        winner=final_record, decision=final_decision, source=source,
        analysis=analysis, directives=directives, ledger=ledger,
    )
    final_path = out_dir / "final.mp4"
    shutil.copyfile(Path(final_record["renderPath"]), final_path)
    final_asset = r21.probe_media(final_path)
    if final_asset.sha256 != bundle["render"]["render_sha256"]:
        raise StaleArtifact("copied final.mp4 differs from winner render")

    platform = "tiktok"
    destination = "privacy:SELF_ONLY"
    authorization = r23.synthetic_release_authorization(
        bundle=bundle, platform=platform, destination=destination
    )
    handoff = r23.build_editor_publish_handoff(
        editor_bundle=bundle,
        media_asset=final_asset,
        release_authorization=authorization,
        platform=platform,
        account_id="r24-rehearsal-account",
        destination=destination,
        credential_ref="vault-ref://r24/not-resolved",
        authorization_ref="oauth-grant-ref://r24/not-resolved",
        caption="R24 closed-loop rehearsal",
        cta="Learn more",
        allow_synthetic_editor=True,
    )
    # Preparation only: do not instantiate or drive any publish provider.
    ledger.append_once("terminal", "publish_handoff_ready", {
        "winnerCandidateId": bundle["winnerCandidateId"],
        "finalRenderSha256": final_asset.sha256,
        "bundleDigest": bundle["bundleDigest"],
        "handoffDigest": handoff["handoffDigest"],
    })
    (out_dir / "editor-final-bundle.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "editor-publish-handoff.json").write_text(
        json.dumps(handoff, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report = {
        "contractVersion": CONTRACT,
        "state": "publish_handoff_ready",
        "source": source,
        "dependencyEvidence": pins,
        "creatorPins": {
            "r22": CREATOR_R22_SHA,
            "r23": CREATOR_R23_SHA,
        },
        "candidateCount": candidates,
        "reeditRounds": final_decision["roundIndex"],
        "realMediaRenderEffects": total_real_media_effects,
        "growthDecisionRevision": previous_revision,
        "growthDecisionDigest": growth_decision["decision_digest"],
        "winnerCandidateId": bundle["winnerCandidateId"],
        "finalRenderSha256": final_asset.sha256,
        "finalBundleDigest": bundle["bundleDigest"],
        "publishHandoffDigest": handoff["handoffDigest"],
        "liveProviderMutation": False,
        "providerInvoked": False,
        "credentialsUsed": False,
        "humanLevelQualityClaimed": False,
        "ledgerDigest": ledger.digest,
    }
    report["reportDigest"] = _sha(report)
    (out_dir / "closed_loop_rehearsal.v1.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="creator-closed-loop-r24")
    p.add_argument("--source", required=True)
    p.add_argument("--brief", required=True)
    p.add_argument("--media-checkout", required=True)
    p.add_argument("--growth-checkout", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--candidates", type=int, default=4)
    p.add_argument(
        "--scenario",
        choices=("winner", "tie", "insufficient_evidence", "human_review_required"),
        default="winner",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = run_closed_loop(
            source_path=Path(args.source),
            brief=args.brief,
            media_checkout=Path(args.media_checkout),
            growth_checkout=Path(args.growth_checkout),
            out_dir=Path(args.out),
            candidates=args.candidates,
            scenario=args.scenario,
        )
    except Exception as exc:
        print(json.dumps({
            "contractVersion": CONTRACT,
            "state": "BLOCKED",
            "reason": type(exc).__name__,
            "detail": str(exc),
            "liveProviderMutation": False,
        }, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
