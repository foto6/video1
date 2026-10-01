from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator import mvp
from creator_orchestrator import semantic_director as sd


FIXTURE_DIR = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "semantic_director_r18"
)


def fixture_adapters(value):
    return sd.SemanticAdapters(
        asr=sd.FixtureAdapter(
            "fixture_asr",
            tuple(value["asr"]),
            ("transcriptSegments", "sentenceBoundaries"),
        ),
        shot=sd.FixtureAdapter(
            "fixture_shot_detector",
            tuple(value["shot"]),
            ("shotBoundaries", "motionEnergy"),
        ),
        cv=sd.FixtureAdapter(
            "fixture_cv_tracking",
            tuple(value["cv"]),
            ("visualSubjects", "importantObjects"),
        ),
        vlm=sd.FixtureAdapter(
            "fixture_vlm",
            tuple(value["vlm"]),
            ("semanticEvents",),
        ),
    )


def unavailable_adapters():
    return sd.SemanticAdapters(
        asr=sd.UnavailableAdapter(
            "asr",
            ("transcriptSegments", "sentenceBoundaries", "speech_energy"),
        ),
        shot=sd.UnavailableAdapter(
            "shot",
            ("shotBoundaries", "motionEnergy"),
        ),
        cv=sd.UnavailableAdapter(
            "cv",
            ("visualSubjects", "importantObjects"),
        ),
        vlm=sd.UnavailableAdapter(
            "vlm",
            ("semanticEvents",),
        ),
    )


def analyze_fixture(value):
    return sd.analyze_video(
        "fixture.mp4",
        input_sha256="a" * 64,
        duration_ms=value["durationMs"],
        width=1080,
        height=1920,
        fps=30.0,
        has_audio=False,
        brief="deterministic semantic conformance fixture",
        adapters=fixture_adapters(value),
    )


