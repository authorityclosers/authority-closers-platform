"""Narrow operator CLI composition and failure-boundary checks."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from ac_platform.audit.models import AuditEvent
from ac_platform.catalog import cli
from ac_platform.catalog.models import ModulePrerequisite
from ac_platform.kernel.authz import ActorContext


def test_promote_uses_validated_studio_service_graph(monkeypatch) -> None:
    service = object()
    validated = []
    runtime = SimpleNamespace(
        studio_video_runtime=SimpleNamespace(
            service=service,
            validate=lambda: validated.append(True),
        ),
    )
    monkeypatch.setattr(cli, "create_default_media_runtime", lambda _settings: runtime)

    assert cli._configured_studio_service(object()) is service
    assert validated == [True]


def test_promote_refuses_missing_studio_filesystem_graph(monkeypatch) -> None:
    monkeypatch.setattr(
        cli,
        "create_default_media_runtime",
        lambda _settings: SimpleNamespace(studio_video_runtime=None),
    )

    try:
        cli._configured_studio_service(object())
    except cli.FreeCourseCliError as error:
        assert str(error) == "the configured Studio filesystem runtime is unavailable"
    else:  # pragma: no cover - assertion makes the refusal contract explicit
        raise AssertionError("missing Studio runtime was accepted")


def test_main_does_not_echo_secret_from_value_error(monkeypatch, capsys) -> None:
    canary = "session-secret-canary"

    def fail(coroutine):
        coroutine.close()
        raise ValueError(f"invalid settings: {canary}")

    monkeypatch.setattr(cli, "run_async", fail)
    result = cli.main(
        [
            "publish",
            "--environment",
            "test",
            "--source-program-id",
            str(uuid4()),
            "--public-tenant-id",
            str(uuid4()),
            "--command-id",
            str(uuid4()),
            "--reason",
            "test",
        ]
    )

    assert result == 2
    captured = capsys.readouterr()
    assert canary not in captured.err
    assert captured.err == ("free-course command refused: invalid or unavailable command input\n")


async def test_wire_prerequisite_uses_catalog_service_and_audits_edge(monkeypatch) -> None:
    tenant_id, program_id, version_id, module_id, prerequisite_id, command_id = (
        uuid4() for _ in range(6)
    )
    actor = ActorContext(uuid4(), uuid4(), tenant_id, frozenset())
    calls: list[dict[str, object]] = []

    class Database:
        async def get(self, model, key):
            assert model is AuditEvent
            assert key == command_id
            return None

    class Catalog:
        def __init__(self, _database):
            pass

        async def add_module_prerequisite(self, module, prerequisite, **kwargs):
            calls.append({"module": module, "prerequisite": prerequisite, **kwargs})
            return SimpleNamespace(
                id=cli._prerequisite_edge_id(
                    program_version_id=version_id,
                    module_id=module_id,
                    prerequisite_module_id=prerequisite_id,
                ),
                program_id=program_id,
                program_version_id=version_id,
                module_id=module_id,
                prerequisite_module_id=prerequisite_id,
                tenant_id=tenant_id,
            )

    audited: dict[str, object] = {}

    class Audit:
        def __init__(self, _database):
            pass

        async def append(self, **kwargs):
            audited.update(kwargs)
            return SimpleNamespace(id=command_id)

    monkeypatch.setattr(cli, "AsyncCatalogApplication", Catalog)
    monkeypatch.setattr(cli, "AuditRepository", Audit)
    result = await cli._wire_prerequisite(
        Database(),
        actor=actor,
        tenant_id=tenant_id,
        program_id=program_id,
        program_version_id=version_id,
        module_id=module_id,
        prerequisite_module_id=prerequisite_id,
        command_id=command_id,
        reason="reviewed source graph",
    )

    edge_id = cli._prerequisite_edge_id(
        program_version_id=version_id,
        module_id=module_id,
        prerequisite_module_id=prerequisite_id,
    )
    assert result == {
        "status": "applied",
        "command_id": str(command_id),
        "program_id": str(program_id),
        "program_version_id": str(version_id),
        "module_id": str(module_id),
        "prerequisite_module_id": str(prerequisite_id),
        "prerequisite_id": str(edge_id),
    }
    assert calls == [
        {
            "module": module_id,
            "prerequisite": prerequisite_id,
            "actor": actor,
            "tenant_id": tenant_id,
            "prerequisite_id": edge_id,
        }
    ]
    assert audited["event_id"] == command_id
    assert audited["actor_person_id"] == actor.person_id
    assert audited["resource_id"] == edge_id
    assert audited["reason"] == "reviewed source graph"


async def test_wire_prerequisite_replay_requires_matching_edge(monkeypatch) -> None:
    tenant_id, program_id, version_id, module_id, prerequisite_id, command_id = (
        uuid4() for _ in range(6)
    )
    actor = ActorContext(uuid4(), uuid4(), tenant_id, frozenset())
    edge_id = cli._prerequisite_edge_id(
        program_version_id=version_id,
        module_id=module_id,
        prerequisite_module_id=prerequisite_id,
    )
    payload = cli._prerequisite_payload(
        program_id=program_id,
        program_version_id=version_id,
        module_id=module_id,
        prerequisite_module_id=prerequisite_id,
        prerequisite_id=edge_id,
    )

    class Database:
        async def get(self, model, key):
            if model is AuditEvent:
                return SimpleNamespace(
                    tenant_id=tenant_id,
                    actor_person_id=actor.person_id,
                    action=cli._SOURCE_PREREQUISITE_ACTION,
                    resource_type="module_prerequisite",
                    resource_id=str(edge_id),
                    payload=payload,
                )
            assert model is ModulePrerequisite
            assert key == edge_id
            return SimpleNamespace(
                program_id=program_id,
                program_version_id=version_id,
                module_id=module_id,
                prerequisite_module_id=prerequisite_id,
                tenant_id=tenant_id,
            )

    class NeverCatalog:
        def __init__(self, _database):
            raise AssertionError("replay must not call the catalog writer")

    monkeypatch.setattr(cli, "AsyncCatalogApplication", NeverCatalog)
    result = await cli._wire_prerequisite(
        Database(),
        actor=actor,
        tenant_id=tenant_id,
        program_id=program_id,
        program_version_id=version_id,
        module_id=module_id,
        prerequisite_module_id=prerequisite_id,
        command_id=command_id,
        reason="reviewed source graph",
    )

    assert result["status"] == "replayed"
    assert result["prerequisite_id"] == str(edge_id)
