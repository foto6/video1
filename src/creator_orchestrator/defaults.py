from __future__ import annotations

from .adapters import (
    DescriptEditAdapter,
    DescriptVoiceAdapter,
    DeterministicTextAdapter,
    MetricoolPublishQueueAdapter,
    RunwayAssetAdapter,
    VidIQAnalyticsAdapter,
    VidIQResearchAdapter,
)
from .models import JobStage
from .orchestrator import JsonJobStore, Orchestrator


def build_default_orchestrator(store: JsonJobStore) -> Orchestrator:
    """Build the safe MVP: all external providers run in dry-run/no-client mode."""
    return Orchestrator(
        store=store,
        adapters={
            JobStage.RESEARCH: VidIQResearchAdapter(),
            JobStage.IDEA: DeterministicTextAdapter("core-idea", "idea"),
            JobStage.SCRIPT: DeterministicTextAdapter("core-script", "script"),
            JobStage.ASSETS: RunwayAssetAdapter(),
            JobStage.VOICE: DescriptVoiceAdapter(),
            JobStage.EDIT: DescriptEditAdapter(),
            JobStage.CRITIC: DeterministicTextAdapter("core-critic", "critique"),
            JobStage.PUBLISH_QUEUE: MetricoolPublishQueueAdapter(dry_run=True),
            JobStage.ANALYTICS: VidIQAnalyticsAdapter(),
        },
    )
