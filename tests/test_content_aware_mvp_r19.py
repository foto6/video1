from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from creator_orchestrator import media_r13_compat as m13
from creator_orchestrator import mvp


def run_ffmpeg(args):
    result = subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=90,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr[-6000:])


def generate_talking_head_like(ffmpeg: str, path: Path):
    run_ffmpeg([
        ffmpeg, "-hide_banner", "-nostdin", "-y",
        "-f", "lavfi",
        "-i", "color=c=0x223344:s=360x640:r=30:d=6",
        "-vf",
        "drawbox=x=105:y=90:w=150:h=180:color=0xdddddd:t=fill,"
        "drawbox=x=70:y=285:w=220:h=260:color=0x667788:t=fill",
        "-threads", "1", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", str(path),
    ])


def generate_action(ffmpeg: str, path: Path):
    colors = ["white", "yellow", "cyan", "magenta", "red", "lime"]
    args = [ffmpeg, "-hide_banner", "-nostdin", "-y"]
    for color in colors:
        args += [
            "-f", "lavfi",
            "-i", f"color=c={color}:s=360x640:r=30:d=1",
        ]
    labels = "".join(f"[{i}:v]" for i in range(len(colors)))
    args += [
        "-filter_complex",
        labels + f"concat=n={len(colors)}:v=1:a=0[outv]",
        "-map", "[outv]",
        "-threads", "1",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", str(path),
    ]
    run_ffmpeg(args)


def generate_landscape_screen_like(ffmpeg: str, path: Path):
    run_ffmpeg([
        ffmpeg, "-hide_banner", "-nostdin", "-y",
        "-f", "lavfi",
        "-i", "testsrc2=s=1280x720:r=30:d=6",
        "-vf",
        "drawgrid=w=160:h=90:t=2:color=white@0.35,"
        "drawbox=x=180:y=90:w=920:h=540:color=white@0.15:t=4",
        "-threads", "1",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", str(path),
    ])


