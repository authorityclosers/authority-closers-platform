from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_v6_migration_only_widens_settings_checks_and_has_no_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[3]
    migration_path = root / "db/migrations/versions/20260925_0049_coaching_v6_selection.py"
    spec = importlib.util.spec_from_file_location("coaching_v6_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        migration,
        "op",
        SimpleNamespace(
            drop_constraint=lambda *args, **kwargs: calls.append(("drop", *args, kwargs)),
            create_check_constraint=lambda *args, **kwargs: calls.append(("create", *args, kwargs)),
        ),
    )
    migration.upgrade()

    assert migration.down_revision == "20260924_0048"
    assert [call[0] for call in calls] == ["drop", "create", "drop", "create"]
    assert calls[0] == (
        "drop",
        "known_c5_prompt",
        "conversation_analysis_settings",
        {"type_": "check"},
    )
    assert calls[2] == (
        "drop",
        "language_prompt_compatible",
        "conversation_analysis_settings",
        {"type_": "check"},
    )
    assert calls[1][1:3] == ("known_c5_prompt", "conversation_analysis_settings")
    assert calls[3][1:3] == ("language_prompt_compatible", "conversation_analysis_settings")
    assert "coaching-v6" in str(calls[1][3])
    assert "coaching-v6" in str(calls[3][3])
    assert "UPDATE" not in " ".join(map(str, calls)).upper()
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.downgrade()
