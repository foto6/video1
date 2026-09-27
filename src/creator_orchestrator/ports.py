from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import Artifact, Evaluation, Job, JobStage, StepResult


@dataclass(frozen=True)
class StepContext:
    job_id: str
    topic: str
    stage: JobStage
    idempotency_key: str
    artifacts: tuple[Artifact, ...]
    attempt: int = 1
    stage_attempt: int = 1


class Adapter(Protocol):
    name: str

    def execute(self, context: StepContext) -> StepResult:
        """Execute one workflow stage using a stable idempotency key."""


class EvaluationHook(Protocol):
    name: str

    def evaluate(self, job: Job, stage: JobStage, result: StepResult) -> Evaluation:
        """Return an evaluation. ``approved=False`` blocks further progress."""
