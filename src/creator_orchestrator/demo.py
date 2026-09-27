from __future__ import annotations

import argparse
import json
from pathlib import Path

from .simulator import CampaignRunner, load_campaign_fixture


def run_demo(fixture_path: str | Path, state_root: str | Path) -> dict:
    config = load_campaign_fixture(fixture_path)
    state = CampaignRunner(state_root, config).run_to_terminal()
    if state.status != "complete" or state.report_artifact is None:
        raise RuntimeError(state.last_error or "campaign simulation did not complete")
    return {
        "campaignId": state.campaign_id,
        "status": state.status,
        "completedCycles": state.completed_cycles,
        "reportArtifact": {
            "id": state.report_artifact.id,
            "kind": state.report_artifact.kind,
            "parents": list(state.report_artifact.parents),
            "metadata": state.report_artifact.metadata,
            "created_at": state.report_artifact.created_at,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic autonomous creator campaign simulation")
    parser.add_argument("fixture")
    parser.add_argument("state_root")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = run_demo(args.fixture, args.state_root)
    wire = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(wire + "\n", encoding="utf-8")
    print(wire)


if __name__ == "__main__":
    main()