class SemanticDirectorR18Tests(unittest.TestCase):
    def test_contract_provenance_and_missing_provider_are_explicit(self):
        analysis = sd.analyze_video(
            "missing.mp4",
            input_sha256="b" * 64,
            duration_ms=6000,
            width=1080,
            height=1920,
            fps=30.0,
            has_audio=False,
            brief="minimal fallback",
            adapters=unavailable_adapters(),
        )
        self.assertEqual(
            analysis["contractVersion"],
            "creator.semantic_video_analysis.r18.v1",
        )
        self.assertEqual(
            analysis["claim"]["humanLevelQuality"],
            "HUMAN_LEVEL_UNPROVEN",
        )
        self.assertFalse(
            analysis["claim"]["syntheticFixturesMayProveHumanLevel"]
        )
        self.assertEqual(analysis["evidence"]["transcriptSegments"], [])
        self.assertEqual(analysis["evidence"]["visualSubjects"], [])
        self.assertEqual(analysis["evidence"]["importantObjects"], [])
        self.assertIn(
            "transcriptSegments",
            analysis["unavailableEvidence"],
        )
        self.assertIn(
            "importantObjects",
            analysis["unavailableEvidence"],
        )
        for values in analysis["evidence"].values():
            for item in values:
                self.assertGreaterEqual(item["confidence"], 0.0)
                self.assertLessEqual(item["confidence"], 1.0)
                self.assertEqual(
                    item["source"]["inputSha256"],
                    "b" * 64,
                )
                self.assertTrue(item["source"]["sourceDigest"])
                self.assertTrue(item["evidenceDigest"])

    def test_five_conformance_fixtures_choose_expected_modes(self):
        names = [
            "talking-head-explainer.json",
            "product-demo.json",
            "story-punchline.json",
            "cinematic-montage.json",
            "static-low-energy.json",
        ]
        observed = {}
        for name in names:
            value = json.loads(
                (FIXTURE_DIR / name).read_text(encoding="utf-8")
            )
            analysis = analyze_fixture(value)
            decision = sd.select_editorial_mode(analysis)
            observed[value["id"]] = decision["effectiveMode"]
            self.assertEqual(
                decision["effectiveMode"],
                value["expectedMode"],
                value["id"],
            )
            self.assertGreater(
                decision["autoDirector"]["confidence"],
                0.0,
            )
            self.assertTrue(
                decision["autoDirector"]["rationale"],
                value["id"],
            )
        self.assertEqual(
            set(observed),
            {
                "talking-head-explainer",
                "product-demo",
                "story-punchline",
                "cinematic-montage",
                "static-low-energy",
            },
        )

    def test_product_demo_directives_preserve_reveal_and_continuity(self):
        value = json.loads(
            (FIXTURE_DIR / "product-demo.json").read_text(
                encoding="utf-8"
            )
        )
        analysis = analyze_fixture(value)
        decision = sd.select_editorial_mode(analysis)
        directives = sd.generate_edit_directives(
            analysis,
            decision,
        )
        self.assertEqual(decision["effectiveMode"], "hybrid")
        self.assertTrue(directives["preserveImportantReveals"])
        self.assertTrue(directives["continuityPreserve"])
        self.assertTrue(directives["broll"]["allowed"])
        self.assertTrue(
            directives["broll"]["requireSemanticMatch"]
        )
        self.assertFalse(directives["cta"]["proposed"])
        self.assertIn(
            "sentenceBoundariesMs",
            directives["mediaHints"],
        )
        self.assertIn("saliency", directives["mediaHints"])

    def test_story_payoff_enables_emphasis_and_loop_only_with_evidence(self):
        value = json.loads(
            (FIXTURE_DIR / "story-punchline.json").read_text(
                encoding="utf-8"
            )
        )
        analysis = analyze_fixture(value)
        decision = sd.select_editorial_mode(analysis)
        directives = sd.generate_edit_directives(
            analysis,
            decision,
        )
        self.assertEqual(
            decision["effectiveMode"],
            "aggressive_shortform",
        )
        self.assertTrue(directives["payoffVisualEmphasis"])
        self.assertTrue(directives["loop"]["proposed"])
        self.assertFalse(directives["cta"]["proposed"])
        self.assertTrue(directives["captionEmphasis"])

        static = json.loads(
            (FIXTURE_DIR / "static-low-energy.json").read_text(
                encoding="utf-8"
            )
        )
        static_analysis = analyze_fixture(static)
        static_directives = sd.generate_edit_directives(
            static_analysis,
            sd.select_editorial_mode(static_analysis),
        )
        self.assertFalse(static_directives["loop"]["proposed"])
        self.assertFalse(static_directives["cta"]["proposed"])

    def test_explicit_style_override_wins_and_reports_material_disagreement(self):
        value = json.loads(
            (FIXTURE_DIR / "cinematic-montage.json").read_text(
                encoding="utf-8"
            )
        )
        analysis = analyze_fixture(value)
        automatic = sd.select_editorial_mode(analysis)
        self.assertEqual(
            automatic["effectiveMode"],
            "cinematic_minimal",
        )
        overridden = sd.select_editorial_mode(
            analysis,
            override="clean",
        )
        self.assertEqual(
            overridden["effectiveMode"],
            "clean_podcast",
        )
        self.assertTrue(overridden["override"]["applied"])
        self.assertTrue(
            overridden["override"]["materialDisagreement"]
        )
        self.assertEqual(
            overridden["autoDirector"]["mode"],
            "cinematic_minimal",
        )

    def test_director_report_is_human_reviewable_without_quality_claim(self):
        value = json.loads(
            (FIXTURE_DIR / "product-demo.json").read_text(
                encoding="utf-8"
            )
        )
        analysis = analyze_fixture(value)
        decision = sd.select_editorial_mode(analysis)
        directives = sd.generate_edit_directives(
            analysis,
            decision,
        )
        report = sd.build_director_report(
            analysis,
            decision,
            directives,
        )
        self.assertEqual(
            report["readiness"],
            "SEMANTIC_PIPELINE_READY",
        )
        self.assertEqual(
            report["humanLevelQuality"],
            "HUMAN_LEVEL_UNPROVEN",
        )
        self.assertFalse(
            report["claims"]["humanLevelQualityClaimed"]
        )
        self.assertIn("semanticTimeline", report)
        self.assertIn("chosenStyle", report)
        self.assertIn("keyMoments", report)
        self.assertIn("cutsToPreserve", report)
        self.assertIn("broll", report)
        self.assertIn("captionEmphasis", report)
        self.assertIn("unavailableEvidence", report)

    def test_adapter_backed_evidence_changes_edit_decision_from_fallback(self):
        fallback = sd.analyze_video(
            "missing.mp4",
            input_sha256="c" * 64,
            duration_ms=6000,
            width=1080,
            height=1920,
            fps=30.0,
            has_audio=False,
            brief="same source",
            adapters=unavailable_adapters(),
        )
        fallback_decision = sd.select_editorial_mode(fallback)
        fallback_directives = sd.generate_edit_directives(
            fallback,
            fallback_decision,
        )
        self.assertEqual(
            fallback_decision["effectiveMode"],
            "clean_podcast",
        )

        semantic = sd.SemanticAdapters(
            asr=sd.FixtureAdapter(
                "adapter_asr",
                (
                    {
                        "evidenceType": "transcript_segment",
                        "startMs": 0,
                        "endMs": 3000,
                        "value": {
                            "text": "First the setup looks normal.",
                            "speechEnergy": 0.8,
                        },
                        "confidence": 0.95,
                    },
                    {
                        "evidenceType": "transcript_segment",
                        "startMs": 3000,
                        "endMs": 6000,
                        "value": {
                            "text": "But then the reveal lands as the punchline.",
                            "speechEnergy": 0.86,
                        },
                        "confidence": 0.96,
                    },
                ),
                ("transcriptSegments",),
            ),
            shot=sd.FixtureAdapter(
                "adapter_shot",
                (
                    {
                        "evidenceType": "shot_boundary",
                        "startMs": 3200,
                        "endMs": 3201,
                        "value": {"boundaryMs": 3200},
                        "confidence": 0.88,
                    },
                    {
                        "evidenceType": "motion_energy",
                        "startMs": 0,
                        "endMs": 6000,
                        "value": {
                            "normalizedEnergy": 0.42,
                            "basis": "adapter",
                        },
                        "confidence": 0.82,
                    },
                ),
                ("shotBoundaries", "motionEnergy"),
            ),
            cv=sd.UnavailableAdapter(
                "cv",
                ("visualSubjects", "importantObjects"),
            ),
            vlm=sd.FixtureAdapter(
                "adapter_vlm",
                (
                    {
                        "evidenceType": "semantic_event",
                        "startMs": 4300,
                        "endMs": 6000,
                        "value": {
                            "event": "punchline_payoff",
                            "basis": "adapter",
                        },
                        "confidence": 0.97,
                    },
                ),
                ("semanticEvents",),
            ),
        )
        enriched = sd.analyze_video(
            "missing.mp4",
            input_sha256="c" * 64,
            duration_ms=6000,
            width=1080,
            height=1920,
            fps=30.0,
            has_audio=False,
            brief="same source",
            adapters=semantic,
        )
        enriched_decision = sd.select_editorial_mode(enriched)
        enriched_directives = sd.generate_edit_directives(
            enriched,
            enriched_decision,
        )
        self.assertEqual(
            enriched_decision["effectiveMode"],
            "aggressive_shortform",
        )
        self.assertNotEqual(
            enriched_decision["mediaBaseStyle"],
            fallback_decision["mediaBaseStyle"],
        )
        self.assertNotEqual(
            enriched_directives["mediaHints"],
            fallback_directives["mediaHints"],
        )
        self.assertTrue(enriched_directives["loop"]["proposed"])

    @unittest.skipUnless(
        os.environ.get("CREATOR_MEDIA_R13_DIR"),
        "exact Media R13 checkout required for adapter-backed plan integration",
    )
    def test_adapter_evidence_changes_actual_media_creative_plan(self):
        media_repo = Path(
            os.environ["CREATOR_MEDIA_R13_DIR"]
        ).resolve()
        adapters = sd.SemanticAdapters(
            asr=sd.FixtureAdapter(
                "integration_asr",
                (
                    {
                        "evidenceType": "transcript_segment",
                        "startMs": 0,
                        "endMs": 3000,
                        "value": {
                            "text": "First the setup looks normal.",
                            "speechEnergy": 0.8,
                        },
                        "confidence": 0.95,
                    },
                    {
                        "evidenceType": "transcript_segment",
                        "startMs": 3000,
                        "endMs": 6000,
                        "value": {
                            "text": "But then the reveal lands as the punchline.",
                            "speechEnergy": 0.85,
                        },
                        "confidence": 0.96,
                    },
                ),
                ("transcriptSegments",),
            ),
            shot=sd.FixtureAdapter(
                "integration_shot",
                (
                    {
                        "evidenceType": "shot_boundary",
                        "startMs": 3200,
                        "endMs": 3201,
                        "value": {"boundaryMs": 3200},
                        "confidence": 0.9,
                    },
                    {
                        "evidenceType": "motion_energy",
                        "startMs": 0,
                        "endMs": 6000,
                        "value": {
                            "normalizedEnergy": 0.4,
                            "basis": "adapter",
                        },
                        "confidence": 0.85,
                    },
                ),
                ("shotBoundaries", "motionEnergy"),
            ),
            cv=sd.UnavailableAdapter(
                "cv",
                ("visualSubjects", "importantObjects"),
            ),
            vlm=sd.FixtureAdapter(
                "integration_vlm",
                (
                    {
                        "evidenceType": "semantic_event",
                        "startMs": 4300,
                        "endMs": 6000,
                        "value": {
                            "event": "punchline_payoff",
                            "basis": "adapter",
                        },
                        "confidence": 0.97,
                    },
                ),
                ("semanticEvents",),
            ),
        )
        fallback_analysis = sd.analyze_video(
            "fixture.mp4",
            input_sha256="d" * 64,
            duration_ms=6000,
            width=1080,
            height=1920,
            fps=30.0,
            has_audio=False,
            brief="same source",
            adapters=unavailable_adapters(),
        )
        fallback_decision = sd.select_editorial_mode(
            fallback_analysis
        )
        fallback_directives = sd.generate_edit_directives(
            fallback_analysis,
            fallback_decision,
        )
        enriched_analysis = sd.analyze_video(
            "fixture.mp4",
            input_sha256="d" * 64,
            duration_ms=6000,
            width=1080,
            height=1920,
            fps=30.0,
            has_audio=False,
            brief="same source",
            adapters=adapters,
        )
        enriched_decision = sd.select_editorial_mode(
            enriched_analysis
        )
        enriched_directives = sd.generate_edit_directives(
            enriched_analysis,
            enriched_decision,
        )
        self.assertEqual(
            fallback_decision["effectiveMode"],
            "clean_podcast",
        )
        self.assertEqual(
            enriched_decision["effectiveMode"],
            "aggressive_shortform",
        )

        with tempfile.TemporaryDirectory() as temp:
            request = Path(temp) / "compare.json"
            request.write_text(
                json.dumps({
                    "fallback": {
                        "mediaStyle":
                            fallback_decision["mediaBaseStyle"],
                        "hints":
                            fallback_directives["mediaHints"],
                        "loopFriendly":
                            fallback_directives["loop"]["proposed"],
                    },
                    "enriched": {
                        "mediaStyle":
                            enriched_decision["mediaBaseStyle"],
                        "hints":
                            enriched_directives["mediaHints"],
                        "loopFriendly":
                            enriched_directives["loop"]["proposed"],
                    },
                }),
                encoding="utf-8",
            )
            helper = (
                Path(__file__).resolve().parents[1]
                / "tools"
                / "semantic-plan-compare-r18.mjs"
            )
            compared = subprocess.run(
                [
                    "node",
                    str(helper),
                    "--media-repo",
                    str(media_repo),
                    "--input",
                    str(request),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
        self.assertEqual(
            compared.returncode,
            0,
            compared.stderr[-4000:],
        )
        result = json.loads(compared.stdout)
        self.assertEqual(
            result["producerSha"],
            "ad4e0ba487a3cabc84dd339d412e19a0db0f9add",
        )
        self.assertEqual(
            result["fallback"]["style"],
            "clean_podcast",
        )
        self.assertEqual(
            result["enriched"]["style"],
            "aggressive_shortform",
        )
        self.assertNotEqual(
            result["fallback"]["planDigest"],
            result["enriched"]["planDigest"],
        )
        self.assertNotEqual(
            result["fallback"]["hintDigest"],
            result["enriched"]["hintDigest"],
        )
        self.assertFalse(result["fallback"]["loopFriendly"])
        self.assertTrue(result["enriched"]["loopFriendly"])



if __name__ == "__main__":
    unittest.main()
