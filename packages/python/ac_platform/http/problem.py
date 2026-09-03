from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from ac_platform.kernel.errors import DomainError


class ProblemDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    request_id: str


def problem_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    title: str,
    detail: str,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unavailable")
    problem = ProblemDetails(
        type=f"https://authorityclosers.com/problems/{code.replace('_', '-')}",
        title=title,
        status=status_code,
        detail=detail,
        instance=request.url.path,
        code=code,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=status_code,
        content=problem.model_dump(mode="json"),
        media_type="application/problem+json",
    )


async def domain_error_handler(request: Request, error: DomainError) -> JSONResponse:
    return problem_response(
        request=request,
        status_code=error.status,
        code=error.code,
        title=error.title,
        detail=error.detail,
    )


def register_problem_handlers(application: Any) -> None:
    application.add_exception_handler(DomainError, domain_error_handler)
