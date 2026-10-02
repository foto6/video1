from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import autonomous_editor_loop as r22
from . import autonomous_reels as reels
from . import publish_execution as r21
from . import publish_providers as r12

HANDOFF_VERSION = "creator.editor_publish_handoff.v1"
HANDOFF_LEDGER_VERSION = "creator.editor_publish_handoff_ledger.v1"
HANDOFF_REPORT_VERSION = "creator.editor_publish_handoff_report.v1"
CREATOR_R22_BASE_SHA = "351df0d455557fb20b47f0fd2ab806c4281ed5ee"

BLOCKED_EDITOR_STATES = {
    "tie",
    "insufficient_evidence",
    "human_review",
    "human_review_required",
    "objective_render_failure",
}


class EditorPublishHandoffError(ValueError):
    pass


class EditorOutcomeIneligible(EditorPublishHandoffError):
    pass


class ArtifactLineageMismatch(EditorPublishHandoffError):
    pass


class HandoffConflict(EditorPublishHandoffError):
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
        raise EditorPublishHandoffError(
            f"{field} must be lowercase sha256 hex"
        )
    return value


def _nonempty(value: Any, field: str) -> str:
    return reels._nonempty(value, field)


def _validate_digest(
    value: Mapping[str, Any],
    digest_field: str,
    field: str,
) -> None:
    digest = _hex64(value[digest_field], f"{field}.{digest_field}")
    material = dict(value)
    material.pop(digest_field)
    if _sha(material) != digest:
        raise EditorPublishHandoffError(f"{field} digest mismatch")


