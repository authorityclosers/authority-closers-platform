"""Focused contract tests for the inert intelligence harness."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ac_platform.intelligence import (
    AbstainOutcome,
    AnswerOutcome,
    BudgetExceededError,
    Citation,
    DeadlineExceededError,
    EscalateOutcome,
    EvidenceItem,
    GenerationRequest,
    GenerationResult,
    IntelligenceOrchestrator,
    IntelligencePurpose,
    IntelligenceValidationError,
    ModelProfile,
    PolicyDeniedError,
    ProviderResultError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ToolsDeniedError,
    Usage,
    outcome_digest,
)

TENANT_ID = uuid4()
ACTOR_ID = uuid4()


def profile(**overrides: object) -> ModelProfile:
    values: dict[str, object] = {
        "profile_id": "local-qwen35-4b-q4",
        "provider": "llama.cpp",
        "model": "Qwen3.5-4B",
        "revision": "sha256:model-placeholder",
        "runtime": "sha256:runtime-placeholder",
    }
    values.update(overrides)
    return ModelProfile(**values)  # type: ignore[arg-type]


def request(**overrides: object) -> GenerationRequest:
    values: dict[str, object] = {
        "request_id": uuid4(),
        "tenant_id": TENANT_ID,
        "actor_id": ACTOR_ID,
        "purpose": IntelligencePurpose.SUPPORT_ASSISTANCE,
        "question": "How do I update my course access?",
        "deadline": datetime.now(UTC) + timedelta(seconds=2),
    }
    values.update(overrides)
    return GenerationRequest(**values)  # type: ignore[arg-type]


class FakePort:
    def __init__(
        self,
        result: GenerationResult | None = None,
        *,
        wait_forever: bool = False,
    ) -> None:
        self.result = result
        self.wait_forever = wait_forever
        self.calls: list[tuple[GenerationRequest, ModelProfile]] = []

    async def generate(self, request: GenerationRequest, profile: ModelProfile) -> GenerationResult:
        self.calls.append((request, profile))
        if self.wait_forever:
            await asyncio.Event().wait()
        assert self.result is not None
        return self.result


class NonContractPort:
    async def generate(
        self,
        request: GenerationRequest,
        profile: ModelProfile,
    ) -> GenerationResult:
        del request, profile
        return object()  # type: ignore[return-value]


class FailingPort:
    async def generate(
        self,
        request: GenerationRequest,
        profile: ModelProfile,
    ) -> GenerationResult:
        del request, profile
        raise RuntimeError("adapter exploded")


class CancellationSuppressingPort:
    def __init__(self, result: GenerationResult) -> None:
        self.result = result

    async def generate(self, request: GenerationRequest, profile: ModelProfile) -> GenerationResult:
        del request, profile
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(0.02)
            return self.result
        raise AssertionError("the cancellation path was not exercised")


class CancellationIgnoringPort:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.started = asyncio.Event()
        self.task: asyncio.Task[GenerationResult] | None = None

    async def generate(self, request: GenerationRequest, profile: ModelProfile) -> GenerationResult:
        del profile
        current = asyncio.current_task()
        assert current is not None
        self.task = current  # type: ignore[assignment]
        self.started.set()
        while not self.release.is_set():
            try:
                await asyncio.sleep(0.001)
            except asyncio.CancelledError:
                continue
        raise RuntimeError("quarantined provider terminated")


def result_for(
    req: GenerationRequest,
    outcome: AnswerOutcome | AbstainOutcome | EscalateOutcome,
) -> GenerationResult:
    return GenerationResult(
        request_id=req.request_id,
        profile_id="local-qwen35-4b-q4",
        outcome=outcome,
        usage=Usage(input_tokens=42, output_tokens=24),
    )


def test_request_bounds_and_tool_policy() -> None:
    with pytest.raises(IntelligenceValidationError):
        request(question=" ")
    with pytest.raises(IntelligenceValidationError):
        request(question="x" * 4_001)
    with pytest.raises(ToolsDeniedError):
        request(tool_names=("lookup_account",))
    with pytest.raises(IntelligenceValidationError):
        request(deadline=datetime.now())


def test_evidence_and_citations_are_bounded_and_deduplicated() -> None:
    evidence = EvidenceItem(
        source_id="course-policy",
        passage="Access is granted after enrollment.",
    )
    assert evidence.locator is None
    with pytest.raises(IntelligenceValidationError):
        AnswerOutcome(
            answer="Read the policy.",
            citations=(Citation("policy", "p1"), Citation("policy", "p1")),
        )


@pytest.mark.parametrize(
    "outcome",
    [
        AnswerOutcome("The policy says to contact support.", (Citation("policy", "p1"),)),
        AbstainOutcome("The evidence does not establish the account state.", ("account state",)),
        EscalateOutcome("A human must verify the request.", "support-review"),
    ],
)
async def test_orchestrator_returns_typed_advisory_outcomes(outcome: object) -> None:
    evidence = (
        EvidenceItem(
            source_id="policy",
            passage="The policy says to contact support.",
            locator="p1",
        ),
    )
    req = request(evidence=evidence) if isinstance(outcome, AnswerOutcome) else request()
    port = FakePort(result=result_for(req, outcome))  # type: ignore[arg-type]
    response = await IntelligenceOrchestrator(port, profile()).generate(req)

    assert response.advisory is True
    assert response.outcome is outcome
    assert response.execution.request_id == req.request_id
    assert len(response.execution.output_digest) == 64
    assert port.calls == [(req, profile())]


async def test_orchestrator_rejects_non_support_purpose() -> None:
    req = request(purpose="sales_simulation")  # type: ignore[arg-type]
    port = FakePort()
    with pytest.raises(PolicyDeniedError):
        await IntelligenceOrchestrator(port, profile()).generate(req)
    assert not port.calls


async def test_orchestrator_rejects_mismatched_provider_result() -> None:
    req = request()
    mismatched = GenerationResult(
        request_id=uuid4(),
        profile_id="local-qwen35-4b-q4",
        outcome=AnswerOutcome("untrusted"),
    )
    with pytest.raises(ProviderResultError):
        await IntelligenceOrchestrator(FakePort(mismatched), profile()).generate(req)


async def test_orchestrator_rejects_a_non_contract_provider_result() -> None:
    with pytest.raises(ProviderResultError):
        await IntelligenceOrchestrator(NonContractPort(), profile()).generate(request())


async def test_orchestrator_normalizes_unexpected_provider_errors() -> None:
    with pytest.raises(ProviderUnavailableError):
        await IntelligenceOrchestrator(FailingPort(), profile()).generate(request())


async def test_orchestrator_times_out_without_synthesizing_an_answer() -> None:
    req = request(deadline=datetime.now(UTC) + timedelta(milliseconds=10))
    port = FakePort(wait_forever=True)
    with pytest.raises(ProviderTimeoutError):
        await IntelligenceOrchestrator(port, profile()).generate(req)


async def test_orchestrator_rejects_a_late_result_after_cancel_suppression() -> None:
    req = request(deadline=datetime.now(UTC) + timedelta(milliseconds=10))
    late_result = result_for(req, AnswerOutcome("late"))
    with pytest.raises(ProviderTimeoutError):
        await IntelligenceOrchestrator(
            CancellationSuppressingPort(late_result),
            profile(),
        ).generate(req)


async def test_orchestrator_returns_at_deadline_when_provider_ignores_cancel() -> None:
    req = request(deadline=datetime.now(UTC) + timedelta(milliseconds=10))
    port = CancellationIgnoringPort()
    generation = asyncio.create_task(IntelligenceOrchestrator(port, profile()).generate(req))
    started_at = time.monotonic()
    try:
        # If scheduling consumes the short request deadline, the orchestrator
        # correctly refuses before entering the provider. Fail this sample
        # within a bound instead of waiting forever for an impossible start.
        await asyncio.wait_for(port.started.wait(), timeout=0.2)
        with pytest.raises(ProviderTimeoutError):
            await asyncio.wait_for(generation, timeout=0.2)
        assert time.monotonic() - started_at < 0.2
    finally:
        port.release.set()
        if port.task is not None and not port.task.done():
            with suppress(RuntimeError):
                await asyncio.wait_for(asyncio.shield(port.task), timeout=0.2)
        if not generation.done():
            generation.cancel()
        await asyncio.gather(generation, return_exceptions=True)


async def test_elapsed_deadline_is_rejected_before_provider_call() -> None:
    req = request(deadline=datetime.now(UTC) - timedelta(seconds=1))
    port = FakePort()
    with pytest.raises(DeadlineExceededError):
        await IntelligenceOrchestrator(port, profile()).generate(req)
    assert not port.calls


def test_tools_cannot_be_enabled_by_a_model_profile() -> None:
    with pytest.raises(ToolsDeniedError):
        profile(tools_enabled=True)


def test_sequences_are_copied_to_immutable_tuples() -> None:
    evidence = EvidenceItem(source_id="policy", passage="Policy text.")
    evidence_values = [evidence]
    tool_name_values: list[str] = []
    request_value = request(evidence=evidence_values, tool_names=tool_name_values)
    evidence_values.clear()
    tool_name_values.append("lookup")
    assert request_value.evidence == (evidence,)
    assert request_value.tool_names == ()

    citation = Citation("policy", "p1")
    citations = [citation]
    answer = AnswerOutcome("answer", citations)
    citations.clear()
    assert answer.citations == (citation,)

    missing = ["account state"]
    abstain = AbstainOutcome("unknown", missing)
    missing.clear()
    assert abstain.missing_evidence == ("account state",)

    tool_calls: list[str] = []
    result = GenerationResult(
        request_id=uuid4(),
        profile_id="p",
        outcome=answer,
        tool_calls=tool_calls,
    )
    tool_calls.append("unexpected")
    assert result.tool_calls == ()


def test_uuid_and_usage_types_are_strict() -> None:
    with pytest.raises(IntelligenceValidationError):
        request(request_id="not-a-uuid")  # type: ignore[arg-type]
    with pytest.raises(IntelligenceValidationError):
        request(tenant_id="not-a-uuid")  # type: ignore[arg-type]
    with pytest.raises(IntelligenceValidationError):
        request(actor_id="not-a-uuid")  # type: ignore[arg-type]
    with pytest.raises(IntelligenceValidationError):
        Usage(input_tokens=True)
    with pytest.raises(IntelligenceValidationError):
        Usage(output_tokens=1.5)  # type: ignore[arg-type]
    with pytest.raises(IntelligenceValidationError):
        Usage(input_tokens=-1)


async def test_provider_usage_must_fit_both_request_and_profile_budgets() -> None:
    req = request(output_tokens=1)
    over_output = GenerationResult(
        request_id=req.request_id,
        profile_id="local-qwen35-4b-q4",
        outcome=AnswerOutcome("answer"),
        usage=Usage(input_tokens=1, output_tokens=8),
    )
    with pytest.raises(BudgetExceededError):
        await IntelligenceOrchestrator(FakePort(over_output), profile()).generate(req)

    input_req = request()
    over_input = GenerationResult(
        request_id=input_req.request_id,
        profile_id="local-qwen35-4b-q4",
        outcome=AnswerOutcome("answer"),
        usage=Usage(input_tokens=1_000_000_000, output_tokens=1),
    )
    with pytest.raises(BudgetExceededError):
        await IntelligenceOrchestrator(
            FakePort(over_input),
            profile(max_input_tokens=100),
        ).generate(input_req)

    with pytest.raises(BudgetExceededError):
        await IntelligenceOrchestrator(
            FakePort(),
            profile(max_output_tokens=4),
        ).generate(request(output_tokens=8))


@pytest.mark.parametrize(
    "evidence, citation",
    [
        ((), Citation("policy", "p1")),
        ((EvidenceItem("other", "Policy text.", "p1"),), Citation("policy", "p1")),
        ((EvidenceItem("policy", "Policy text.", "p1"),), Citation("policy", "p2")),
        ((EvidenceItem("policy", "Policy text."),), Citation("policy", "p1")),
        (
            (EvidenceItem("policy", "Policy text.", "p1"),),
            Citation("policy", "p1", "invented"),
        ),
        (
            (
                EvidenceItem("policy", "First passage.", "p1"),
                EvidenceItem("policy", "Second passage.", "p2"),
            ),
            Citation("policy", "p1"),
        ),
    ],
)
async def test_answer_citations_must_ground_in_unambiguous_request_evidence(
    evidence: tuple[EvidenceItem, ...],
    citation: Citation,
) -> None:
    req = request(evidence=evidence)
    result = result_for(req, AnswerOutcome("answer", (citation,)))
    with pytest.raises(ProviderResultError):
        await IntelligenceOrchestrator(FakePort(result), profile()).generate(req)


async def test_provider_result_mutation_is_revalidated_at_the_boundary() -> None:
    evidence = EvidenceItem("policy", "Policy text.", "p1")
    req = request(evidence=(evidence,))
    outcome = AnswerOutcome("answer", (Citation("policy", "p1", "Policy"),))
    result = result_for(req, outcome)
    object.__setattr__(result, "tool_calls", ["write_access"])
    with pytest.raises(ProviderResultError):
        await IntelligenceOrchestrator(FakePort(result), profile()).generate(req)

    clean_result = result_for(req, outcome)
    object.__setattr__(outcome, "citations", [Citation("policy", "p1", "forged")])
    with pytest.raises(ProviderResultError):
        await IntelligenceOrchestrator(FakePort(clean_result), profile()).generate(req)


def test_digest_is_stable_and_does_not_require_raw_prompt() -> None:
    first = outcome_digest(AnswerOutcome("same", (Citation("source", "line 1"),)))
    second = outcome_digest(AnswerOutcome("same", (Citation("source", "line 1"),)))
    assert first == second
