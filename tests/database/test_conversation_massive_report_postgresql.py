"""Synthetic long-recording proof from upload bytes through a saved report.

This deliberately uses generated silence and the local synthetic provider broker. It
does not call an external provider or use a customer recording. The 60-minute payload
stays below the configured 32 MiB upload ceiling while exercising the complete C1-C5
database pipeline.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from ac_platform.conversation_intelligence.checkpoints import SourceBinding
from ac_platform.conversation_intelligence.entitlements import ExecutionPermission, Quote
from ac_platform.conversation_intelligence.models import ConversationQuote
from tests.database import test_conversation_reporting_pipeline_postgresql as reporting
from tests.database import test_conversation_worker_postgresql as worker


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from worker._postgres_harness.__wrapped__()


def _sixty_minute_wav() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(4_000)
        block = b"\x00\x00" * 4_000
        for _ in range(3_600):
            stream.writeframes(block)
    return output.getvalue()


def test_sixty_minute_upload_reaches_saved_report(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _sixty_minute_wav()
    assert len(data) < 32 * 1024 * 1024
    monkeypatch.setattr(worker, "_wav_one_second_48k", lambda _duration_ms: data)

    original_seed_minutes = worker._seed_minutes

    async def seed_long_minutes(engine: Any, state: Any, *, seconds: int = 600) -> None:
        await original_seed_minutes(engine, state, seconds=7_200)

    monkeypatch.setattr(worker, "_seed_minutes", seed_long_minutes)

    async def add_long_quote(
        sessions: Any,
        state: Any,
        recording_id: UUID,
        scope_id: UUID,
        source_sha256: str,
        **kwargs: Any,
    ) -> UUID:
        quote_id = uuid4()
        current = kwargs.get("now") or state.now
        quoted = Quote(
            quote_id=str(quote_id),
            source=SourceBinding(str(state.tenant_id), str(recording_id), source_sha256, "1"),
            account_id=str(state.person_id),
            budget_scope_id=str(scope_id),
            provider_id="local",
            provider_model="audioatlas",
            recipe_revision=kwargs.get("recipe_revision", worker.AUDIOATLAS_RECIPE),
            operation="inspect_audioatlas",
            input_sha256=source_sha256,
            privacy_revision="synthetic-local-privacy-v1",
            permission_ref=str(state.permission_id),
            provider_terms_ref="native-source-license",
            retention_ref="delete-test-schema",
            professional_gate_ref="synthetic-fixture-only",
            pricing_ref="local-zero-price",
            entitlement_seconds=7_200,
            max_cost_paise=0,
            created_at_epoch=int(current.timestamp()) - 1,
            expires_at_epoch=int(current.timestamp()) + 3600,
        )
        permission = ExecutionPermission(
            "synthetic-sixty-minute-approval",
            quoted.fingerprint,
            "authorized-fixture-owner",
            int(current.timestamp()) + 3600,
        )
        async with sessions() as database, database.begin():
            database.add(
                ConversationQuote(
                    id=quote_id,
                    tenant_id=state.tenant_id,
                    person_id=state.person_id,
                    recording_id=recording_id,
                    budget_scope_id=scope_id,
                    quote=quoted.as_dict(),
                    execution_permission=permission.as_dict(),
                )
            )
        return quote_id

    monkeypatch.setattr(worker, "_add_quote", add_long_quote)
    # Production's hosted C1 adapter is the 16 kHz profile.  Keep this
    # end-to-end report fixture on that exact profile while retaining the
    # local recipe/ledger so it exercises the same durable C1→C5 path.
    original_worker = worker.OfflineConversationWorker

    class HostedProfileWorker(original_worker):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.c1_rate = 16_000

    monkeypatch.setattr(worker, "OfflineConversationWorker", HostedProfileWorker)
    failures: list[str] = []
    original_inspect = worker.inspect_media

    def traced_inspect(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return original_inspect(*args, **kwargs)
        except Exception as error:
            failures.append(f"{type(error).__name__}:{error}")
            raise

    monkeypatch.setattr(worker, "inspect_media", traced_inspect)
    try:
        reporting.test_saved_transcript_to_private_report_and_profile_reuse(
            postgres_harness, tmp_path, False, "groq", monkeypatch
        )
    except RuntimeError as error:
        assert failures, "C1 failed without a captured signal error"
        raise AssertionError(f"C1 signal failure: {failures}") from error
