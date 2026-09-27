from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from creator_orchestrator.campaign_chaos import (
    GROWTH_SOURCE_HEAD,
    MEDIA_SOURCE_HEAD,
    run_campaign_chaos,
)

ROOT = Path(__file__).resolve().parents[1]
GROWTH_FIXTURE = ROOT / "fixtures" / "upstream" / "growth" / "creator_next_cycle_seed_v1.json"
MEDIA_FIXTURE = ROOT / "fixtures" / "upstream" / "media" / "media.job.v1.consumer.json"
EXPECTED_REPORT = ROOT / "fixtures" / "campaign_chaos.stress_report.v1.json"


class CampaignChaosTests(unittest.TestCase):
    def test_50_cycle_soak_is_deterministic_under_variant_reordering(self):
        with tempfile.TemporaryDirectory() as left_dir, tempfile.TemporaryDirectory() as right_dir:
            left = run_campaign_chaos(
                left_dir,
                growth_fixture_path=GROWTH_FIXTURE,
                media_fixture_path=MEDIA_FIXTURE,
                cycles=50,
                variants_per_cycle=2,
                seed=73421,
                ordering="forward",
            )
            right = run_campaign_chaos(
                right_dir,
                growth_fixture_path=GROWTH_FIXTURE,
                media_fixture_path=MEDIA_FIXTURE,
                cycles=50,
                variants_per_cycle=2,
                seed=73421,
                ordering="permuted",
            )
            self.assertEqual(left, right)
            self.assertEqual(left, json.loads(EXPECTED_REPORT.read_text(encoding="utf-8")))
            self.assertEqual(left["cycles"], 50)
            self.assertEqual(left["jobs"], 100)
            self.assertEqual(left["growth"]["committedBatches"], 50)
            self.assertEqual(left["media"]["acceptedJobs"], 100)
            self.assertEqual(left["creator"]["completeJobs"], 100)
            self.assertEqual(left["creator"]["livePublishCalls"], 0)
            self.assertEqual(left["creator"]["immutableLineageChecks"], 100)
            self.assertGreaterEqual(left["crashes"], 150)
            self.assertGreater(left["polls"], 100)

    def test_exact_green_producer_heads_are_reported(self):
        self.assertEqual(GROWTH_SOURCE_HEAD, "8d1a94cae77f2886b514477c272d7bc6de978042")
        self.assertEqual(MEDIA_SOURCE_HEAD, "c921308a9deef916d088dc7c2c1186071eccb6e8")

    def test_soak_rejects_too_few_cycles_or_variants(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                run_campaign_chaos(
                    td,
                    growth_fixture_path=GROWTH_FIXTURE,
                    media_fixture_path=MEDIA_FIXTURE,
                    cycles=49,
                    variants_per_cycle=2,
                )
            with self.assertRaises(ValueError):
                run_campaign_chaos(
                    td,
                    growth_fixture_path=GROWTH_FIXTURE,
                    media_fixture_path=MEDIA_FIXTURE,
                    cycles=50,
                    variants_per_cycle=1,
                )


if __name__ == "__main__":
    unittest.main()