@unittest.skipUnless(
    os.environ.get("CREATOR_MEDIA_R13_DIR"),
    "exact Media R13 checkout required for real R19 E2E",
)
class ContentAwareMvpR19Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = shutil.which("ffmpeg")
        cls.ffprobe = shutil.which("ffprobe")
        if not cls.ffmpeg or not cls.ffprobe:
            raise unittest.SkipTest("ffmpeg/ffprobe required")
        cls.media_repo = Path(
            os.environ["CREATOR_MEDIA_R13_DIR"]
        ).resolve()

    def test_default_cli_is_auto_content_aware(self):
        args = mvp._parser().parse_args([
            "--input", "source.mp4",
            "--brief", "Make it concise",
            "--out", "out",
        ])
        self.assertEqual(args.style, "auto")
        self.assertEqual(args.semantic_provider, "auto")

    def test_three_real_generated_sources_produce_content_aware_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = {
                "talking": root / "talking.mp4",
                "action": root / "action.mp4",
                "landscape": root / "landscape.mp4",
            }
            generate_talking_head_like(self.ffmpeg, sources["talking"])
            generate_action(self.ffmpeg, sources["action"])
            generate_landscape_screen_like(
                self.ffmpeg,
                sources["landscape"],
            )

            summaries = {}
            with mock.patch.dict(
                os.environ,
                {
                    "GEMINI_API_KEY": "",
                    "CREATOR_GEMINI_VIDEO_ENABLE": "",
                },
                clear=False,
            ):
                for name, source in sources.items():
                    out = root / ("out-" + name)
                    summaries[name] = mvp.run_pipeline(
                        input_path=source,
                        brief_arg=(
                            "Build a content-aware short while preserving "
                            "source evidence."
                        ),
                        out_dir=out,
                        media_repo=str(self.media_repo),
                    )
                    for filename in (
                        "final.mp4",
                        "preview.mp4",
                        "qa.json",
                        "run-summary.json",
                        "semantic-timeline.json",
                        "editorial-directives.json",
                        "style-decision.json",
                        "content-aware-run.json",
                    ):
                        target = out / filename
                        self.assertTrue(target.is_file(), str(target))
                        self.assertGreater(target.stat().st_size, 0)
                    envelope = json.loads(
                        (out / "content-aware-run.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertEqual(
                        envelope["contractVersion"],
                        "creator.content_aware_run.r19.v1",
                    )
                    self.assertEqual(
                        envelope["source"]["sha256"],
                        summaries[name]["input"]["sha256"],
                    )
                    self.assertEqual(
                        envelope["media"]["producerSha"],
                        m13.MEDIA_R13_PRODUCER_SHA,
                    )
                    self.assertEqual(
                        envelope["media"]["compatibilityContract"],
                        m13.MEDIA_R13_COMPAT_VERSION,
                    )
                    self.assertTrue(envelope["qa"]["technicalPassed"])
                    self.assertTrue(envelope["qa"]["creativePassed"])
                    self.assertFalse(
                        envelope["claims"]["humanLevelQualityClaimed"]
                    )
                    self.assertFalse(
                        envelope["claims"]["aestheticSuperiorityClaimed"]
                    )
                    provider = envelope["semantic"]["provider"]
                    self.assertEqual(
                        provider["effective"],
                        "deterministic_local",
                    )
                    self.assertTrue(provider["fallback"])
                    self.assertEqual(
                        provider["fallbackReason"],
                        "gemini_not_configured",
                    )

            modes = {
                name: summary["style"]["editorialMode"]
                for name, summary in summaries.items()
            }
            self.assertEqual(modes["talking"], "clean_podcast")
            self.assertEqual(
                modes["action"],
                "cinematic_minimal",
            )
            self.assertGreaterEqual(len(set(modes.values())), 2)

            talking_directives = json.loads(
                (root / "out-talking" / "editorial-directives.json")
                .read_text(encoding="utf-8")
            )
            action_directives = json.loads(
                (root / "out-action" / "editorial-directives.json")
                .read_text(encoding="utf-8")
            )
            self.assertNotEqual(
                talking_directives["editorialDirectivesDigest"],
                action_directives["editorialDirectivesDigest"],
            )
            self.assertEqual(
                talking_directives["directives"]["mediaHints"][
                    "beatMarkersMs"
                ],
                [],
            )
            self.assertTrue(
                action_directives["directives"]["mediaHints"][
                    "beatMarkersMs"
                ]
            )

            landscape_timeline = json.loads(
                (root / "out-landscape" / "semantic-timeline.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(
                landscape_timeline["source"]["width"],
                1280,
            )
            self.assertEqual(
                landscape_timeline["source"]["height"],
                720,
            )

    def test_manual_style_override_wins_and_is_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "action.mp4"
            generate_action(self.ffmpeg, source)
            with mock.patch.dict(
                os.environ,
                {
                    "GEMINI_API_KEY": "",
                    "CREATOR_GEMINI_VIDEO_ENABLE": "",
                },
                clear=False,
            ):
                summary = mvp.run_pipeline(
                    input_path=source,
                    brief_arg="Keep this restrained despite action.",
                    out_dir=root / "out",
                    style="clean",
                    media_repo=str(self.media_repo),
                )
            decision = json.loads(
                (root / "out" / "style-decision.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(
                summary["style"]["editorialMode"],
                "clean_podcast",
            )
            self.assertTrue(
                decision["overrideProvenance"]["applied"]
            )
            self.assertEqual(
                decision["overrideProvenance"]["requested"],
                "clean",
            )
            self.assertEqual(
                decision["decision"]["autoDirector"]["mode"],
                "cinematic_minimal",
            )
            self.assertTrue(
                decision["overrideProvenance"]["materialDisagreement"]
            )
            self.assertTrue(
                decision["decision"]["selectionBasis"]["sourceBound"]
            )
            self.assertTrue(
                decision["rejectedAlternatives"]
            )


if __name__ == "__main__":
    unittest.main()
