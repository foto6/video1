from __future__ import annotations

import json
import tempfile
from pathlib import Path

from creator_orchestrator.checkpoint import (
    build_reproducibility_report,
    export_campaign_checkpoint,
    write_campaign_checkpoint,
)
from creator_orchestrator.simulator import CampaignRunner, load_campaign_fixture

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "fixtures" / "campaign.checkpoint.v1.source.json"
OUTPUT = ROOT / "fixtures" / "checkpoints"

BOUNDARIES = [
    "00_created",
    "01_research",
    "02_idea",
    "03_script",
    "04_assets",
    "05_voice",
    "06_edit",
    "07_critic",
    "08_publish_queue",
    "09_analytics",
    "10_terminal",
]


def main() -> None:
    config = load_campaign_fixture(CONFIG)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.glob("*.json"):
        path.unlink()

    with tempfile.TemporaryDirectory() as td:
        runner = CampaignRunner(td, config)
        runner.initialize()
        runner.step()  # durable job creation boundary

        checkpoints: list[tuple[str, dict]] = []
        for index, boundary in enumerate(BOUNDARIES):
            if index > 0:
                runner.step()
            bundle = export_campaign_checkpoint(
                td,
                campaign_id=config.campaign_id,
                campaign_config=config.raw,
                repo_root=ROOT,
            )
            filename = f"{boundary}.checkpoint.json"
            write_campaign_checkpoint(
                bundle,
                OUTPUT / filename,
                repo_root=ROOT,
            )
            checkpoints.append((f"fixtures/checkpoints/{filename}", bundle))

        final_bundle = checkpoints[-1][1]
        report = build_reproducibility_report(
            checkpoints,
            final_checkpoint=final_bundle,
        )
        (OUTPUT / "reproducibility_report_v1.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
