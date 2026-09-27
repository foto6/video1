from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .external_ops import (
    JsonOperationLedger,
    OperationBoundaryCrash,
    OperationPending,
    OperationPollTimeout,
    OperationPollingExhausted,
    OperationReceipt,
    OperationResumePolicy,
    OperationState,
    ResumableAdapter,
)
from .integration import SeedArtifactInput, build_seed_artifact
from .models import Artifact, Evaluation, Job, JobStage, JobState, STAGE_ORDER, StepResult
from .ports import Adapter, EvaluationHook, StepContext


class RetryableStepError(RuntimeError):
    pass


class EvaluationRejected(RuntimeError):
    pass


class MissingAdapter(RuntimeError):
    pass


class RevisionError(RuntimeError):
    pass


class RetryPolicy:
    def __init__(self, max_attempts: int = 3) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.max_attempts = max_attempts


class JsonJobStore:
    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        safe = "".join(c for c in job_id if c.isalnum() or c in "-_.")
        if not safe or safe != job_id:
            raise ValueError("unsafe job id")
        return self.directory / f"{safe}.json"

    def save(self, job: Job) -> None:
        payload = {**asdict(job), "state": job.state.value}
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
            Artifact(**{**artifact, "parents": tuple(artifact.get("parents", ()))})
            for artifact in data.get("artifacts", [])
        ]
        data["evaluations"] = [Evaluation(**item) for item in data.get("evaluations", [])]
        return Job(**data)


