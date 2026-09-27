from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStage(str, Enum):
    RESEARCH = "research"
    IDEA = "idea"
    SCRIPT = "script"
    ASSETS = "assets"
    VOICE = "voice"
    EDIT = "edit"
    CRITIC = "critic"
    PUBLISH_QUEUE = "publish_queue"
    ANALYTICS = "analytics"


STAGE_ORDER: tuple[JobStage, ...] = (
    JobStage.RESEARCH,
    JobStage.IDEA,
    JobStage.SCRIPT,
    JobStage.ASSETS,
    JobStage.VOICE,
    JobStage.EDIT,
    JobStage.CRITIC,
    JobStage.PUBLISH_QUEUE,
    JobStage.ANALYTICS,
)


class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_RETRY = "waiting_retry"
    FAILED = "failed"
    COMPLETE = "complete"


@dataclass(frozen=True)
class Artifact:
    id: str
    kind: str
    uri: str
    producer: str
    parents: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class Evaluation:
    hook: str
    approved: bool
    score: float | None = None
    notes: str = ""
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class StepResult:
    artifacts: tuple[Artifact, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Job:
    id: str
    topic: str
    state: JobState = JobState.PENDING
    stage_index: int = 0
    attempts: dict[str, int] = field(default_factory=dict)
    idempotency_attempts: dict[str, int] = field(default_factory=dict)
    completed_idempotency_keys: dict[str, str] = field(default_factory=dict)
    artifacts: list[Artifact] = field(default_factory=list)
    evaluations: list[Evaluation] = field(default_factory=list)
    last_error: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @property
    def stage(self) -> JobStage | None:
        if self.stage_index >= len(STAGE_ORDER):
            return None
        return STAGE_ORDER[self.stage_index]

    def touch(self) -> None:
        self.updated_at = utc_now()
