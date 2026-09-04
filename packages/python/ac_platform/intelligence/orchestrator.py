"""Fail-closed orchestration for advisory intelligence generation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from uuid import uuid4

from ac_platform.intelligence.contracts import (
    AnswerOutcome,
    ExecutionRecord,
    GenerationPort,
    GenerationRequest,
    GenerationResult,
    IntelligencePurpose,
    IntelligenceResponse,
    ModelProfile,
    outcome_digest,
    validate_answer_grounding,
    validate_generation_request,
    validate_generation_result,
)
from ac_platform.intelligence.errors import (
    BudgetExceededError,
    DeadlineExceededError,
    IntelligenceValidationError,
    PolicyDeniedError,
    ProviderResultError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ToolsDeniedError,
)


class IntelligenceOrchestrator:
    """Coordinate one bounded provider call with no tools or side effects."""

    def __init__(
        self,
        port: GenerationPort,
        profile: ModelProfile,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._port = port
        self._profile = profile
        self._clock = clock or (lambda: datetime.now(UTC))
        self._quarantined_tasks: set[asyncio.Task[GenerationResult]] = set()

    async def generate(self, request: GenerationRequest) -> IntelligenceResponse:
        """Generate one advisory response or fail closed with a typed error."""

        self._validate_request(request)
        started_at = self._clock().astimezone(UTC)
        remaining = request.remaining_seconds(started_at)
        if remaining <= 0:
            raise DeadlineExceededError("generation request deadline has elapsed")

        task = asyncio.create_task(self._port.generate(request, self._profile))
        try:
            _, pending = await asyncio.wait((task,), timeout=remaining)
        except asyncio.CancelledError:
            self._quarantine(task)
            raise
        if pending:
            self._quarantine(task)
            raise ProviderTimeoutError("provider did not finish before the request deadline")

        try:
            result = task.result()
        except asyncio.CancelledError:
            raise
        except ProviderUnavailableError:
            raise
        except IntelligenceValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize adapter failures at the boundary
            raise ProviderUnavailableError(
                "provider adapter failed before a trusted result"
            ) from exc

        completed_at = self._clock().astimezone(UTC)
        if completed_at > request.deadline:
            raise DeadlineExceededError("provider result completed after the request deadline")
        self._validate_result(request, result)
        execution = ExecutionRecord(
            execution_id=uuid4(),
            request_id=request.request_id,
            profile_id=self._profile.profile_id,
            started_at=started_at,
            completed_at=completed_at,
            output_digest=outcome_digest(result.outcome),
        )
        return IntelligenceResponse(outcome=result.outcome, execution=execution)

    def _validate_request(self, request: GenerationRequest) -> None:
        validate_generation_request(request)
        if request.purpose is not IntelligencePurpose.SUPPORT_ASSISTANCE:
            raise PolicyDeniedError("the Phase-1 harness admits support assistance only")
        if request.output_tokens > self._profile.max_output_tokens:
            raise BudgetExceededError("request output budget exceeds the model profile")
        if request.tool_names or self._profile.tools_enabled:
            raise PolicyDeniedError("tools are disabled for the Phase-1 harness")

    def _validate_result(self, request: GenerationRequest, result: GenerationResult) -> None:
        try:
            validate_generation_result(result)
        except Exception as exc:  # noqa: BLE001 - provider data must fail closed
            if isinstance(exc, (ProviderResultError, ToolsDeniedError)):
                raise
            raise ProviderResultError("provider result failed contract validation") from exc
        if result.request_id != request.request_id:
            raise ProviderResultError("provider result request_id does not match the request")
        if result.profile_id != self._profile.profile_id:
            raise ProviderResultError(
                "provider result profile_id does not match the selected profile"
            )
        if result.usage.input_tokens > self._profile.max_input_tokens:
            raise BudgetExceededError("provider input usage exceeds the model profile budget")
        if result.usage.output_tokens > request.output_tokens:
            raise BudgetExceededError("provider output usage exceeds the request budget")
        if result.usage.output_tokens > self._profile.max_output_tokens:
            raise BudgetExceededError("provider output usage exceeds the model profile budget")
        if isinstance(result.outcome, AnswerOutcome):
            try:
                validate_answer_grounding(result.outcome, request.evidence)
            except Exception as exc:  # noqa: BLE001 - citation data must fail closed
                raise ProviderResultError("provider citations failed evidence grounding") from exc

    def _quarantine(self, task: asyncio.Task[GenerationResult]) -> None:
        """Cancel a late provider and consume its eventual terminal state."""

        self._quarantined_tasks.add(task)
        task.cancel()
        task.add_done_callback(self._consume_quarantined)

    def _consume_quarantined(self, task: asyncio.Task[GenerationResult]) -> None:
        self._quarantined_tasks.discard(task)
        if not task.cancelled():
            with suppress(BaseException):
                task.exception()


__all__ = ["IntelligenceOrchestrator"]
