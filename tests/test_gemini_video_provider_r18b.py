from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from creator_orchestrator import gemini_video_provider as gv
from creator_orchestrator import semantic_director as sd


def provider_output():
    return {
        "contractVersion": sd.SEMANTIC_ANALYSIS_VERSION,
        "transcriptSegments": [
            {
                "startMs": 0,
                "endMs": 2500,
                "text": "Watch this product and the screen.",
                "confidence": 0.96,
            },
            {
                "startMs": 2500,
                "endMs": 5200,
                "text": "Here is the result after the tap.",
                "confidence": 0.95,
            },
        ],
        "visualSubjects": [
            {
                "startMs": 0,
                "endMs": 6000,
                "kind": "person",
                "label": "presenter",
                "box": {
                    "x": 0.10,
                    "y": 0.08,
                    "width": 0.42,
                    "height": 0.80,
                },
                "confidence": 0.92,
            }
        ],
        "importantObjects": [
            {
                "startMs": 800,
                "endMs": 5200,
                "kind": "product",
                "label": "device",
                "isReveal": True,
                "confidence": 0.97,
            },
            {
                "startMs": 2200,
                "endMs": 5200,
                "kind": "screen",
                "label": "interface",
                "isReveal": True,
                "confidence": 0.95,
            },
        ],
        "semanticEvents": [
            {
                "startMs": 0,
                "endMs": 1800,
                "event": "hook",
                "rationale": "The presenter immediately promises a visible result.",
                "confidence": 0.91,
            },
            {
                "startMs": 1400,
                "endMs": 5200,
                "event": "proof_demo",
                "rationale": "The product interaction and screen result are shown.",
                "confidence": 0.97,
            },
        ],
    }


def disabled_adapters():
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


