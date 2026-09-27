from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Mapping, Sequence

from .models import Artifact, Evaluation, Job, JobStage, JobState, STAGE_ORDER, StepResult
from .ports import Adapter, EvaluationHook, StepContext


class RetryableStepError(RuntimeError):
    pass


class EvaluationRejected(RuntimeError):
    pass


class MissingAdapter(RuntimeError):
    pass


class RetryPolicy:
    def __init__(self, max_attempts: int = 3) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.max_attempts = max_attempts


class JsonJobStore:
    """Small durable store using atomic file replacement."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        safe = "".join(c for c in job_id if c.isalnum() or c in "-_.")
        if not safe or safe != job_id:
            raise ValueError("unsafe job id")
        return self.directory / f"{safe}.json"

    def save(self, job: Job) -> None:
        payload = {
            **asdict(job),
            "state": job.state.value,
        }
        path = self._path(job.id)
        fd, temp_name = tempfile.mkstemp(prefix=path.name, dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def load(self, job_id: str) -> Job:
        data = json.loads(self._path(job_id).read_text(encoding="utf-8"))
        data["state"] = JobState(data["state"])
        data["artifacts"] = [
            Artifact(
                **{
                    **artifact,
                    "parents": tuple(artifact.get("parents", ())),
                }
            )
            for artifact in data.get("artifacts", [])
        ]
        data["evaluations"] = [Evaluation(**item) for item in data.get("evaluations", [])]
        return Job(**data)


class Orchestrator:
    """Durable stage machine for the creator pipeline.

    A job advances only after the stage result, evaluations, lineage and
    idempotency key are persisted together. Provider adapters receive a stable
    idempotency key so external calls can deduplicate redelivery.
    """

    def __init__(
        self,
        store: JsonJobStore,
        adapters: Mapping[JobStage, Adapter],
        evaluation_hooks: Sequence[EvaluationHook] = (),
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.store = store
        self.adapters = dict(adapters)
        self.evaluation_hooks = tuple(evaluation_hooks)
        self.retry_policy = retry_policy or RetryPolicy()

    def create_job(self, job_id: str, topic: str) -> Job:
        job = Job(id=job_id, topic=topic)
        self.store.save(job)
        return job

    @staticmethod
    def _idempotency_key(job: Job, stage: JobStage) -> str:
        lineage = ",".join(a.id for a in job.artifacts)
        raw = f"{job.id}|{stage.value}|{lineage}".encode()
        return hashlib.sha256(raw).hexdigest()

    def run_next(self, job_id: str) -> Job:
        job = self.store.load(job_id)
        if job.state in (JobState.COMPLETE, JobState.FAILED):
            return job

        stage = job.stage
        if stage is None:
            job.state = JobState.COMPLETE
            job.touch()
            self.store.save(job)
            return job

        adapter = self.adapters.get(stage)
        if adapter is None:
            job.state = JobState.FAILED
            job.last_error = f"missing adapter for {stage.value}"
            job.touch()
            self.store.save(job)
            raise MissingAdapter(job.last_error)

        key = self._idempotency_key(job, stage)
        if job.completed_idempotency_keys.get(stage.value) == key:
            job.stage_index += 1
            if job.stage is None:
                job.state = JobState.COMPLETE
            job.touch()
            self.store.save(job)
            return job

        job.state = JobState.RUNNING
        job.attempts[stage.value] = job.attempts.get(stage.value, 0) + 1
        job.touch()
        self.store.save(job)

        context = StepContext(
            job_id=job.id,
            topic=job.topic,
            stage=stage,
            idempotency_key=key,
            artifacts=tuple(job.artifacts),
        )

        try:
            result = adapter.execute(context)
        except RetryableStepError as exc:
            job = self.store.load(job_id)
            job.last_error = str(exc)
            if job.attempts[stage.value] >= self.retry_policy.max_attempts:
                job.state = JobState.FAILED
            else:
                job.state = JobState.WAITING_RETRY
            job.touch()
            self.store.save(job)
            return job
        except Exception as exc:
            job = self.store.load(job_id)
            job.state = JobState.FAILED
            job.last_error = f"{type(exc).__name__}: {exc}"
            job.touch()
            self.store.save(job)
            return job

        job = self.store.load(job_id)
        evaluations = [
            hook.evaluate(job, stage, result)
            for hook in self.evaluation_hooks
        ]
        job.evaluations.extend(evaluations)
        rejected = next((item for item in evaluations if not item.approved), None)
        if rejected:
            job.state = JobState.FAILED
            job.last_error = f"evaluation rejected by {rejected.hook}: {rejected.notes}"
            job.touch()
            self.store.save(job)
            return job

        existing = {artifact.id for artifact in job.artifacts}
        for artifact in result.artifacts:
            if artifact.id not in existing:
                job.artifacts.append(artifact)
                existing.add(artifact.id)

        job.completed_idempotency_keys[stage.value] = key
        job.stage_index += 1
        job.last_error = None
        job.state = JobState.COMPLETE if job.stage is None else JobState.PENDING
        job.touch()
        self.store.save(job)
        return job

    def run_to_terminal(self, job_id: str) -> Job:
        while True:
            job = self.run_next(job_id)
            if job.state in (JobState.COMPLETE, JobState.FAILED, JobState.WAITING_RETRY):
                return job
