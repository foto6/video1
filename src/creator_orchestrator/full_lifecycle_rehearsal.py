from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import autonomous_editor_loop as r22
from . import autonomous_reels as reels
from . import editor_publish_handoff as r23
from . import publish_execution as r21
from . import publish_providers as r12

LIFECYCLE_VERSION = "creator.full_lifecycle_rehearsal.r24.v1"
LEDGER_VERSION = "creator.full_lifecycle_ledger.r24.v1"
REPORT_VERSION = "creator.full_lifecycle_report.r24.v1"

PINS = {
    "creatorR22": {
        "repository": "foto6/video1",
        "sha": "351df0d455557fb20b47f0fd2ab806c4281ed5ee",
        "ciRunId": "36859291553",
    },
    "creatorR23": {
        "repository": "foto6/video1",
        "sha": "8914a1207241115a9cb9e1d666a3cf6955ec4190",
        "ciRunId": "36861170789",
    },
    "mediaR15": {
        "repository": "foto6/video2",
        "sha": "a17f782da8144d1e890ac83195396a3192df93c2",
        "ciRunId": "36860193113",
        "contract": "media.render_export.v1",
        "manifestBlobSha": "945acb01ff0269d89b91463aa8d862f500e055b2",
        "schemaBlobSha": "6353d32d785a2a1f1441bac4cfd0271b46b41d4a",
        "implementationBlobSha": "2aee865404d78eeb64e17e9aeae8f44a0c1a746e",
    },
    "growthR18": {
        "repository": "foto6/video3",
        "sha": "2d3bf275c5b456d53384073fb7ec1ed992e6b996",
        "ciRunId": "36859378847",
        "contract": "growth.candidate_decision.v1",
        "manifestBlobSha": "05e778e7a67556b66cb407e2c65a2f7bb391dbab",
        "schemaBlobSha": "75a3efbb8a4e14789508dae11ae8db92723d0e27",
        "implementationBlobSha": "0d977ac0161a1f13facf79c42f97182649b40722",
    },
    "growthR19": {
        "repository": "foto6/video3",
        "sha": "a802a1c0eed5ae564e7e67236e986bff560c58a9",
        "ciRunId": "36861560705",
        "contract": "growth.post_publish_learning.v1",
        "manifestBlobSha": "ee1864329ff80c243e8f2b653a715091374316c8",
        "schemaBlobSha": "8cc7b1ff3ea99da31865df65cb688e57cbbf0882",
        "implementationBlobSha": "78b839a954cc1375998229e40fcfe1cbfeb5c54a",
    },
}

UPSTREAM_FILES = {
    "mediaR15": {
        "manifest": "media-r15-manifest.json",
        "schema": "media-r15-schema.json",
    },
    "growthR18": {
        "manifest": "growth-r18-manifest.json",
        "schema": "growth-r18-schema.json",
    },
    "growthR19": {
        "manifest": "growth-r19-manifest.json",
        "schema": "growth-r19-schema.json",
    },
}


class LifecycleError(ValueError):
    pass


class InvariantViolation(LifecycleError):
    pass


class OutOfOrderMetrics(LifecycleError):
    pass


def _clone(value: Any) -> Any:
    return json.loads(reels.canonical_json(value))


def _sha(value: Any) -> str:
    return reels.sha256_json(value)


def _hex64(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise LifecycleError(f"{field} must be lowercase sha256")
    return value


def _git_blob_sha(text: str) -> str:
    raw = text.encode("utf-8")
    return hashlib.sha1(
        b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    ).hexdigest()


def _contract_root() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "conformance"
        / "creator.full_lifecycle_rehearsal.r24.v1"
        / "upstreams"
    )


def verify_pinned_contracts(root: Path | None = None) -> dict[str, Any]:
    root = root or _contract_root()
    result: dict[str, Any] = {}
    for name, files in UPSTREAM_FILES.items():
        pin = PINS[name]
        evidence = {}
        for kind, filename in files.items():
            path = root / filename
            if not path.is_file():
                raise InvariantViolation(
                    f"missing vendored {name} {kind}: {path}"
                )
            text = path.read_text(encoding="utf-8")
            actual = _git_blob_sha(text)
            expected = pin[kind + "BlobSha"]
            if actual != expected:
                raise InvariantViolation(
                    f"{name} {kind} blob drift: {actual} != {expected}"
                )
            payload = json.loads(text)
            evidence[kind + "BlobSha"] = actual
            evidence[kind + "Digest"] = hashlib.sha256(
                text.encode("utf-8")
            ).hexdigest()
            evidence[kind + "TopLevel"] = (
                payload.get("contractVersion")
                or payload.get("manifest_version")
                or payload.get("$id")
            )
        result[name] = {
            "producerSha": pin["sha"],
            "ciRunId": pin["ciRunId"],
            **evidence,
        }
    return result


class LifecycleLedger:
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
            if set(event) != {
                "ledgerVersion", "sequence", "eventKey",
                "eventType", "payload", "eventDigest",
            }:
                raise LifecycleError("lifecycle ledger event fields invalid")
            if event["ledgerVersion"] != LEDGER_VERSION:
                raise LifecycleError("lifecycle ledger version mismatch")
            if event["sequence"] != len(self.events) + 1:
                raise LifecycleError("lifecycle ledger sequence mismatch")
            material = dict(event)
            digest = material.pop("eventDigest")
            if _sha(material) != digest:
                raise LifecycleError("lifecycle ledger digest mismatch")
            if event["eventKey"] in self.by_key:
                raise LifecycleError("duplicate durable event key")
            reels._reject_secrets(event["payload"])
            self.events.append(event)
            self.by_key[event["eventKey"]] = event

    def append_once(
        self, key: str, event_type: str, payload: Mapping[str, Any]
    ) -> str:
        reels._reject_secrets(payload)
        normalized = _clone(payload)
        prior = self.by_key.get(key)
        if prior is not None:
            if (
                prior["eventType"] != event_type
                or prior["payload"] != normalized
            ):
                raise LifecycleError(
                    f"conflicting duplicate lifecycle event {key}"
                )
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