class GeminiNativeVideoProviderR18BTests(unittest.TestCase):
    def temp_video(self):
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name) / "native-video.mp4"
        path.write_bytes(b"\x00\x00\x00\x18ftypmp42fake-native-video")
        return temp, path

    def context(self):
        return {
            "inputSha256": "a" * 64,
            "durationMs": 6000,
            "width": 360,
            "height": 640,
            "fps": 30.0,
            "hasAudio": True,
            "brief": "Show the product proof clearly.",
            "briefDigest": "b" * 64,
        }

    def test_provider_is_disabled_by_default_and_key_is_never_artifacted(self):
        temp, path = self.temp_video()
        self.addCleanup(temp.cleanup)
        adapter = gv.GeminiNativeVideoAdapter(
            config=gv.GeminiNativeVideoConfig(),
        )
        with mock.patch.dict(os.environ, {}, clear=True):
            result = adapter.analyze(path, self.context())
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], gv.PROVIDER_UNAVAILABLE)
        self.assertEqual(result["evidence"], [])
        self.assertNotIn("GEMINI_API_KEY", json.dumps(result))
        self.assertNotIn("authorization", json.dumps(result).lower())

    def test_static_native_video_uses_bounded_fps_clip_model_and_cleanup(self):
        temp, path = self.temp_video()
        self.addCleanup(temp.cleanup)
        transport = gv.FakeGeminiVideoTransport(
            output=provider_output(),
        )
        config = gv.GeminiNativeVideoConfig(
            enabled=True,
            model="gemini-configurable-test-model",
            mode="static",
            static_fps=2.5,
            clip_start_seconds=0.5,
            clip_end_seconds=5.5,
            max_retries=0,
        )
        adapter = gv.GeminiNativeVideoAdapter(
            config=config,
            transport=transport,
            api_key="must-never-appear",
            sleep_fn=lambda _: None,
        )
        result = adapter.analyze(path, self.context())
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["providerMode"], "gemini_static")
        calls = [call for call in transport.calls if call["op"] == "analyze"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["model"], "gemini-configurable-test-model")
        self.assertEqual(calls[0]["mode"], "static")
        self.assertEqual(calls[0]["fps"], 2.5)
        self.assertEqual(calls[0]["clipStart"], 0.5)
        self.assertEqual(calls[0]["clipEnd"], 5.5)
        self.assertEqual(transport.deleted, ["files/fake-native-video"])
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn("must-never-appear", serialized)
        self.assertNotIn("gemini://fake-native-video", serialized)
        first = result["evidence"][0]
        provenance = first["value"]["providerProvenance"]
        self.assertEqual(provenance["provider"], "google_gemini")
        self.assertEqual(provenance["model"], "gemini-configurable-test-model")
        self.assertEqual(provenance["mode"], "static")
        self.assertTrue(provenance["requestDigest"])
        self.assertTrue(provenance["uploadIdentityDigest"])
        self.assertEqual(first["source"]["mode"], "provider")

    def test_agentic_requires_explicit_model_capability_and_is_transport_visible(self):
        temp, path = self.temp_video()
        self.addCleanup(temp.cleanup)
        unsupported = gv.GeminiNativeVideoAdapter(
            config=gv.GeminiNativeVideoConfig(
                enabled=True,
                mode="agentic",
                agentic_model_supported=False,
            ),
            transport=gv.FakeGeminiVideoTransport(
                output=provider_output()
            ),
        )
        blocked = unsupported.analyze(path, self.context())
        self.assertEqual(blocked["reason"], gv.PROVIDER_UNAVAILABLE)

        transport = gv.FakeGeminiVideoTransport(
            output=provider_output()
        )
        supported = gv.GeminiNativeVideoAdapter(
            config=gv.GeminiNativeVideoConfig(
                enabled=True,
                model="agentic-capable-test-model",
                mode="agentic",
                agentic_model_supported=True,
                max_retries=0,
            ),
            transport=transport,
            sleep_fn=lambda _: None,
        )
        result = supported.analyze(path, self.context())
        self.assertEqual(result["status"], "available")
        analyze_call = next(
            call for call in transport.calls if call["op"] == "analyze"
        )
        self.assertEqual(analyze_call["mode"], "agentic")
        self.assertEqual(
            analyze_call["model"],
            "agentic-capable-test-model",
        )

    def test_out_of_range_model_timestamp_is_rejected_and_remote_file_deleted(self):
        temp, path = self.temp_video()
        self.addCleanup(temp.cleanup)
        invalid = provider_output()
        invalid["semanticEvents"][0]["endMs"] = 7000
        transport = gv.FakeGeminiVideoTransport(output=invalid)
        adapter = gv.GeminiNativeVideoAdapter(
            config=gv.GeminiNativeVideoConfig(
                enabled=True,
                max_retries=0,
            ),
            transport=transport,
            sleep_fn=lambda _: None,
        )
        result = adapter.analyze(path, self.context())
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], gv.PROVIDER_INVALID_OUTPUT)
        self.assertEqual(result["evidence"], [])
        self.assertEqual(transport.deleted, ["files/fake-native-video"])

    def test_timeout_is_explicit_bounded_and_remote_file_deleted(self):
        temp, path = self.temp_video()
        self.addCleanup(temp.cleanup)
        transport = gv.FakeGeminiVideoTransport(
            output=provider_output(),
            poll_states=("ACTIVE",),
            timeout_on_analyze=True,
        )
        adapter = gv.GeminiNativeVideoAdapter(
            config=gv.GeminiNativeVideoConfig(
                enabled=True,
                max_retries=0,
                request_timeout_seconds=1,
                cleanup_timeout_seconds=1,
            ),
            transport=transport,
            sleep_fn=lambda _: None,
        )
        result = adapter.analyze(path, self.context())
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], gv.PROVIDER_TIMEOUT)
        self.assertEqual(transport.deleted, ["files/fake-native-video"])

    def test_smoke_is_noop_blocked_without_explicit_credentials(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            report = gv.smoke(
                input_path="not-needed.mp4",
                live=False,
                mode="static",
                fps=1.0,
                clip_start_seconds=0.0,
                clip_end_seconds=None,
            )
        self.assertEqual(report["state"], "BLOCKED")
        self.assertFalse(report["networkAttempted"])
        self.assertIn("GEMINI_API_KEY", report["reason"])

    @unittest.skipUnless(
        os.environ.get("CREATOR_MEDIA_R13_DIR"),
        "exact Media R13 checkout required for plan integration",
    )
    def test_fake_native_video_changes_semantics_directives_and_media_plan(self):
        temp, path = self.temp_video()
        self.addCleanup(temp.cleanup)
        transport = gv.FakeGeminiVideoTransport(
            output=provider_output(),
            poll_states=("PROCESSING", "ACTIVE"),
        )
        config = gv.GeminiNativeVideoConfig(
            enabled=True,
            model="fake-semantic-model",
            mode="static",
            static_fps=2.0,
            clip_start_seconds=0.0,
            clip_end_seconds=6.0,
            max_retries=0,
        )
        adapters = gv.build_semantic_adapters(
            config=config,
            transport=transport,
            api_key="not-artifacted",
        )
        enriched = sd.analyze_video(
            path,
            input_sha256="a" * 64,
            duration_ms=6000,
            width=360,
            height=640,
            fps=30.0,
            has_audio=False,
            brief="Show the product proof clearly.",
            adapters=adapters,
        )
        fallback = sd.analyze_video(
            path,
            input_sha256="a" * 64,
            duration_ms=6000,
            width=360,
            height=640,
            fps=30.0,
            has_audio=False,
            brief="Show the product proof clearly.",
            adapters=disabled_adapters(),
        )
        enriched_decision = sd.select_editorial_mode(enriched)
        fallback_decision = sd.select_editorial_mode(fallback)
        enriched_directives = sd.generate_edit_directives(
            enriched,
            enriched_decision,
        )
        fallback_directives = sd.generate_edit_directives(
            fallback,
            fallback_decision,
        )
        self.assertEqual(
            fallback_decision["effectiveMode"],
            "clean_podcast",
        )
        self.assertEqual(
            enriched_decision["effectiveMode"],
            "hybrid",
        )
        self.assertNotEqual(
            enriched["analysisDigest"],
            fallback["analysisDigest"],
        )
        self.assertTrue(
            enriched_directives["preserveImportantReveals"]
        )
        self.assertTrue(
            enriched_directives["continuityPreserve"]
        )
        self.assertTrue(enriched_directives["broll"]["allowed"])
        self.assertNotEqual(
            enriched_directives["directivesDigest"],
            fallback_directives["directivesDigest"],
        )

        media_repo = Path(
            os.environ["CREATOR_MEDIA_R13_DIR"]
        ).resolve()
        helper = (
            Path(__file__).resolve().parents[1]
            / "tools"
            / "semantic-plan-compare-r18.mjs"
        )
        with tempfile.TemporaryDirectory() as compare_temp:
            spec = Path(compare_temp) / "compare.json"
            spec.write_text(
                json.dumps(
                    {
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
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "node",
                    str(helper),
                    "--media-repo",
                    str(media_repo),
                    "--input",
                    str(spec),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        plans = json.loads(result.stdout)
        self.assertEqual(
            plans["producerSha"],
            "ad4e0ba487a3cabc84dd339d412e19a0db0f9add",
        )
        self.assertNotEqual(
            plans["fallback"]["planDigest"],
            plans["enriched"]["planDigest"],
        )
        self.assertNotEqual(
            plans["fallback"]["hintDigest"],
            plans["enriched"]["hintDigest"],
        )
        report = sd.build_director_report(
            enriched,
            enriched_decision,
            enriched_directives,
        )
        self.assertEqual(
            report["humanLevelQuality"],
            "HUMAN_LEVEL_UNPROVEN",
        )
        self.assertFalse(
            report["claims"]["humanLevelQualityClaimed"]
        )


if __name__ == "__main__":
    unittest.main()
