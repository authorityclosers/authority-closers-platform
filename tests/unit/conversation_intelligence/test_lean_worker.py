import asyncio
from pathlib import Path

import pytest

from ac_platform.conversation_intelligence.lean_native_runtime import LeanDockerNativeRuntime
from ac_platform.conversation_intelligence.lean_service import cap_consumers
from ac_platform.conversation_intelligence.native_runtime import (
    NativeRuntimeError,
)
from ac_platform.conversation_intelligence.runner import PipelinedConversationWorkerRunner
from ac_platform.conversation_intelligence.service_config import WorkerServiceConfig
from ac_platform.worker import DurableWorker, WorkerRunResult


@pytest.mark.parametrize("manifest,requested,expected", [(8, 1, 1), (8, 2, 2), (1, 2, 1)])
def test_lean_cap_never_expands_manifest(manifest: int, requested: int, expected: int) -> None:
    config = WorkerServiceConfig.model_construct(provider_consumers=manifest)
    assert cap_consumers(config, requested) == expected


@pytest.mark.parametrize("requested", [0, 3, 8, True])
def test_lean_refuses_unbounded_provider_concurrency(requested: int) -> None:
    with pytest.raises(ValueError):
        cap_consumers(WorkerServiceConfig.model_construct(provider_consumers=8), requested)


class Step:
    async def step(self) -> bool:
        return False

    async def run_once(self) -> bool:
        return False


async def test_recycle_drains_accepted_stages_before_return() -> None:
    started, release = asyncio.Event(), asyncio.Event()

    class Inference(Step):
        async def run_once(self) -> bool:
            started.set()
            await release.wait()
            return True

    class Offline(Step):
        async def run_once(self) -> bool:
            await started.wait()
            release.set()
            return True

    stop = asyncio.Event()
    runner = PipelinedConversationWorkerRunner(
        Step(),
        Offline(),
        Step(),
        Inference(),
        provider_consumers=1,
        max_jobs=1,
    )
    summary = await asyncio.wait_for(runner.run(stop), timeout=1)
    assert stop.is_set()
    assert summary.offline_work == summary.inference_work == 1


async def test_background_admission_waits_before_any_stage() -> None:
    calls = []

    async def refuse(stop: asyncio.Event) -> bool:
        calls.append("gate")
        return False

    class Forbidden(Step):
        async def step(self) -> bool:
            pytest.fail("no background stage should run")

    runner = PipelinedConversationWorkerRunner(
        Forbidden(),
        Step(),
        Step(),
        Step(),
        admission=refuse,
    )
    await runner.run(asyncio.Event())
    assert calls == ["gate"]


async def test_core_recycles_after_exact_job_count(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = object.__new__(DurableWorker)
    worker._poll_interval = 0
    counts = []

    async def prepare() -> bool:
        return True

    async def run_once(*, max_jobs: int) -> WorkerRunResult:
        counts.append(max_jobs)
        return WorkerRunResult(claimed=min(2, max_jobs))

    worker.prepare, worker.run_once = prepare, run_once
    monkeypatch.setenv("AC_WORKER_MAX_JOBS", "3")
    stop = asyncio.Event()
    await worker.run(stop_event=stop)
    assert counts == [3, 1] and stop.is_set()


def test_native_child_joins_combined_cgroup_and_has_hard_cap(tmp_path: Path) -> None:
    runtime = LeanDockerNativeRuntime(
        "sha256:" + "a" * 64,
        workspace_root=tmp_path,
        memory_mib=192,
        cgroup_parent="native.slice",
    )
    command = runtime._command(
        tmp_path / "source", tmp_path / "out", "fictional", operation="inspect"
    )
    assert "--memory=192m" in command and "--memory-swap=192m" in command
    assert "--cgroup-parent=native.slice" in command and "--oom-score-adj=500" in command


@pytest.mark.parametrize("parent", ["/prod", "../native.slice", "native.slice --privileged", ""])
def test_native_rejects_unbounded_parent(tmp_path: Path, parent: str) -> None:
    with pytest.raises(NativeRuntimeError):
        LeanDockerNativeRuntime("sha256:" + "a" * 64, workspace_root=tmp_path, cgroup_parent=parent)