def validate_media_r15_export(
    value: Mapping[str, Any],
    *,
    expected_render_sha: str | None = None,
) -> dict[str, Any]:
    required = {
        "contractVersion", "status", "producer", "job", "artifact", "probe",
        "qa", "evidence", "provenance", "failure", "benchmark",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise LifecycleError("media.render_export.v1 fields drifted")
    if value["contractVersion"] != "media.render_export.v1":
        raise LifecycleError("Media R15 contract version drift")
    if value["status"] != "succeeded":
        raise LifecycleError("Media R15 render export not succeeded")
    if value["producer"] != {
        "repository": PINS["mediaR15"]["repository"],
        "sha": PINS["mediaR15"]["sha"],
    }:
        raise LifecycleError("Media R15 producer provenance drift")
    artifact = value["artifact"]
    if not isinstance(artifact, Mapping) or set(artifact) != {
        "fileName", "algorithm", "sha256", "size", "contentId",
        "artifactManifestDigest",
    }:
        raise LifecycleError("Media R15 artifact fields drifted")
    render_sha = _hex64(artifact["sha256"], "media.artifact.sha256")
    if artifact["fileName"] != "final.mp4" or artifact["algorithm"] != "sha256":
        raise LifecycleError("Media R15 artifact identity invalid")
    if expected_render_sha is not None and render_sha != expected_render_sha:
        raise InvariantViolation("Media R15 render SHA lineage mismatch")
    if value["failure"] is not None:
        raise LifecycleError("successful Media export carries failure")
    qa = value["qa"]
    if (
        not isinstance(qa, Mapping)
        or qa.get("technical", {}).get("passed") is not True
        or qa.get("creative", {}).get("passed") is not True
    ):
        raise LifecycleError("Media R15 QA failed")
    if value["benchmark"].get("technicalDq") is not False:
        raise LifecycleError("Media R15 benchmark technical DQ")
    provenance = value["provenance"]
    if provenance.get("syntheticFixtureAdapter") is not True:
        raise LifecycleError("R24 Media export must identify synthetic adapter")
    if provenance.get("actualMediaProducerInvoked") is not False:
        raise LifecycleError("synthetic rehearsal cannot claim Media invocation")
    return _clone(value)


class MediaR15SyntheticAdapter:
    """Contract-shaped Media R15 fixture adapter; never claims real producer execution."""

    def __init__(self, source_path: Path, work_dir: Path):
        self.source_path = Path(source_path)
        self.work_dir = Path(work_dir)
        self.results: dict[str, dict[str, Any]] = {}
        self.files: dict[str, Path] = {}
        self.accepted_effects = 0
        self.submit_calls = 0

    def recover(self, key: str) -> Mapping[str, Any] | None:
        return _clone(self.results[key]) if key in self.results else None

    def submit(
        self, *, idempotency_key: str, source: Mapping[str, Any],
        plan: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.submit_calls += 1
        if idempotency_key in self.results:
            return _clone(self.results[idempotency_key])
        data = self.source_path.read_bytes()
        marker = (
            b"\nR24-CANDIDATE:"
            + plan["candidateId"].encode("utf-8")
            + b":ROUND:"
            + str(plan["roundIndex"]).encode("ascii")
            + b"\n"
        )
        candidate_dir = self.work_dir / "renders" / plan["candidateId"].replace(":", "_")
        candidate_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = candidate_dir / "final.mp4"
        artifact_path.write_bytes(data + marker)
        render_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        manifest_digest = _sha({
            "candidateId": plan["candidateId"],
            "renderSha256": render_sha,
            "planDigest": plan["planDigest"],
        })
        qa_technical = {
            "sha256": _sha({"render": render_sha, "qa": "technical"}),
            "passed": True,
            "value": {"passed": True, "checks": []},
        }
        qa_creative = {
            "sha256": _sha({"render": render_sha, "qa": "creative"}),
            "passed": True,
            "value": {
                "passed": True, "guardrails": [],
                "visualQa": {"passed": True, "checks": []},
            },
        }
        export = {
            "contractVersion": "media.render_export.v1",
            "status": "succeeded",
            "producer": {
                "repository": PINS["mediaR15"]["repository"],
                "sha": PINS["mediaR15"]["sha"],
            },
            "job": {
                "logicalJobId": plan["candidateId"],
                "idempotencyKey": idempotency_key,
                "renderFingerprint": _sha({
                    "sourceSha": source["sha256"],
                    "planDigest": plan["planDigest"],
                }),
                "status": "succeeded",
            },
            "artifact": {
                "fileName": "final.mp4",
                "algorithm": "sha256",
                "sha256": render_sha,
                "size": artifact_path.stat().st_size,
                "contentId": "sha256:" + render_sha,
                "artifactManifestDigest": manifest_digest,
            },
            "probe": {
                "hasVideo": True, "hasAudio": False,
                "width": 360, "height": 640, "fps": 30,
                "durationMs": 15200, "videoCodec": "h264",
                "audioCodec": None,
            },
            "qa": {"technical": qa_technical, "creative": qa_creative},
            "evidence": {
                "sources": {
                    "count": 1,
                    "sha256": source["sha256"],
                    "items": [{"sourceId": source["sourceId"]}],
                },
                "captions": {
                    "count": 0, "sha256": _sha([]),
                    "safeAreaPassed": True, "textCharsPerSecond": 0,
                },
                "crop": {
                    "explicitCropItems": 0, "reframeItems": 1,
                    "motionItems": 0, "unsafeCropPassed": True,
                },
                "audio": {
                    "itemCount": 0, "roles": [], "maxMusicGainDb": None,
                    "hasAudio": False, "meanDb": None, "peakDb": None,
                    "silenceRatio": 1.0,
                },
            },
            "provenance": {
                "validatedRequestDigest": plan["planDigest"],
                "profileDigest": _sha({"profile": "9:16-shortform"}),
                "timelineDigest": _sha({
                    "candidateId": plan["candidateId"],
                    "roundIndex": plan["roundIndex"],
                    "deltas": plan["targetedDeltas"],
                }),
                "creativePlanDigest": plan["planDigest"],
                "sourceEvidenceDigest": source["sha256"],
                "artifactManifestDigest": manifest_digest,
                "syntheticFixtureAdapter": True,
                "actualMediaProducerInvoked": False,
            },
            "failure": None,
            "benchmark": {
                "binding": {
                    "protocol": "creator.r24.synthetic_rehearsal",
                    "producerPin": PINS["mediaR15"]["sha"],
                },
                "technicalDq": False,
                "technicalDqReasons": [],
            },
        }
        validate_media_r15_export(export)
        self.results[idempotency_key] = _clone(export)
        self.files[plan["candidateId"]] = artifact_path
        self.accepted_effects += 1
        return _clone(export)

    @staticmethod
    def to_r22(
        export: Mapping[str, Any],
        *, source: Mapping[str, Any], plan: Mapping[str, Any],
    ) -> dict[str, Any]:
        export = validate_media_r15_export(export)
        artifact = export["artifact"]
        technical = export["qa"]["technical"]
        value = {
            "contract_version": r22.MEDIA_RENDER_EXPORT_VERSION,
            "repository": PINS["mediaR15"]["repository"],
            "commit_sha": PINS["mediaR15"]["sha"],
            "source_class": "synthetic_fixture",
            "source_id": source["sourceId"],
            "source_sha256": source["sha256"],
            "candidate_id": plan["candidateId"],
            "round_index": plan["roundIndex"],
            "plan_digest": plan["planDigest"],
            "render_sha256": artifact["sha256"],
            "timeline_digest": export["provenance"]["timelineDigest"],
            "artifact_manifest_digest": artifact["artifactManifestDigest"],
            "technical_qa": {
                "passed": True,
                "qa_digest": technical["sha256"],
                "checks": technical["value"]["checks"],
            },
            "render_provenance": {
                "adapter": "MediaR15SyntheticAdapter",
                "ordinal": plan["ordinal"],
                "roundIndex": plan["roundIndex"],
                "mediaR15ExportDigest": _sha(export),
                "mediaR15ProducerPin": PINS["mediaR15"]["sha"],
                "actualMediaProducerInvoked": False,
                "humanLevelQuality": "HUMAN_LEVEL_UNPROVEN",
            },
            "human_ground_truth": False,
        }
        return r22.validate_media_render_export(
            value,
            expected_source_id=source["sourceId"],
            expected_source_sha256=source["sha256"],
            expected_candidate_id=plan["candidateId"],
            expected_plan_digest=plan["planDigest"],
            allow_synthetic=True,
        )


def _r18_evidence(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_candidate = {
        r["candidateId"]: {
            "count": len(r["critic"]["hard_failure_observations"]),
            "failures": r["critic"]["hard_failure_observations"],
        }
        for r in records
    }
    scores = {}
    for r in records:
        evaluation = r22.evaluate_critic(r["critic"], config=r22.LoopConfig())
        scores[r["candidateId"]] = evaluation["score"]
    return {
        "objective_defects": {
            "kind": "objective_defects",
            "by_candidate": by_candidate,
            "human_ground_truth": False,
        },
        "structural_rule_judgment": {
            "kind": "structural_rule",
            "comparable_dimension_count": 10,
            "comparable_dimensions": [],
            "candidate_scores": scores,
            "minimum_required": 6,
            "minimum_confidence": 0.35,
            "winner_margin": 0.08,
            "human_ground_truth": False,
        },
        "model_aesthetic_judgment": {
            "kind": "model_and_pairwise_advisory",
            "observations": [],
            "contradictions": [],
            "has_contradiction": False,
            "human_ground_truth": False,
            "per_candidate_vlm": {
                r["candidateId"]: [] for r in records
            },
        },
        "human_labels": {
            "labels": [],
            "contradictions": [],
            "has_contradiction": False,
            "human_ground_truth": None,
        },
        "live_platform_observations": [],
        "historical_metric_context": [],
    }


def build_growth_r18_decision(
    records: Sequence[Mapping[str, Any]],
    *,
    source: Mapping[str, Any],
    round_index: int,
    scenario: str,
) -> dict[str, Any]:
    expected = [r["candidateId"] for r in records]
    r22_decision = r22.select_round(
        records, config=r22.LoopConfig(), round_index=round_index
    )
    decision = r22_decision["state"]
    winner = r22_decision["winnerCandidateId"]
    if scenario == "insufficient_evidence":
        decision, winner = "insufficient_evidence", None
    elif scenario in {"tie", "human_review_required"}:
        decision, winner = "tie", None
    elif scenario in {"winner", "provider_auth_required"}:
        if round_index < 2:
            decision, winner = "tie", None
        elif decision != "winner":
            raise InvariantViolation("R22 evidence did not produce round-2 winner")
    reason = {
        "winner": "R22 structural evidence separates a complete candidate set",
        "tie": "bounded synthetic candidates remain within comparison tolerance",
        "insufficient_evidence": "synthetic evidence intentionally incomplete",
    }[decision]
    refs = [{
        "candidate_id": r["candidateId"],
        "source_id": source["sourceId"],
        "source_sha256": source["sha256"],
        "render_sha256": r["render"]["render_sha256"],
        "critic_export_commit_sha": r22.GROWTH_CRITIC_PIN["producerSha"],
        "critic_mode": r["critic"]["critic_mode"],
    } for r in sorted(records, key=lambda x: x["candidateId"])]
    material = {
        "contract_version": "growth.candidate_decision.v1",
        "decision_id": "",
        "decision_digest": "",
        "campaign_id": "r24-synthetic-campaign",
        "source_id": source["sourceId"],
        "source_sha256": source["sha256"],
        "cycle_revision": 1,
        "decision_revision": round_index + 1,
        "expected_candidate_ids": expected,
        "candidate_refs": refs,
        "missing_candidate_ids": [],
        "decision": decision,
        "winner_candidate_id": winner,
        "reason": reason,
        "evidence_policy": {
            "min_candidates": 2,
            "max_candidates": 4,
            "min_comparable_dimensions": 6,
            "min_rule_confidence": 0.35,
            "winner_margin": 0.08,
            "live_metric_freshness_required": "fresh",
            "model_score_is_human_preference": False,
            "synthetic_metric_is_live_evidence": False,
            "historical_metric_causal": False,
        },
        "evidence": _r18_evidence(records),
        "live_metric_eligibility": {
            r["candidateId"]: False for r in records
        },
        "policy_gates": [
            "synthetic_fixture_only",
            "no_live_metrics",
            "no_human_labels",
        ],
        "reedit_guidance": [],
        "authority": {
            "advisory_only": True,
            "publish_authorized": False,
            "provider_mutation": False,
            "creator_mutation": False,
            "media_mutation": False,
            "reedit_authorized": False,
        },
        "interpretation": (
            "Synthetic R24 rehearsal consumes the exact R18 contract shape. "
            "Evidence is non-human and non-live; the decision cannot authorize publication."
        ),
    }
    material["decision_id"] = "gcd1:" + _sha({
        "campaign_id": material["campaign_id"],
        "source_id": material["source_id"],
        "source_sha256": material["source_sha256"],
        "cycle_revision": 1,
        "decision_revision": round_index + 1,
        "expected_candidate_ids": expected,
    })
    digest_material = dict(material)
    digest_material["decision_digest"] = ""
    material["decision_digest"] = _sha(digest_material)
    return validate_growth_r18_decision(material)


def validate_growth_r18_decision(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "contract_version", "decision_id", "decision_digest", "campaign_id",
        "source_id", "source_sha256", "cycle_revision", "decision_revision",
        "expected_candidate_ids", "candidate_refs", "missing_candidate_ids",
        "decision", "winner_candidate_id", "reason", "evidence_policy",
        "evidence", "live_metric_eligibility", "policy_gates",
        "reedit_guidance", "authority", "interpretation",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise LifecycleError("Growth R18 decision schema drift")
    if value["contract_version"] != PINS["growthR18"]["contract"]:
        raise LifecycleError("Growth R18 contract drift")
    if value["decision"] not in {"winner", "tie", "insufficient_evidence"}:
        raise LifecycleError("Growth R18 decision state invalid")
    if not 2 <= len(value["expected_candidate_ids"]) <= 4:
        raise LifecycleError("Growth R18 candidate bound invalid")
    if value["missing_candidate_ids"]:
        raise LifecycleError("R24 decision requires complete candidate set")
    if value["decision"] == "winner":
        if value["winner_candidate_id"] not in value["expected_candidate_ids"]:
            raise LifecycleError("Growth R18 winner missing")
    elif value["winner_candidate_id"] is not None:
        raise LifecycleError("non-winner decision named winner")
    for ref in value["candidate_refs"]:
        if ref["source_sha256"] != value["source_sha256"]:
            raise InvariantViolation("Growth R18 source hash mismatch")
        _hex64(ref["render_sha256"], "Growth R18 render SHA")
    if value["authority"] != {
        "advisory_only": True, "publish_authorized": False,
        "provider_mutation": False, "creator_mutation": False,
        "media_mutation": False, "reedit_authorized": False,
    }:
        raise LifecycleError("Growth R18 authority drift")
    expected_id = "gcd1:" + _sha({
        "campaign_id": value["campaign_id"],
        "source_id": value["source_id"],
        "source_sha256": value["source_sha256"],
        "cycle_revision": value["cycle_revision"],
        "decision_revision": value["decision_revision"],
        "expected_candidate_ids": value["expected_candidate_ids"],
    })
    if value["decision_id"] != expected_id:
        raise LifecycleError("Growth R18 decision identity mismatch")
    digest_material = dict(value)
    provided = digest_material["decision_digest"]
    digest_material["decision_digest"] = ""
    if _sha(digest_material) != provided:
        raise LifecycleError("Growth R18 decision digest mismatch")
    return _clone(value)


def build_growth_publish_result(
    *, receipt: Mapping[str, Any], handoff: Mapping[str, Any],
    fixture_source_sha: str,
) -> dict[str, Any]:
    request = handoff["publishRequest"]
    media = request["media"]
    identity = {
        "platform": request["platform"],
        "account_id": request["accountId"],
        "post_id": receipt["postId"],
        "cycle_revision": 1,
        "media_artifact_digest": media["contentSha256"],
    }
    material = {
        "contract_version": "growth.shortform_publish_result.v1",
        "publish_result_id": "spr1:" + _sha(identity),
        "source_class": "synthetic_fixture",
        "platform": request["platform"],
        "account_id": request["accountId"],
        "post_id": receipt["postId"],
        "published_at": receipt["publishedAt"],
        "captured_at": receipt["publishedAt"],
        "cycle_revision": 1,
        "artifact": {
            "creative_artifact_id": handoff["editor"]["winnerCandidateId"],
            "creative_artifact_digest": handoff["editor"]["decisionDigest"],
            "media_artifact_id": media["contentId"],
            "media_artifact_digest": media["contentSha256"],
            "media_render_fingerprint": handoff["editor"]["timelineDigest"],
            "media_duration_seconds": media["durationSeconds"],
        },
        "provenance": {
            "provider_receipt_digest": None,
            "fixture_source_sha256": fixture_source_sha,
            "live_performance_claim_allowed": False,
        },
    }
    material["publish_result_digest"] = _sha(material)
    return validate_growth_publish_result(material)


def validate_growth_publish_result(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "contract_version", "publish_result_id", "publish_result_digest",
        "source_class", "platform", "account_id", "post_id", "published_at",
        "captured_at", "cycle_revision", "artifact", "provenance",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise LifecycleError("Growth publish result fields drift")
    if value["source_class"] != "synthetic_fixture":
        raise LifecycleError("R24 cannot create live publish result")
    if value["provenance"] != {
        "provider_receipt_digest": None,
        "fixture_source_sha256": value["provenance"]["fixture_source_sha256"],
        "live_performance_claim_allowed": False,
    }:
        raise LifecycleError("synthetic publish provenance invalid")
    identity = {
        "platform": value["platform"],
        "account_id": value["account_id"],
        "post_id": value["post_id"],
        "cycle_revision": value["cycle_revision"],
        "media_artifact_digest": value["artifact"]["media_artifact_digest"],
    }
    if value["publish_result_id"] != "spr1:" + _sha(identity):
        raise LifecycleError("Growth publish result identity mismatch")
    material = dict(value)
    provided = material.pop("publish_result_digest")
    if _sha(material) != provided:
        raise LifecycleError("Growth publish result digest mismatch")
    return _clone(value)


def build_synthetic_metric_snapshot(
    publish: Mapping[str, Any], *, revision: int = 1,
    window_start: str | None = None,
    window_end: str = "2026-10-01T01:00:00Z",
) -> dict[str, Any]:
    publish = validate_growth_publish_result(publish)
    if window_start is None:
        window_start = publish["published_at"]
    metrics = {
        "average_watch_duration_seconds": 7.0,
        "comments": 8,
        "completed_views": 180,
        "completion_rate": 0.18,
        "follows": 3,
        "impressions": 1800,
        "likes": 90,
        "link_clicks": 8,
        "retention_denominator_views": 1000,
        "retention_points": [
            {"position": 0.0, "retained": 1.0},
            {"position": 0.5, "retained": 0.42},
            {"position": 1.0, "retained": 0.18},
        ],
        "saves": 15,
        "shares": 25,
        "views": 1000,
        "watch_time_seconds": 7000.0,
    }
    available = sorted(metrics)
    event_identity = {
        "platform": publish["platform"],
        "account_id": publish["account_id"],
        "post_id": publish["post_id"],
        "cycle_revision": revision,
        "export_id": f"r24-synthetic-metrics-r{revision}",
        "window": {"start": window_start, "end": window_end},
    }
    event_id = "spm1:" + _sha(event_identity)
    event_digest = _sha({
        "eventIdentity": event_identity,
        "metrics": metrics,
        "sourceClass": "synthetic_fixture",
    })
    normalized = {
        "views": 1000,
        "watch_time_seconds": 7000.0,
        "average_watch_duration_seconds": 7.0,
        "completion_rate": 0.18,
        "retention_auc": 0.505,
        "likes": 90,
        "comments": 8,
        "shares": 25,
        "saves": 15,
        "follows": 3,
        "impressions": 1800,
        "link_clicks": 8,
        "link_ctr": round(8 / 1800, 8),
    }
    snapshot = {
        "contract_version": "growth.shortform_metric_snapshot.v1",
        "publish_result_id": publish["publish_result_id"],
        "publish_result_digest": publish["publish_result_digest"],
        "platform": publish["platform"],
        "account_id": publish["account_id"],
        "post_id": publish["post_id"],
        "cycle_revision": 1,
        "source_class": "synthetic_fixture",
        "live_performance_claim_allowed": False,
        "window": {"start": window_start, "end": window_end},
        "selected_metrics_event_id": event_id,
        "selected_metrics_event_digest": event_digest,
        "available_metrics": available,
        "raw_metrics": metrics,
        "normalized_metrics": normalized,
        "normalization_sources": {
            "average_watch_duration_seconds": "provider_export",
            "completion_rate": "provider_export",
            "retention_auc": "derived_from_platform_retention_curve",
            "link_ctr": "derived_link_clicks_over_impressions",
        },
        "denominators": {
            "average_watch_duration_seconds": {
                "metric": "provider_defined", "value": None,
            },
            "completion_rate": {
                "metric": "provider_defined_views", "value": 1000,
            },
            "retention_auc": {
                "metric": "retention_denominator_views", "value": 1000,
            },
            "link_ctr": {"metric": "impressions", "value": 1800},
            "engagement_rates": {"metric": "views", "value": 1000},
        },
        "uncertainty": {
            "average_watch_duration_seconds": {
                "state": "not_estimable_from_aggregate_export",
                "reason": "synthetic aggregate fixture",
            },
            "completion_rate": {
                "state": "synthetic_fixture",
                "causal": False,
            },
            "retention_auc": {
                "state": "not_estimable_from_aggregate_export",
                "reason": "synthetic aggregate fixture",
            },
            "link_ctr": {
                "state": "synthetic_fixture",
                "causal": False,
            },
            "engagement_counts": {
                "state": "descriptive_only",
                "reason": "synthetic fixture",
            },
        },
        "provenance": {
            "complete_export": True,
            "provider": "fixture",
            "export_id": event_identity["export_id"],
            "export_digest": _sha(event_identity),
            "fixture_source_sha256": publish["provenance"]["fixture_source_sha256"],
            "candidate_event_count": 1,
            "complete_event_count": 1,
            "observational": True,
            "interpretation": (
                "Synthetic performance fixture only; not live platform evidence "
                "and not causal."
            ),
        },
    }
    snapshot["snapshot_digest"] = _sha(snapshot)
    return validate_metric_snapshot(snapshot)


def validate_metric_snapshot(
    value: Mapping[str, Any],
    *, previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    required = {
        "contract_version", "publish_result_id", "publish_result_digest",
        "platform", "account_id", "post_id", "cycle_revision",
        "source_class", "live_performance_claim_allowed", "window",
        "selected_metrics_event_id", "selected_metrics_event_digest",
        "available_metrics", "raw_metrics", "normalized_metrics",
        "normalization_sources", "denominators", "uncertainty",
        "provenance", "snapshot_digest",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise LifecycleError("metric snapshot fields drift")
    if (
        value["contract_version"] != "growth.shortform_metric_snapshot.v1"
        or value["source_class"] != "synthetic_fixture"
        or value["live_performance_claim_allowed"] is not False
    ):
        raise LifecycleError("synthetic metric snapshot boundary violated")
    material = dict(value)
    provided = material.pop("snapshot_digest")
    if _sha(material) != provided:
        raise LifecycleError("metric snapshot digest mismatch")
    if previous is not None:
        if value["publish_result_id"] != previous["publish_result_id"]:
            raise OutOfOrderMetrics("metric stream publish identity changed")
        if value["window"]["end"] < previous["window"]["end"]:
            raise OutOfOrderMetrics("metric observation window moved backwards")
    return _clone(value)


def build_growth_r19_learning(
    publish: Mapping[str, Any], snapshot: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    publish = validate_growth_publish_result(publish)
    snapshot = validate_metric_snapshot(snapshot)
    decision = validate_growth_r18_decision(decision)
    render_sha = publish["artifact"]["media_artifact_digest"]
    matches = [
        ref for ref in decision["candidate_refs"]
        if ref["render_sha256"] == render_sha
    ]
    if len(matches) != 1:
        raise InvariantViolation(
            "Growth R19 decision link does not uniquely bind published render"
        )
    hypotheses = [
        {
            "hypothesis_id": "test_stronger_first_3s_pacing",
            "priority": 1,
            "testable_change": (
                "Test a faster first-3-second hook while holding CTA, "
                "duration bucket, and downstream structure constant."
            ),
            "target_metric": "average_watch_duration_seconds",
            "expected_direction": "increase",
            "evidence_refs": [
                "metric_snapshot:" + snapshot["snapshot_digest"]
                + "#normalized_metrics.average_watch_duration_seconds"
            ],
            "certainty": "directional_observational_not_causal",
            "causal_claim": False,
        },
        {
            "hypothesis_id": "test_tighter_payoff_loop",
            "priority": 2,
            "testable_change": (
                "Test a shorter payoff-to-loop ending while holding the "
                "opening hook and CTA constant."
            ),
            "target_metric": "completion_rate",
            "expected_direction": "increase",
            "evidence_refs": [
                "metric_snapshot:" + snapshot["snapshot_digest"]
                + "#normalized_metrics.completion_rate"
            ],
            "certainty": "directional_observational_not_causal",
            "causal_claim": False,
        },
    ]
    learning = {
        "contract_version": PINS["growthR19"]["contract"],
        "learning_id": "",
        "learning_digest": "",
        "learning_revision": 1,
        "source_class": "synthetic_fixture",
        "live_performance_claim_allowed": False,
        "next_cycle_id": "r24-next-cycle-1",
        "lineage": {
            "publish_result_id": publish["publish_result_id"],
            "publish_result_digest": publish["publish_result_digest"],
            "platform": publish["platform"],
            "account_id": publish["account_id"],
            "post_id": publish["post_id"],
            "cycle_revision": 1,
            "provider_receipt_digest": None,
            "media_artifact_id": publish["artifact"]["media_artifact_id"],
            "media_render_sha256": render_sha,
            "metric_snapshot_digest": snapshot["snapshot_digest"],
            "selected_metrics_event_id": snapshot["selected_metrics_event_id"],
            "observation_window": snapshot["window"],
        },
        "observed_provider_metrics": {
            key: snapshot["raw_metrics"].get(key)
            for key in (
                "average_watch_duration_seconds", "comments",
                "completed_views", "completion_rate", "follows",
                "impressions", "likes", "link_clicks",
                "retention_denominator_views", "retention_points",
                "saves", "shares", "views", "watch_time_seconds",
            )
        },
        "derived_analytics": {
            "average_watch_duration_seconds": {
                "value": snapshot["normalized_metrics"][
                    "average_watch_duration_seconds"
                ],
                "derivation": "provider_reported_normalized",
                "source": "provider_export",
            },
            "completion_rate": {
                "value": snapshot["normalized_metrics"]["completion_rate"],
                "derivation": "provider_reported_normalized",
                "source": "provider_export",
            },
            "retention_auc": {
                "value": snapshot["normalized_metrics"]["retention_auc"],
                "derivation": "derived_from_platform_retention_curve",
                "source": "derived_from_platform_retention_curve",
            },
            "link_ctr": {
                "value": snapshot["normalized_metrics"]["link_ctr"],
                "derivation": "derived_link_clicks_over_impressions",
                "source": "derived_link_clicks_over_impressions",
            },
        },
        "speculative_hypotheses": hypotheses,
        "runtime_state": {
            "state": "unavailable",
            "freshness": "unknown",
            "collector_state": "unknown",
            "lag_seconds": None,
            "error_classification": None,
            "backfill_recovery_state": "unknown",
            "unavailable_evidence": {
                "runtime_status": "R17 runtime status was not supplied"
            },
        },
        "candidate_decision": {
            "contract_version": "growth.candidate_decision.v1",
            "decision_id": decision["decision_id"],
            "decision_digest": decision["decision_digest"],
            "decision_revision": decision["decision_revision"],
            "decision": decision["decision"],
            "winner_candidate_id": decision["winner_candidate_id"],
            "published_candidate_id": matches[0]["candidate_id"],
            "published_candidate_was_winner": (
                decision["winner_candidate_id"] == matches[0]["candidate_id"]
            ),
            "reedit_guidance": [],
            "human_preference_inferred": False,
        },
        "unavailable_evidence": {
            "live_platform_metrics": (
                "synthetic fixture metrics are not live platform evidence"
            )
        },
        "evidence_state": "directional_observational",
        "evidence_blockers": [],
        "causality": {
            "historical_performance_may_prioritize_hypotheses": True,
            "historical_performance_proves_causality": False,
            "retroactive_human_preference_inference": False,
            "hypotheses_are_speculative": True,
        },
        "authority": {
            "advisory_only": True,
            "provider_mutation": False,
            "publish_authorized": False,
            "creator_mutation": False,
            "media_mutation": False,
            "release_authorized": False,
        },
        "interpretation": (
            "R24 uses synthetic metrics only. Learning is a bounded set of "
            "testable hypotheses, never live evidence or a causal conclusion."
        ),
    }
    learning["learning_id"] = "gppl1:" + _sha({
        "publish_result_digest": publish["publish_result_digest"],
        "metric_snapshot_digest": snapshot["snapshot_digest"],
        "learning_revision": 1,
        "next_cycle_id": learning["next_cycle_id"],
    })
    digest_material = dict(learning)
    digest_material["learning_digest"] = ""
    learning["learning_digest"] = _sha(digest_material)
    validate_growth_r19_learning(learning)

    seed = {
        "contract_version": "growth.post_publish_brief_seed.v1",
        "seed_id": "",
        "seed_digest": "",
        "next_cycle_id": learning["next_cycle_id"],
        "source_class": "synthetic_fixture",
        "creator_cycle_eligible": False,
        "learning_ref": {
            "learning_id": learning["learning_id"],
            "learning_digest": learning["learning_digest"],
            "learning_revision": 1,
            "publish_result_digest": publish["publish_result_digest"],
            "media_render_sha256": render_sha,
            "metric_snapshot_digest": snapshot["snapshot_digest"],
        },
        "brief_guidance": [{
            "hypothesis_id": item["hypothesis_id"],
            "testable_change": item["testable_change"],
            "target_metric": item["target_metric"],
            "expected_direction": item["expected_direction"],
            "certainty": item["certainty"],
            "hold_constant": (
                "All creative dimensions not explicitly named by the hypothesis."
            ),
        } for item in hypotheses],
        "unavailable_evidence": learning["unavailable_evidence"],
        "authority": {
            "advisory_only": True,
            "auto_publish": False,
            "external_mutation": False,
            "release_authorized": False,
        },
        "interpretation": (
            "Synthetic next-cycle guidance is testable hypothesis input only; "
            "it is not Creator-cycle eligible and does not authorize mutation."
        ),
    }
    seed["seed_id"] = "gppbs1:" + _sha({
        "next_cycle_id": seed["next_cycle_id"],
        "learning_digest": learning["learning_digest"],
    })
    seed_material = dict(seed)
    seed_material["seed_digest"] = ""
    seed["seed_digest"] = _sha(seed_material)
    validate_brief_seed(seed)
    return _clone(learning), _clone(seed)


def validate_growth_r19_learning(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "contract_version", "learning_id", "learning_digest",
        "learning_revision", "source_class",
        "live_performance_claim_allowed", "next_cycle_id", "lineage",
        "observed_provider_metrics", "derived_analytics",
        "speculative_hypotheses", "runtime_state", "candidate_decision",
        "unavailable_evidence", "evidence_state", "evidence_blockers",
        "causality", "authority", "interpretation",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise LifecycleError("Growth R19 learning schema drift")
    if (
        value["contract_version"] != PINS["growthR19"]["contract"]
        or value["source_class"] != "synthetic_fixture"
        or value["live_performance_claim_allowed"] is not False
    ):
        raise LifecycleError("Growth R19 source/contract boundary violated")
    hypotheses = value["speculative_hypotheses"]
    if not 1 <= len(hypotheses) <= 6:
        raise LifecycleError("Growth R19 hypotheses unbounded")
    for item in hypotheses:
        if item.get("causal_claim") is not False:
            raise LifecycleError("Growth R19 hypothesis claimed causality")
        if not item.get("testable_change"):
            raise LifecycleError("Growth R19 hypothesis is not testable")
    if value["authority"] != {
        "advisory_only": True, "provider_mutation": False,
        "publish_authorized": False, "creator_mutation": False,
        "media_mutation": False, "release_authorized": False,
    }:
        raise LifecycleError("Growth R19 authority drift")
    expected_id = "gppl1:" + _sha({
        "publish_result_digest": value["lineage"]["publish_result_digest"],
        "metric_snapshot_digest": value["lineage"]["metric_snapshot_digest"],
        "learning_revision": value["learning_revision"],
        "next_cycle_id": value["next_cycle_id"],
    })
    if value["learning_id"] != expected_id:
        raise LifecycleError("Growth R19 learning identity mismatch")
    material = dict(value)
    provided = material["learning_digest"]
    material["learning_digest"] = ""
    if _sha(material) != provided:
        raise LifecycleError("Growth R19 learning digest mismatch")
    return _clone(value)


def validate_brief_seed(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("contract_version") != "growth.post_publish_brief_seed.v1":
        raise LifecycleError("brief seed contract mismatch")
    if (
        value.get("source_class") != "synthetic_fixture"
        or value.get("creator_cycle_eligible") is not False
    ):
        raise LifecycleError("synthetic seed became Creator-cycle eligible")
    if not value.get("brief_guidance"):
        raise LifecycleError("brief seed has no hypotheses")
    material = dict(value)
    provided = material["seed_digest"]
    material["seed_digest"] = ""
    if _sha(material) != provided:
        raise LifecycleError("brief seed digest mismatch")
    return _clone(value)


def _semantic_context(source_path: Path, brief: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    analysis, style, directives = r22.synthetic_semantic_context()
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    analysis = _clone(analysis)
    analysis["source"]["sha256"] = source_sha
    analysis["source"]["sourceId"] = "r24-source:" + source_sha[:16]
    analysis["briefDigest"] = _sha({"brief": brief.strip()})
    digest_material = dict(analysis)
    digest_material.pop("analysisDigest")
    analysis["analysisDigest"] = _sha(digest_material)
    style = _clone(style)
    style["analysisDigest"] = analysis["analysisDigest"]
    directives = _clone(directives)
    directives["analysisDigest"] = analysis["analysisDigest"]
    directives["directivesDigest"] = _sha({
        k: v for k, v in directives.items() if k != "directivesDigest"
    })
    return analysis, style, directives


def _make_final_bundle(
    record: Mapping[str, Any], decision: Mapping[str, Any],
    source: Mapping[str, Any], analysis: Mapping[str, Any],
    directives: Mapping[str, Any], ledger: LifecycleLedger,
) -> dict[str, Any]:
    r22_decision = r22.select_round(
        [record, {
            **record,
            "candidateId": "shadow:" + record["candidateId"],
            "render": {
                **record["render"],
                "render_sha256": _sha({"shadow": record["render"]["render_sha256"]}),
            },
            "critic": _clone(record["critic"]),
        }],
        config=r22.LoopConfig(tie_epsilon=0.0),
        round_index=record["plan"]["roundIndex"],
    )
    r22_decision["state"] = "winner"
    r22_decision["winnerCandidateId"] = record["candidateId"]
    r22_decision["reason"] = (
        "Growth R18 pinned decision selected this exact source-bound render"
    )
    r22_decision["evaluations"] = [{
        "candidateId": record["candidateId"],
        "renderSha256": record["render"]["render_sha256"],
        "evaluation": r22.evaluate_critic(
            record["critic"], config=r22.LoopConfig()
        ),
        "pairwisePreferredCandidateId": None,
    }]
    dm = dict(r22_decision)
    dm.pop("decisionDigest", None)
    r22_decision["decisionDigest"] = _sha(dm)
    bundle = {
        "contractVersion": r22.FINAL_BUNDLE_VERSION,
        "state": "final_bundle",
        "winnerCandidateId": record["candidateId"],
        "roundIndex": record["plan"]["roundIndex"],
        "render": record["render"],
        "critic": record["critic"],
        "decision": r22_decision,
        "lineage": {
            "loopId": "r24-loop:" + source["sha256"][:24],
            "sourceId": source["sourceId"],
            "sourceSha256": source["sha256"],
            "briefDigest": analysis["briefDigest"],
            "semanticAnalysisDigest": analysis["analysisDigest"],
            "semanticDirectivesDigest": directives["directivesDigest"],
            "ledgerDigest": ledger.digest,
            "growthCriticPin": {
                **r22.GROWTH_CRITIC_PIN,
                "r18DecisionDigest": decision["decision_digest"],
                "r18ProducerSha": PINS["growthR18"]["sha"],
            },
            "mediaRenderExport": {
                **r22.MEDIA_RENDER_EXPORT_OBSERVED,
                "r15ProducerSha": PINS["mediaR15"]["sha"],
                "r15Contract": "media.render_export.v1",
                "productionPinAvailable": True,
            },
        },
        "humanReviewRequired": False,
        "humanLevelQualityClaimed": False,
    }
    bundle["bundleDigest"] = _sha(bundle)
    return r23.validate_terminal_editor_bundle(
        bundle, allow_synthetic_editor=True
    )


def run_rehearsal(
    *,
    source_path: Path,
    brief: str,
    out_dir: Path,
    scenario: str = "winner",
    inject_violation: str | None = None,
) -> dict[str, Any]:
    pin_evidence = verify_pinned_contracts()
    source_path = Path(source_path).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    asset = r21.probe_media(source_path)
    if asset.width * 16 != asset.height * 9:
        raise InvariantViolation("source fixture must be exact 9:16")
    if not 15 <= asset.duration_seconds <= 60:
        raise InvariantViolation("source fixture duration outside 15-60s")
    analysis, style, directives = _semantic_context(source_path, brief)
    source = {
        "sourceId": analysis["source"]["sourceId"],
        "sha256": asset.sha256,
        "durationMs": int(round(asset.duration_seconds * 1000)),
    }
    ledger = LifecycleLedger(out_dir / "lifecycle-ledger.jsonl")
    ledger.append_once("source", "source_bound", {
        "source": source,
        "briefDigest": analysis["briefDigest"],
        "semanticDigest": analysis["analysisDigest"],
        "directivesDigest": directives["directivesDigest"],
        "pins": PINS,
    })
    media = MediaR15SyntheticAdapter(source_path, out_dir)
    critic = r22.SyntheticGrowthCriticAdapter(
        scenario="insufficient" if scenario == "insufficient_evidence" else "reedit_winner"
    )
    plans = r22.build_initial_plans(
        loop_id="r24-loop:" + asset.sha256[:24],
        semantic_analysis=analysis,
        style_decision=style,
        directives=directives,
        count=4,
    )
    final_record = None
    final_decision = None
    reedit_rounds = 0
    for round_index in range(3):
        records = []
        for plan in plans:
            key = "media:" + plan["candidateId"]
            export = media.recover(key)
            if export is None:
                export = media.submit(
                    idempotency_key=key, source=source, plan=plan
                )
            if inject_violation == "render_hash_mismatch" and not records:
                export = _clone(export)
                export["artifact"]["sha256"] = "f" * 64
            actual_render_sha = hashlib.sha256(
                media.files[plan["candidateId"]].read_bytes()
            ).hexdigest()
            export = validate_media_r15_export(
                export, expected_render_sha=actual_render_sha
            )
            r22_render = MediaR15SyntheticAdapter.to_r22(
                export, source=source, plan=plan
            )
            critic_key = "critic:" + plan["candidateId"]
            crit = critic.recover(critic_key)
            if crit is None:
                crit = critic.submit(
                    idempotency_key=critic_key,
                    source=source,
                    render_export=r22_render,
                    semantic_analysis=analysis,
                )
            crit = r22.validate_growth_critic_export(
                crit,
                expected_source_id=source["sourceId"],
                expected_render_sha256=r22_render["render_sha256"],
                allow_synthetic=True,
            )
            record = {
                "candidateId": plan["candidateId"],
                "plan": plan,
                "render": r22_render,
                "mediaR15Export": export,
                "critic": crit,
            }
            records.append(record)
            ledger.append_once(
                "candidate:" + plan["candidateId"],
                "candidate_evaluated",
                {
                    "candidateId": plan["candidateId"],
                    "planDigest": plan["planDigest"],
                    "renderSha256": r22_render["render_sha256"],
                    "mediaR15ExportDigest": _sha(export),
                    "criticDigest": _sha(crit),
                },
            )
        decision = build_growth_r18_decision(
            records, source=source, round_index=round_index,
            scenario=scenario,
        )
        if inject_violation == "decision_source_hash_mismatch":
            decision = _clone(decision)
            decision["source_sha256"] = "e" * 64
            dm = dict(decision)
            dm["decision_digest"] = ""
            decision["decision_digest"] = _sha(dm)
        decision = validate_growth_r18_decision(decision)
        if decision["source_sha256"] != source["sha256"]:
            raise InvariantViolation("Growth R18 decision source mismatch")
        ledger.append_once(
            "decision:" + str(round_index),
            "growth_r18_decision",
            {"decision": decision},
        )
        if scenario == "insufficient_evidence":
            result = _terminal_review(
                ledger, source, decision, "insufficient_evidence"
            )
            _write_report(out_dir, result)
            return result
        if decision["decision"] == "winner":
            final_decision = decision
            final_record = next(
                r for r in records
                if r["candidateId"] == decision["winner_candidate_id"]
            )
            break
        if round_index == 2:
            state = (
                "human_review_required"
                if scenario == "human_review_required"
                else "tie"
            )
            result = _terminal_review(ledger, source, decision, state)
            _write_report(out_dir, result)
            return result
        ranked = sorted(
            records,
            key=lambda r: (
                -float(
                    r22.evaluate_critic(
                        r["critic"], config=r22.LoopConfig()
                    )["score"] or -1.0
                ),
                r["candidateId"],
            ),
        )[:2]
        plans = [
            r22.build_reedit_plan(
                parent_plan=r["plan"], critic=r["critic"],
                round_index=round_index + 1,
            )
            for r in ranked
        ]
        reedit_rounds += 1

    if final_record is None or final_decision is None:
        raise InvariantViolation("winner path produced no final record")
    if reedit_rounds > 2:
        raise InvariantViolation("editor re-edit bound exceeded")
    bundle = _make_final_bundle(
        final_record, final_decision, source, analysis, directives, ledger
    )
    ledger.append_once("editor:final", "editor_final_bundle", {
        "bundleDigest": bundle["bundleDigest"],
        "winnerCandidateId": bundle["winnerCandidateId"],
        "renderSha256": bundle["render"]["render_sha256"],
        "growthR18DecisionDigest": final_decision["decision_digest"],
        "reeditRounds": reedit_rounds,
    })
    winner_path = media.files[final_record["candidateId"]]
    final_path = out_dir / "final.mp4"
    shutil.copyfile(winner_path, final_path)
    final_asset = r23.validate_final_artifact(bundle, final_path)

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
        account_id="r24-synthetic-account",
        destination=destination,
        credential_ref="vault-ref://r24/synthetic",
        authorization_ref="oauth-grant-ref://r24/synthetic",
        caption="R24 synthetic lifecycle",
        cta="Learn more",
        allow_synthetic_editor=True,
    )
    handoff_ledger = r23.HandoffLedger(
        out_dir / "editor-publish-ledger.jsonl",
        handoff,
        allow_synthetic_editor=True,
    )
    provider = r12.TikTokMockProvider(
        credentials_available=(scenario != "provider_auth_required"),
        crash_after_effect_once=(scenario == "winner"),
        polls_before_publish=1,
    )
    publish_coord = r23.EditorPublishCoordinator(
        handoff_ledger=handoff_ledger,
        publish_ledger_path=out_dir / "publish-ledger.jsonl",
        allow_synthetic=True,
    )
    restart_count = 0
    outcome = None
    for index in range(8):
        try:
            outcome = publish_coord.drive(
                provider, now=f"2026-10-01T00:00:0{index}Z"
            )
        except reels.InjectedCrash:
            restart_count += 1
            handoff_ledger = r23.HandoffLedger(
                out_dir / "editor-publish-ledger.jsonl",
                handoff,
                allow_synthetic_editor=True,
            )
            publish_coord = r23.EditorPublishCoordinator(
                handoff_ledger=handoff_ledger,
                publish_ledger_path=out_dir / "publish-ledger.jsonl",
                allow_synthetic=True,
            )
            continue
        if outcome["state"] in {
            "published", "failed_terminal", "waiting_for_credentials"
        }:
            break
    if outcome is None:
        raise InvariantViolation("publish stage produced no outcome")
    if scenario == "provider_auth_required":
        if outcome["state"] != "waiting_for_credentials":
            raise InvariantViolation("auth-required path did not stop")
        result = _report(
            state="provider_auth_required", ledger=ledger,
            source=source, pin_evidence=pin_evidence,
            bundle=bundle, decision=final_decision,
            handoff=handoff, receipt=None, learning=None, seed=None,
            metric_snapshot=None, reedit_rounds=reedit_rounds,
            restart_count=restart_count, provider=provider,
        )
        _write_report(out_dir, result)
        return result
    if outcome["state"] != "published":
        raise InvariantViolation("synthetic provider did not publish")
    receipt = outcome["receipt"]
    if receipt["mediaContentSha256"] != final_asset.sha256:
        raise InvariantViolation("provider receipt render hash mismatch")
    duplicate = publish_coord.drive(
        provider, now="2026-10-01T00:00:09Z"
    )
    if duplicate["receipt"]["receiptDigest"] != receipt["receiptDigest"]:
        raise InvariantViolation("duplicate receipt changed")
    if provider.accepted_effects != 1 or provider.submit_calls != 1:
        raise InvariantViolation("provider exactly-once invariant failed")

    growth_publish = build_growth_publish_result(
        receipt=receipt, handoff=handoff,
        fixture_source_sha=source["sha256"],
    )
    snapshot = build_synthetic_metric_snapshot(growth_publish)
    if inject_violation == "metrics_hash_mismatch":
        snapshot = _clone(snapshot)
        snapshot["publish_result_digest"] = "d" * 64
        sm = dict(snapshot)
        sm.pop("snapshot_digest")
        snapshot["snapshot_digest"] = _sha(sm)
    snapshot = validate_metric_snapshot(snapshot)
    if snapshot["publish_result_digest"] != growth_publish["publish_result_digest"]:
        raise InvariantViolation("metric snapshot publish lineage mismatch")
    if growth_publish["artifact"]["media_artifact_digest"] != final_asset.sha256:
        raise InvariantViolation("Growth publish render lineage mismatch")

    learning, seed = build_growth_r19_learning(
        growth_publish, snapshot, final_decision
    )
    if learning["lineage"]["media_render_sha256"] != final_asset.sha256:
        raise InvariantViolation("Growth R19 render lineage mismatch")
    ledger.append_once("learning:r19", "growth_r19_learning", {
        "learningDigest": learning["learning_digest"],
        "metricSnapshotDigest": snapshot["snapshot_digest"],
        "publishResultDigest": growth_publish["publish_result_digest"],
        "mediaRenderSha256": final_asset.sha256,
    })
    ledger.append_once("seed:r19", "next_cycle_seed", {
        "seedDigest": seed["seed_digest"],
        "learningDigest": learning["learning_digest"],
        "creatorCycleEligible": seed["creator_cycle_eligible"],
    })
    for item in learning["speculative_hypotheses"]:
        if item["causal_claim"] is not False:
            raise InvariantViolation("learning hypothesis became causal")
    result = _report(
        state="completed", ledger=ledger, source=source,
        pin_evidence=pin_evidence, bundle=bundle,
        decision=final_decision, handoff=handoff, receipt=receipt,
        learning=learning, seed=seed, metric_snapshot=snapshot,
        reedit_rounds=reedit_rounds, restart_count=restart_count,
        provider=provider,
    )
    _write_artifacts(
        out_dir, bundle, final_decision, handoff, receipt,
        growth_publish, snapshot, learning, seed,
    )
    _write_report(out_dir, result)
    return result


def _terminal_review(
    ledger: LifecycleLedger, source: Mapping[str, Any],
    decision: Mapping[str, Any], state: str,
) -> dict[str, Any]:
    result = {
        "reportVersion": REPORT_VERSION,
        "contractVersion": LIFECYCLE_VERSION,
        "state": state,
        "source": source,
        "producerPins": PINS,
        "growthR18DecisionDigest": decision["decision_digest"],
        "finalRenderSha256": None,
        "publishReceiptDigest": None,
        "metricSnapshotDigest": None,
        "learningDigest": None,
        "nextCycleSeedDigest": None,
        "reeditRounds": decision["decision_revision"] - 1,
        "livePublishingExecuted": False,
        "liveMetricsUsed": False,
        "humanLevelQualityClaimed": False,
        "ledgerDigest": ledger.digest,
    }
    result["reportDigest"] = _sha(result)
    return result


def _report(
    *, state: str, ledger: LifecycleLedger, source: Mapping[str, Any],
    pin_evidence: Mapping[str, Any], bundle: Mapping[str, Any],
    decision: Mapping[str, Any], handoff: Mapping[str, Any],
    receipt: Mapping[str, Any] | None, learning: Mapping[str, Any] | None,
    seed: Mapping[str, Any] | None,
    metric_snapshot: Mapping[str, Any] | None, reedit_rounds: int,
    restart_count: int, provider: Any,
) -> dict[str, Any]:
    result = {
        "reportVersion": REPORT_VERSION,
        "contractVersion": LIFECYCLE_VERSION,
        "state": state,
        "source": source,
        "producerPins": PINS,
        "pinnedContractEvidence": pin_evidence,
        "editorBundleDigest": bundle["bundleDigest"],
        "growthR18DecisionDigest": decision["decision_digest"],
        "finalRenderSha256": bundle["render"]["render_sha256"],
        "handoffDigest": handoff["handoffDigest"],
        "publishReceiptDigest": (
            None if receipt is None else receipt["receiptDigest"]
        ),
        "metricSnapshotDigest": (
            None if metric_snapshot is None
            else metric_snapshot["snapshot_digest"]
        ),
        "learningDigest": (
            None if learning is None else learning["learning_digest"]
        ),
        "nextCycleSeedDigest": (
            None if seed is None else seed["seed_digest"]
        ),
        "reeditRounds": reedit_rounds,
        "restartCount": restart_count,
        "providerAcceptedEffects": provider.accepted_effects,
        "providerSubmitCalls": provider.submit_calls,
        "livePublishingExecuted": False,
        "liveMetricsUsed": False,
        "credentialsPersisted": False,
        "humanLevelQualityClaimed": False,
        "ledgerDigest": ledger.digest,
    }
    result["reportDigest"] = _sha(result)
    return result


def _write_artifacts(
    out_dir: Path, bundle: Mapping[str, Any],
    decision: Mapping[str, Any], handoff: Mapping[str, Any],
    receipt: Mapping[str, Any], growth_publish: Mapping[str, Any],
    snapshot: Mapping[str, Any], learning: Mapping[str, Any],
    seed: Mapping[str, Any],
) -> None:
    values = {
        "editor-final-bundle.json": bundle,
        "growth-r18-decision.json": decision,
        "editor-publish-handoff.json": handoff,
        "provider-receipt.json": receipt,
        "growth-publish-result.json": growth_publish,
        "synthetic-metric-snapshot.json": snapshot,
        "growth-r19-learning.json": learning,
        "next-cycle-brief-seed.json": seed,
    }
    for name, value in values.items():
        (out_dir / name).write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _write_report(out_dir: Path, report: Mapping[str, Any]) -> None:
    (out_dir / "lifecycle-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="creator-lifecycle-r24",
        description="Run the bounded synthetic Creator R24 full lifecycle.",
    )
    p.add_argument("--source", required=True)
    p.add_argument("--brief", required=True)
    p.add_argument("--out", required=True)
    p.add_argument(
        "--scenario",
        choices=(
            "winner", "tie", "insufficient_evidence",
            "human_review_required", "provider_auth_required",
        ),
        default="winner",
    )
    p.add_argument(
        "--inject-violation",
        choices=("render_hash_mismatch", "decision_source_hash_mismatch", "metrics_hash_mismatch"),
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = run_rehearsal(
            source_path=Path(args.source),
            brief=args.brief,
            out_dir=Path(args.out),
            scenario=args.scenario,
            inject_violation=args.inject_violation,
        )
    except Exception as exc:
        print(json.dumps({
            "reportVersion": REPORT_VERSION,
            "state": "BLOCKED_INVARIANT",
            "reason": type(exc).__name__,
            "detail": str(exc),
            "livePublishingExecuted": False,
            "liveMetricsUsed": False,
        }, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if report["state"] in {
        "completed", "tie", "insufficient_evidence",
        "human_review_required", "provider_auth_required",
    } else 3


if __name__ == "__main__":
    raise SystemExit(main())