def validate_terminal_editor_bundle(
    bundle: Mapping[str, Any],
    *,
    allow_synthetic_editor: bool,
    growth_critic_validator: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(bundle, Mapping):
        raise EditorOutcomeIneligible("editor outcome must be an object")
    decision = (
        bundle.get("decision")
        if isinstance(bundle.get("decision"), Mapping)
        else {}
    )
    state = bundle.get("state")
    decision_state = decision.get("state") or bundle.get("decisionState")
    if (
        bundle.get("contractVersion") == r22.HUMAN_REVIEW_VERSION
        or state in BLOCKED_EDITOR_STATES
        or decision_state in BLOCKED_EDITOR_STATES
        or bundle.get("humanReviewRequired") is True
    ):
        raise EditorOutcomeIneligible(
            "editor outcome is non-terminal-eligible for publication"
        )
    required = {
        "contractVersion",
        "state",
        "winnerCandidateId",
        "roundIndex",
        "render",
        "critic",
        "decision",
        "lineage",
        "humanReviewRequired",
        "humanLevelQualityClaimed",
        "bundleDigest",
    }
    if set(bundle) != required:
        raise EditorPublishHandoffError(
            "R22 final bundle fields must match exactly"
        )
    if bundle["contractVersion"] != r22.FINAL_BUNDLE_VERSION:
        raise EditorOutcomeIneligible(
            "only creator.autonomous_edit_final_bundle.r22.v1 may proceed"
        )
    if bundle["state"] != "final_bundle":
        raise EditorOutcomeIneligible("editor state must be final_bundle")
    if bundle["humanReviewRequired"] is not False:
        raise EditorOutcomeIneligible("human-review outcome cannot publish")
    if bundle["humanLevelQualityClaimed"] is not False:
        raise EditorPublishHandoffError(
            "R23 does not accept HUMAN_LEVEL claims"
        )
    _validate_digest(bundle, "bundleDigest", "editor bundle")
    if decision.get("contractVersion") != r22.DECISION_VERSION:
        raise EditorPublishHandoffError("editor decision contract mismatch")
    if decision.get("state") != "winner":
        raise EditorOutcomeIneligible(
            "tie or insufficient evidence cannot publish"
        )
    if decision.get("winnerCandidateId") != bundle["winnerCandidateId"]:
        raise EditorPublishHandoffError(
            "editor winner candidate binding mismatch"
        )
    _validate_digest(decision, "decisionDigest", "editor decision")

    lineage = bundle["lineage"]
    expected_lineage = {
        "loopId",
        "sourceId",
        "sourceSha256",
        "briefDigest",
        "semanticAnalysisDigest",
        "semanticDirectivesDigest",
        "ledgerDigest",
        "growthCriticPin",
        "mediaRenderExport",
    }
    if not isinstance(lineage, Mapping) or set(lineage) != expected_lineage:
        raise EditorPublishHandoffError("editor lineage fields mismatch")
    _nonempty(lineage["loopId"], "editor.lineage.loopId")
    _nonempty(lineage["sourceId"], "editor.lineage.sourceId")
    for key in (
        "sourceSha256",
        "briefDigest",
        "semanticAnalysisDigest",
        "semanticDirectivesDigest",
        "ledgerDigest",
    ):
        _hex64(lineage[key], f"editor.lineage.{key}")

    render = bundle["render"]
    r22.validate_media_render_export(
        render,
        expected_source_id=lineage["sourceId"],
        expected_source_sha256=lineage["sourceSha256"],
        expected_candidate_id=bundle["winnerCandidateId"],
        expected_plan_digest=render["plan_digest"],
        allow_synthetic=allow_synthetic_editor,
    )
    if render["technical_qa"]["passed"] is not True:
        raise EditorOutcomeIneligible(
            "objective_render_failure: technical QA failed"
        )
    critic = bundle["critic"]
    if growth_critic_validator is None:
        r22.validate_growth_critic_export(
            critic,
            expected_source_id=lineage["sourceId"],
            expected_render_sha256=render["render_sha256"],
            allow_synthetic=allow_synthetic_editor,
        )
    else:
        growth_critic_validator(
            critic,
            expected_source_id=lineage["sourceId"],
            expected_render_sha256=render["render_sha256"],
        )
    if critic["hard_failure_observations"]:
        raise EditorOutcomeIneligible(
            "objective_render_failure: critic hard failure"
        )
    return _clone(bundle)


def validate_final_artifact(
    bundle: Mapping[str, Any],
    media_path: Path,
) -> r21.MediaAsset:
    asset = r21.probe_media(media_path)
    expected_sha = bundle["render"]["render_sha256"]
    if asset.sha256 != expected_sha:
        raise ArtifactLineageMismatch(
            "final.mp4 SHA does not match terminal editor render SHA"
        )
    if asset.width * 16 != asset.height * 9:
        raise ArtifactLineageMismatch("final artifact is not exact 9:16")
    if not 15 <= asset.duration_seconds <= 60:
        raise ArtifactLineageMismatch(
            "final artifact duration is outside Creator short-form profile"
        )
    return asset


def build_editor_publish_handoff(
    *,
    editor_bundle: Mapping[str, Any],
    media_asset: r21.MediaAsset,
    release_authorization: Mapping[str, Any],
    platform: str,
    account_id: str,
    destination: str,
    credential_ref: str,
    authorization_ref: str,
    caption: str,
    cta: str,
    allow_synthetic_editor: bool,
    growth_critic_validator: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    bundle = validate_terminal_editor_bundle(
        editor_bundle,
        allow_synthetic_editor=allow_synthetic_editor,
        growth_critic_validator=growth_critic_validator,
    )
    if media_asset.sha256 != bundle["render"]["render_sha256"]:
        raise ArtifactLineageMismatch(
            "final artifact SHA does not match editor winner render"
        )
    winner = bundle["winnerCandidateId"]
    artifact_id = "sha256:" + media_asset.sha256
    auth = _clone(release_authorization)
    if auth.get("candidateId") != winner:
        raise reels.PublishGateError(
            "release authorization candidate binding mismatch"
        )
    if auth.get("lineageHash") != "sha256:" + bundle["bundleDigest"]:
        raise reels.PublishGateError(
            "release authorization editor lineage binding mismatch"
        )

    source_class = bundle["render"]["source_class"]
    media_source_class = (
        "synthetic_fixture"
        if source_class == "synthetic_fixture"
        else "provider"
    )
    media = {
        "sourceClass": media_source_class,
        "contentId": artifact_id,
        "contentSha256": media_asset.sha256,
        "sizeBytes": media_asset.size_bytes,
        "contentType": "video/mp4",
        "durationSeconds": round(media_asset.duration_seconds, 6),
        "aspectRatio": "9:16",
        "manifestDigest": bundle["render"]["artifact_manifest_digest"],
    }
    request = r12.build_publish_request(
        platform=platform,
        account_id=account_id,
        destination=destination,
        credential_ref=credential_ref,
        authorization_lineage={
            "credentialRef": credential_ref,
            "authorizationRef": authorization_ref,
        },
        media=media,
        caption=caption,
        cta=cta,
        release_authorization=auth,
        allow_synthetic_fixture=allow_synthetic_editor,
    )
    target = {
        "platform": platform,
        "accountId": account_id,
        "destination": destination,
        "credentialRef": credential_ref,
        "authorizationRef": authorization_ref,
    }
    handoff = {
        "contractVersion": HANDOFF_VERSION,
        "handoffId": "",
        "source": {
            "sourceId": bundle["lineage"]["sourceId"],
            "sourceSha256": bundle["lineage"]["sourceSha256"],
            "loopId": bundle["lineage"]["loopId"],
            "semanticAnalysisDigest": bundle["lineage"][
                "semanticAnalysisDigest"
            ],
            "semanticDirectivesDigest": bundle["lineage"][
                "semanticDirectivesDigest"
            ],
        },
        "editor": {
            "bundleDigest": bundle["bundleDigest"],
            "decisionDigest": bundle["decision"]["decisionDigest"],
            "winnerCandidateId": winner,
            "roundIndex": bundle["roundIndex"],
            "renderSha256": bundle["render"]["render_sha256"],
            "timelineDigest": bundle["render"]["timeline_digest"],
            "artifactManifestDigest": bundle["render"][
                "artifact_manifest_digest"
            ],
            "technicalQaDigest": bundle["render"]["technical_qa"][
                "qa_digest"
            ],
        },
        "finalArtifact": {
            "fileName": media_asset.path.name,
            "sha256": media_asset.sha256,
            "sizeBytes": media_asset.size_bytes,
            "durationSeconds": round(media_asset.duration_seconds, 6),
            "contentType": "video/mp4",
            "aspectRatio": "9:16",
        },
        "releaseAuthorization": auth,
        "target": target,
        "publishRequest": request,
        "livePublishingExecuted": False,
        "handoffDigest": "",
    }
    identity = {
        key: value
        for key, value in handoff.items()
        if key not in {"handoffId", "handoffDigest"}
    }
    handoff["handoffId"] = "eph1:" + _sha(identity)
    digest_material = dict(handoff)
    digest_material.pop("handoffDigest")
    handoff["handoffDigest"] = _sha(digest_material)
    return validate_editor_publish_handoff(
        handoff,
        allow_synthetic_editor=allow_synthetic_editor,
    )


def validate_editor_publish_handoff(
    handoff: Mapping[str, Any],
    *,
    allow_synthetic_editor: bool,
) -> dict[str, Any]:
    required = {
        "contractVersion",
        "handoffId",
        "source",
        "editor",
        "finalArtifact",
        "releaseAuthorization",
        "target",
        "publishRequest",
        "livePublishingExecuted",
        "handoffDigest",
    }
    if not isinstance(handoff, Mapping) or set(handoff) != required:
        raise EditorPublishHandoffError(
            "editor publish handoff fields must match exactly"
        )
    if handoff["contractVersion"] != HANDOFF_VERSION:
        raise EditorPublishHandoffError("handoff contract mismatch")
    if handoff["livePublishingExecuted"] is not False:
        raise EditorPublishHandoffError(
            "R23 handoff cannot claim live publishing"
        )
    _nonempty(handoff["handoffId"], "handoffId")
    _hex64(handoff["handoffDigest"], "handoffDigest")
    digest_material = dict(handoff)
    digest = digest_material.pop("handoffDigest")
    if _sha(digest_material) != digest:
        raise EditorPublishHandoffError("handoff digest mismatch")
    identity = {
        key: value
        for key, value in handoff.items()
        if key not in {"handoffId", "handoffDigest"}
    }
    if handoff["handoffId"] != "eph1:" + _sha(identity):
        raise EditorPublishHandoffError("handoff identity mismatch")

    source = handoff["source"]
    if set(source) != {
        "sourceId",
        "sourceSha256",
        "loopId",
        "semanticAnalysisDigest",
        "semanticDirectivesDigest",
    }:
        raise EditorPublishHandoffError("handoff source fields mismatch")
    _nonempty(source["sourceId"], "source.sourceId")
    _nonempty(source["loopId"], "source.loopId")
    for key in (
        "sourceSha256",
        "semanticAnalysisDigest",
        "semanticDirectivesDigest",
    ):
        _hex64(source[key], f"source.{key}")

    editor = handoff["editor"]
    if set(editor) != {
        "bundleDigest",
        "decisionDigest",
        "winnerCandidateId",
        "roundIndex",
        "renderSha256",
        "timelineDigest",
        "artifactManifestDigest",
        "technicalQaDigest",
    }:
        raise EditorPublishHandoffError("handoff editor fields mismatch")
    _nonempty(editor["winnerCandidateId"], "editor.winnerCandidateId")
    if (
        isinstance(editor["roundIndex"], bool)
        or not isinstance(editor["roundIndex"], int)
        or not 0 <= editor["roundIndex"] <= 2
    ):
        raise EditorPublishHandoffError("editor roundIndex invalid")
    for key in (
        "bundleDigest",
        "decisionDigest",
        "renderSha256",
        "timelineDigest",
        "artifactManifestDigest",
        "technicalQaDigest",
    ):
        _hex64(editor[key], f"editor.{key}")

    artifact = handoff["finalArtifact"]
    if set(artifact) != {
        "fileName",
        "sha256",
        "sizeBytes",
        "durationSeconds",
        "contentType",
        "aspectRatio",
    }:
        raise EditorPublishHandoffError("finalArtifact fields mismatch")
    if artifact["fileName"] != "final.mp4":
        raise EditorPublishHandoffError(
            "canonical publish artifact must be final.mp4"
        )
    if artifact["contentType"] != "video/mp4":
        raise EditorPublishHandoffError("finalArtifact must be video/mp4")
    if artifact["aspectRatio"] != "9:16":
        raise EditorPublishHandoffError("finalArtifact must be 9:16")
    _hex64(artifact["sha256"], "finalArtifact.sha256")
    if artifact["sha256"] != editor["renderSha256"]:
        raise ArtifactLineageMismatch(
            "finalArtifact SHA differs from editor render"
        )

    target = handoff["target"]
    if set(target) != {
        "platform",
        "accountId",
        "destination",
        "credentialRef",
        "authorizationRef",
    }:
        raise EditorPublishHandoffError("target fields mismatch")
    for key in target:
        _nonempty(target[key], f"target.{key}")
    request = r12.validate_publish_request(
        handoff["publishRequest"],
        allow_synthetic_fixture=allow_synthetic_editor,
    )
    for target_key, request_key in (
        ("platform", "platform"),
        ("accountId", "accountId"),
        ("destination", "destination"),
        ("credentialRef", "credentialRef"),
    ):
        if target[target_key] != request[request_key]:
            raise EditorPublishHandoffError(
                f"target {target_key} does not match publish request"
            )
    if (
        target["authorizationRef"]
        != request["authorizationLineage"]["authorizationRef"]
    ):
        raise EditorPublishHandoffError(
            "target authorizationRef does not match publish request"
        )
    if request["media"]["contentSha256"] != artifact["sha256"]:
        raise ArtifactLineageMismatch(
            "publish request media SHA differs from final artifact"
        )
    if (
        request["media"]["manifestDigest"]
        != editor["artifactManifestDigest"]
    ):
        raise ArtifactLineageMismatch(
            "publish request manifest differs from editor render"
        )
    auth = handoff["releaseAuthorization"]
    if auth != request["releaseAuthorization"]:
        raise EditorPublishHandoffError(
            "handoff release authorization differs from publish request"
        )
    if auth["candidateId"] != editor["winnerCandidateId"]:
        raise reels.PublishGateError(
            "release authorization candidate differs from editor winner"
        )
    if auth["lineageHash"] != "sha256:" + editor["bundleDigest"]:
        raise reels.PublishGateError(
            "release authorization lineage differs from editor bundle"
        )
    reels._reject_secrets(handoff)
    return _clone(handoff)


class HandoffLedger:
    def __init__(
        self,
        path: str | os.PathLike[str],
        handoff: Mapping[str, Any],
        *,
        allow_synthetic_editor: bool,
    ) -> None:
        self.path = Path(path)
        self.handoff = validate_editor_publish_handoff(
            handoff,
            allow_synthetic_editor=allow_synthetic_editor,
        )
        self.events: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            self._load()
            if self.events[0]["eventType"] != "handoff_created":
                raise HandoffConflict("handoff ledger missing creation event")
            if self.events[0]["payload"] != self.handoff:
                raise HandoffConflict("durable handoff identity mismatch")
        else:
            self.append_once(
                "handoff:create",
                "handoff_created",
                self.handoff,
            )

    def _load(self) -> None:
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise HandoffConflict(
                    f"invalid handoff ledger line {line_number}"
                ) from exc
            if set(event) != {
                "ledgerVersion",
                "sequence",
                "eventKey",
                "eventType",
                "payload",
                "eventDigest",
            }:
                raise HandoffConflict("handoff ledger fields mismatch")
            if event["ledgerVersion"] != HANDOFF_LEDGER_VERSION:
                raise HandoffConflict("handoff ledger version mismatch")
            if event["sequence"] != len(self.events) + 1:
                raise HandoffConflict("handoff ledger sequence mismatch")
            material = dict(event)
            digest = material.pop("eventDigest")
            if _sha(material) != digest:
                raise HandoffConflict("handoff ledger digest mismatch")
            reels._reject_secrets(event["payload"])
            if event["eventKey"] in self.by_key:
                raise HandoffConflict("duplicate durable event key")
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
                raise HandoffConflict(
                    f"conflicting durable replay for {event_key}"
                )
            return "duplicate"
        event = {
            "ledgerVersion": HANDOFF_LEDGER_VERSION,
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

    def has_publish_intent(self) -> bool:
        return "publish:intent" in self.by_key

    @property
    def digest(self) -> str:
        return _sha(self.events)


class EditorPublishCoordinator:
    def __init__(
        self,
        *,
        handoff_ledger: HandoffLedger,
        publish_ledger_path: str | os.PathLike[str],
        allow_synthetic: bool,
    ) -> None:
        self.handoff_ledger = handoff_ledger
        self.publish_ledger_path = Path(publish_ledger_path)
        self.allow_synthetic = allow_synthetic

    def drive(
        self,
        provider: r12.PublishProvider,
        *,
        now: str,
    ) -> dict[str, Any]:
        request = self.handoff_ledger.handoff["publishRequest"]
        self.handoff_ledger.append_once(
            "publish:intent",
            "publish_intent_committed",
            {
                "handoffId": self.handoff_ledger.handoff["handoffId"],
                "handoffDigest": self.handoff_ledger.handoff[
                    "handoffDigest"
                ],
                "publishId": request["publishId"],
                "idempotencyKey": request["idempotencyKey"],
                "requestDigest": _sha(request),
            },
        )
        coordinator = r12.DurablePublishCoordinator(
            self.publish_ledger_path,
            request,
            allow_synthetic_fixture=self.allow_synthetic,
        )
        outcome = coordinator.drive(provider, now=now)
        snapshot = coordinator.snapshot()
        self.handoff_ledger.append_once(
            "publish:snapshot:" + snapshot["ledgerDigest"],
            "publish_snapshot",
            snapshot,
        )
        if outcome["state"] == "published":
            receipt = r12.validate_provider_receipt(
                outcome["receipt"],
                request,
                allow_synthetic_fixture=self.allow_synthetic,
            )
            self.handoff_ledger.append_once(
                "publish:receipt",
                "provider_receipt_committed",
                receipt,
            )
            growth = r12.build_growth_handoff(
                receipt,
                request,
                allow_synthetic_fixture=self.allow_synthetic,
            )
            self.handoff_ledger.append_once(
                "growth:handoff",
                "growth_handoff_committed",
                growth,
            )
            return {
                "state": "published",
                "receipt": receipt,
                "growthHandoff": growth,
                "publishSnapshot": snapshot,
            }
        return {
            "state": outcome["state"],
            "receipt": None,
            "growthHandoff": None,
            "publishSnapshot": snapshot,
        }


def _synthetic_dimension(score: float) -> dict[str, Any]:
    return {
        "source_dimension": "fixture",
        "rule_observation": {
            "available": True,
            "confidence": 0.9,
            "evidence": ["r23 synthetic conformance"],
            "human_ground_truth": False,
            "limitation": "synthetic fixture only",
            "normalized_score": score,
        },
        "vlm_observations": [],
        "unavailable": None,
    }


def synthetic_editor_bundle_for_asset(
    asset: r21.MediaAsset,
) -> dict[str, Any]:
    source_sha = "a" * 64
    candidate_id = "candidate22r:" + ("b" * 64)
    plan_digest = "c" * 64
    qa_material = {
        "passed": True,
        "checks": [
            {"name": "mp4", "pass": True},
            {"name": "aspect_9_16", "pass": True},
            {"name": "duration", "pass": True},
        ],
    }
    qa = {**qa_material, "qa_digest": _sha(qa_material)}
    render = {
        "contract_version": r22.MEDIA_RENDER_EXPORT_VERSION,
        "repository": "foto6/video2",
        "commit_sha": "0" * 40,
        "source_class": "synthetic_fixture",
        "source_id": "r23-synthetic-source",
        "source_sha256": source_sha,
        "candidate_id": candidate_id,
        "round_index": 2,
        "plan_digest": plan_digest,
        "render_sha256": asset.sha256,
        "timeline_digest": _sha(
            {"asset": asset.sha256, "kind": "timeline"}
        ),
        "artifact_manifest_digest": _sha(
            {"asset": asset.sha256, "kind": "manifest"}
        ),
        "technical_qa": qa,
        "render_provenance": {
            "adapter": "r23_synthetic_final_mp4",
            "ordinal": 0,
            "roundIndex": 2,
            "humanLevelQuality": "HUMAN_LEVEL_UNPROVEN",
        },
        "human_ground_truth": False,
    }
    dimensions = {
        name: {
            **_synthetic_dimension(0.85),
            "source_dimension": name,
        }
        for name in r22.CRITIC_DIMENSIONS
    }
    critic = {
        "contract_version": r22.GROWTH_CRITIC_EXPORT_VERSION,
        "repository": r22.GROWTH_CRITIC_PIN["repository"],
        "commit_sha": "0" * 40,
        "source_id": render["source_id"],
        "render_sha256": asset.sha256,
        "critic_mode": "structural_rule",
        "model_or_rule_identity": {
            "kind": "synthetic_fixture",
            "mode": "r23_handoff_conformance",
            "humanLevelQuality": "HUMAN_LEVEL_UNPROVEN",
        },
        "dimension_observations": dimensions,
        "timecoded_evidence": [],
        "hard_failure_observations": [],
        "pairwise_if_used": None,
        "human_ground_truth": False,
    }
    decision = {
        "contractVersion": r22.DECISION_VERSION,
        "roundIndex": 2,
        "state": "winner",
        "winnerCandidateId": candidate_id,
        "reason": "synthetic R23 handoff conformance winner",
        "evaluations": [
            {
                "candidateId": candidate_id,
                "renderSha256": asset.sha256,
                "evaluation": {
                    "eligible": True,
                    "state": "eligible",
                    "score": 0.85,
                    "confidence": 0.9,
                    "availableDimensions": 10,
                    "reason": "synthetic conformance evidence",
                },
                "pairwisePreferredCandidateId": None,
            }
        ],
        "humanLevelQualityClaimed": False,
        "aestheticSuperiorityClaimed": False,
    }
    decision["decisionDigest"] = _sha(decision)
    bundle = {
        "contractVersion": r22.FINAL_BUNDLE_VERSION,
        "state": "final_bundle",
        "winnerCandidateId": candidate_id,
        "roundIndex": 2,
        "render": render,
        "critic": critic,
        "decision": decision,
        "lineage": {
            "loopId": "r23-synthetic-loop",
            "sourceId": render["source_id"],
            "sourceSha256": source_sha,
            "briefDigest": "d" * 64,
            "semanticAnalysisDigest": "e" * 64,
            "semanticDirectivesDigest": "f" * 64,
            "ledgerDigest": "1" * 64,
            "growthCriticPin": r22.GROWTH_CRITIC_PIN,
            "mediaRenderExport": r22.MEDIA_RENDER_EXPORT_OBSERVED,
        },
        "humanReviewRequired": False,
        "humanLevelQualityClaimed": False,
    }
    bundle["bundleDigest"] = _sha(bundle)
    return validate_terminal_editor_bundle(
        bundle,
        allow_synthetic_editor=True,
    )


def synthetic_release_authorization(
    *,
    bundle: Mapping[str, Any],
    platform: str,
    destination: str,
) -> dict[str, Any]:
    sha = bundle["render"]["render_sha256"]
    return {
        "contractVersion": reels.RELEASE_AUTHORIZATION_VERSION,
        "decisionId": "r23-release-decision",
        "idempotencyKey": "r23-release-key",
        "requestId": "r23-release-request",
        "campaignId": "r23-synthetic-campaign",
        "candidateId": bundle["winnerCandidateId"],
        "artifactId": "sha256:" + sha,
        "artifactHash": "sha256:" + sha,
        "lineageHash": "sha256:" + bundle["bundleDigest"],
        "destinationScope": {
            "provider": platform,
            "destination": destination,
            "action": "release",
        },
        "decision": "approved",
        "authorizationId": "r23-synthetic-authorization",
        "expiresAt": "2026-10-02T00:00:00Z",
        "decidedAt": "2026-10-01T00:00:00Z",
        "decisionSource": "external",
        "approverRef": "r23-synthetic-human-fixture",
    }


def run_synthetic_handoff(
    *,
    media_path: Path,
    editor_bundle_path: Path,
    authorization_path: Path,
    platform: str,
    account_id: str,
    destination: str,
    credential_ref: str,
    authorization_ref: str,
    caption: str,
    cta: str,
    out_dir: Path,
    provider: r12.PublishProvider | None = None,
) -> dict[str, Any]:
    bundle = json.loads(editor_bundle_path.read_text(encoding="utf-8"))
    bundle = validate_terminal_editor_bundle(
        bundle,
        allow_synthetic_editor=True,
    )
    asset = validate_final_artifact(bundle, media_path)
    authorization = json.loads(
        authorization_path.read_text(encoding="utf-8")
    )
    handoff = build_editor_publish_handoff(
        editor_bundle=bundle,
        media_asset=asset,
        release_authorization=authorization,
        platform=platform,
        account_id=account_id,
        destination=destination,
        credential_ref=credential_ref,
        authorization_ref=authorization_ref,
        caption=caption,
        cta=cta,
        allow_synthetic_editor=True,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "editor-publish-handoff.json").write_text(
        json.dumps(handoff, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    ledger = HandoffLedger(
        out_dir / "editor-publish-ledger.jsonl",
        handoff,
        allow_synthetic_editor=True,
    )
    runtime = provider
    if runtime is None:
        provider_cls = {
            "instagram_reels": r12.InstagramReelsMockProvider,
            "tiktok": r12.TikTokMockProvider,
            "youtube_shorts": r12.YouTubeShortsMockProvider,
        }[platform]
        runtime = provider_cls(polls_before_publish=1)
    coordinator = EditorPublishCoordinator(
        handoff_ledger=ledger,
        publish_ledger_path=out_dir / "publish-ledger.jsonl",
        allow_synthetic=True,
    )
    outcome: dict[str, Any] = {
        "state": "recoverable_unknown",
        "receipt": None,
        "growthHandoff": None,
    }
    for index in range(8):
        outcome = coordinator.drive(
            runtime,
            now=f"2026-10-01T00:00:0{min(index, 9)}Z",
        )
        if outcome["state"] in {
            "published",
            "failed_terminal",
            "waiting_for_credentials",
        }:
            break
    report = {
        "reportVersion": HANDOFF_REPORT_VERSION,
        "handoffContractVersion": HANDOFF_VERSION,
        "state": outcome["state"],
        "sourceId": handoff["source"]["sourceId"],
        "sourceSha256": handoff["source"]["sourceSha256"],
        "winnerCandidateId": handoff["editor"]["winnerCandidateId"],
        "finalRenderSha256": handoff["editor"]["renderSha256"],
        "editorBundleDigest": handoff["editor"]["bundleDigest"],
        "editorDecisionDigest": handoff["editor"]["decisionDigest"],
        "releaseAuthorizationDigest": _sha(
            handoff["releaseAuthorization"]
        ),
        "publishRequestDigest": _sha(handoff["publishRequest"]),
        "handoffDigest": handoff["handoffDigest"],
        "handoffLedgerDigest": ledger.digest,
        "providerAcceptedEffects": getattr(
            runtime, "accepted_effects", None
        ),
        "providerSubmitCalls": getattr(runtime, "submit_calls", None),
        "receiptDigest": (
            None
            if outcome["receipt"] is None
            else outcome["receipt"]["receiptDigest"]
        ),
        "growthHandoffDigest": (
            None
            if outcome["growthHandoff"] is None
            else outcome["growthHandoff"]["handoffDigest"]
        ),
        "growthLivePerformanceClaimEligible": (
            None
            if outcome["growthHandoff"] is None
            else outcome["growthHandoff"][
                "livePerformanceClaimEligible"
            ]
        ),
        "livePublishingExecuted": False,
        "credentialsPersisted": False,
    }
    report["reportDigest"] = _sha(report)
    (out_dir / "handoff-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if outcome["receipt"] is not None:
        (out_dir / "provider-receipt.json").write_text(
            json.dumps(outcome["receipt"], indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    if outcome["growthHandoff"] is not None:
        (out_dir / "growth-handoff.json").write_text(
            json.dumps(
                outcome["growthHandoff"], indent=2, sort_keys=True
            )
            + "\n",
            encoding="utf-8",
        )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="creator-editor-publish-r23",
        description=(
            "Run R23 editor-to-publish handoff with synthetic providers only."
        ),
    )
    parser.add_argument("--media", required=True)
    parser.add_argument("--editor-bundle", required=True)
    parser.add_argument("--authorization", required=True)
    parser.add_argument(
        "--platform",
        required=True,
        choices=tuple(sorted(r12.PLATFORMS)),
    )
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--credential-ref", required=True)
    parser.add_argument("--authorization-ref", required=True)
    parser.add_argument("--caption", required=True)
    parser.add_argument("--cta", default="Learn more")
    parser.add_argument("--out", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = run_synthetic_handoff(
            media_path=Path(args.media),
            editor_bundle_path=Path(args.editor_bundle),
            authorization_path=Path(args.authorization),
            platform=args.platform,
            account_id=args.account_id,
            destination=args.destination,
            credential_ref=args.credential_ref,
            authorization_ref=args.authorization_ref,
            caption=args.caption,
            cta=args.cta,
            out_dir=Path(args.out),
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "reportVersion": HANDOFF_REPORT_VERSION,
                    "state": "BLOCKED",
                    "reason": type(exc).__name__,
                    "livePublishingExecuted": False,
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if report["state"] == "published" else 3


if __name__ == "__main__":
    raise SystemExit(main())
