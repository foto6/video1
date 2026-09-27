from __future__ import annotations

from typing import Any, Mapping

from .adapters import (
    DescriptEditAdapter,
    DescriptVoiceAdapter,
    DeterministicTextAdapter,
    MetricoolPublishQueueAdapter,
    RunwayAssetAdapter,
    VidIQAnalyticsAdapter,
    VidIQResearchAdapter,
)
from .integration import MediaEngineClient, MediaRenderPlanAdapter
from .models import JobStage
from .orchestrator import JsonJobStore, Orchestrator


def _base_adapters():
    return {
        JobStage.RESEARCH: VidIQResearchAdapter(),
        JobStage.IDEA: DeterministicTextAdapter("core-idea", "idea"),
        JobStage.SCRIPT: DeterministicTextAdapter("core-script", "script"),
        JobStage.ASSETS: RunwayAssetAdapter(),
        JobStage.VOICE: DescriptVoiceAdapter(),
        JobStage.EDIT: DescriptEditAdapter(),
        JobStage.CRITIC: DeterministicTextAdapter("core-critic", "critique"),
        JobStage.PUBLISH_QUEUE: MetricoolPublishQueueAdapter(dry_run=True),
        JobStage.ANALYTICS: VidIQAnalyticsAdapter(),
    }


def build_default_orchestrator(store: JsonJobStore) -> Orchestrator:
    """Build the safe MVP: all external providers run in dry-run/no-client mode."""
    return Orchestrator(store=store, adapters=_base_adapters())


def build_media_planning_orchestrator(
    store: JsonJobStore,
    *,
    media_client: MediaEngineClient,
    export_spec: Mapping[str, Any],
    output_path: str,
) -> Orchestrator:
    """Explicit B3 assembly: use Media dry-run planning at the existing edit stage."""
    adapters = _base_adapters()
    adapters[JobStage.EDIT] = MediaRenderPlanAdapter(
        client=media_client,
        export_spec=export_spec,
        output_path=output_path,
    )
    return Orchestrator(store=store, adapters=adapters)