class Orchestrator:
    """Durable stage machine with optional resumable external-operation receipts.

    Ordinary synchronous adapters keep the original ``execute(context)`` path.
    Adapters implementing ``ResumableAdapter`` use the same stage idempotency
    key but additionally persist prepared/accepted/result/committed handoff state.
    """

    def __init__(
        self,
        store: JsonJobStore,
        adapters: Mapping[JobStage, Adapter],
        evaluation_hooks: Sequence[EvaluationHook] = (),
        retry_policy: RetryPolicy | None = None,
        operation_ledger: JsonOperationLedger | None = None,
        operation_resume_policy: OperationResumePolicy | None = None,
        operation_boundary_hook: Callable[[str, OperationReceipt], None] | None = None,
    ) -> None:
        self.store = store
        self.adapters = dict(adapters)
        self.evaluation_hooks = tuple(evaluation_hooks)
        self.retry_policy = retry_policy or RetryPolicy()
        self.operation_ledger = operation_ledger or JsonOperationLedger(
            self.store.directory / "_operations"
        )
        self.operation_resume_policy = operation_resume_policy or OperationResumePolicy()
        self.operation_boundary_hook = operation_boundary_hook

    def create_job(
        self,
        job_id: str,
        topic: str,
        *,
        seed_artifacts: Sequence[SeedArtifactInput | Artifact] = (),
    ) -> Job:
        seeds: list[Artifact] = []
        for index, seed in enumerate(seed_artifacts):
            artifact = (
                seed
                if isinstance(seed, Artifact)
                else build_seed_artifact(job_id, seed, index)
            )
            if any(existing.id == artifact.id for existing in seeds):
                raise ValueError(f"duplicate seed artifact id: {artifact.id}")
            seeds.append(artifact)
        job = Job(id=job_id, topic=topic, artifacts=seeds)
        self.store.save(job)
        return job

    @staticmethod
    def _idempotency_key(job: Job, stage: JobStage) -> str:
        lineage = ",".join(a.id for a in job.artifacts)
        return hashlib.sha256(f"{job.id}|{stage.value}|{lineage}".encode()).hexdigest()

    def _boundary(self, name: str, receipt: OperationReceipt) -> None:
        if self.operation_boundary_hook is not None:
            self.operation_boundary_hook(name, receipt)

    def _reconcile_committed_receipts(self, job: Job) -> None:
        for stage_name, key in job.completed_idempotency_keys.items():
            if not self.operation_ledger.exists(job.id, stage_name, key):
                continue
            receipt = self.operation_ledger.load(job.id, stage_name, key)
            if receipt.state == OperationState.RESULT_OBTAINED:
                self.operation_ledger.mark_committed(receipt)

    def _execute_resumable(
        self,
        adapter: ResumableAdapter,
        context: StepContext,
    ) -> tuple[StepResult, OperationReceipt]:
        request = adapter.prepare(context)
        receipt = self.operation_ledger.prepare(
            job_id=context.job_id,
            stage=context.stage,
            idempotency_key=context.idempotency_key,
            adapter_name=adapter.name,
            request=request,
        )

        if receipt.state == OperationState.PREPARED:
            self._boundary("before_submit", receipt)
            acceptance = adapter.submit(context, receipt.request)
            self._boundary("after_submit_before_accept_persisted", receipt)
            receipt = self.operation_ledger.accept(receipt, acceptance)
            self._boundary("after_accept_persisted", receipt)

        if receipt.state == OperationState.ACCEPTED:
            if receipt.poll_attempts >= self.operation_resume_policy.max_poll_attempts:
                raise OperationPollingExhausted(
                    f"operation polling exhausted for {receipt.external_operation_id}"
                )
            receipt = self.operation_ledger.record_poll(receipt)
            poll = adapter.poll(context, receipt.external_operation_id or "")
            if not poll.done:
                raise OperationPending(
                    f"external operation pending: {receipt.external_operation_id}"
                )
            if poll.result is None:
                raise RuntimeError("completed external operation returned no StepResult")
            receipt = self.operation_ledger.record_result(
                receipt,
                poll.result,
                poll.metadata,
            )
            self._boundary("after_result_persisted", receipt)

        if receipt.state in (OperationState.RESULT_OBTAINED, OperationState.COMMITTED):
            if receipt.result is None:
                raise RuntimeError("durable operation receipt is missing its result")
            return receipt.result, receipt

        raise RuntimeError(f"unsupported operation receipt state: {receipt.state}")

    def request_revision(self, job_id: str, stage: JobStage) -> Job:
        target = STAGE_ORDER.index(stage)
        critic = STAGE_ORDER.index(JobStage.CRITIC)
        if target >= critic:
            raise RevisionError("revision target must be before critic")
        job = self.store.load(job_id)
        if job.stage_index < critic:
            raise RevisionError("revision may only be requested after critic execution")
        job.stage_index = target
        job.state = JobState.PENDING
        job.last_error = None
        job.touch()
        self.store.save(job)
        return job

    def run_next(self, job_id: str) -> Job:
        job = self.store.load(job_id)
        self._reconcile_committed_receipts(job)
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
        job.idempotency_attempts[key] = job.idempotency_attempts.get(key, 0) + 1
        logical_attempt = job.idempotency_attempts[key]
        job.touch()
        self.store.save(job)

        context = StepContext(
            job_id=job.id,
            topic=job.topic,
            stage=stage,
            idempotency_key=key,
            artifacts=tuple(job.artifacts),
            attempt=logical_attempt,
            stage_attempt=job.attempts[stage.value],
        )

        receipt: OperationReceipt | None = None
        try:
            if isinstance(adapter, ResumableAdapter):
                result, receipt = self._execute_resumable(adapter, context)
            else:
                result = adapter.execute(context)
        except OperationBoundaryCrash:
            raise
        except (OperationPending, OperationPollTimeout) as exc:
            job = self.store.load(job_id)
            job.last_error = f"{type(exc).__name__}: {exc}"
            job.state = JobState.WAITING_RETRY
            job.touch()
            self.store.save(job)
            return job
        except RetryableStepError as exc:
            job = self.store.load(job_id)
            job.last_error = str(exc)
            job.state = (
                JobState.FAILED
                if job.idempotency_attempts.get(key, 0) >= self.retry_policy.max_attempts
                else JobState.WAITING_RETRY
            )
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

        if receipt is not None:
            self._boundary("after_artifact_commit_before_receipt_commit", receipt)
            persisted = self.operation_ledger.load(job.id, stage.value, key)
            if persisted.state == OperationState.RESULT_OBTAINED:
                self.operation_ledger.mark_committed(persisted)
        return job

    def run_to_terminal(self, job_id: str) -> Job:
        while True:
            job = self.run_next(job_id)
            if job.state in (JobState.COMPLETE, JobState.FAILED, JobState.WAITING_RETRY):
                return job
