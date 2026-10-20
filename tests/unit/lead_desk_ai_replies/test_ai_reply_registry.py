"""AI replies' model and Admin settings: chosen in Admin, the key only in the runner."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from ac_platform.call_data import provider as text_models
from ac_platform.call_data import settings as model_menu
from ac_platform.lead_desk.ai_replies import admin_settings, registry, service

PACKAGE = Path(registry.__file__).parent


class Client:
    def __init__(self, answer: Any = None, failure: str | None = None) -> None:
        self.answer, self.failure = answer, failure
        self.calls: list[dict[str, Any]] = []

    def generate_json(self, **kwargs: Any) -> text_models.Answer:
        self.calls.append(kwargs)
        if self.failure:
            raise text_models.ProviderFailure(self.failure)
        return text_models.Answer(
            value=self.answer or {"reply": "Yes.", "handoff": False, "reason": "ok"},
            usage={"promptTokenCount": 1000, "candidatesTokenCount": 40, "thoughtsTokenCount": 10},
        )


def ask(model: registry.ProviderModel) -> service.Completion:
    return asyncio.run(model.complete(tenant_id=uuid4(), system="s", user="u"))


def test_the_answer_with_its_tokens_and_list_price_cost() -> None:
    client = Client()
    other = [name for name, item in model_menu.MODELS.items() if item.provider == "gemini"][-1]
    done = ask(
        registry.ProviderModel({"provider": "gemini", "model": other}, client=lambda: client)
    )
    assert json.loads(done.text) == {"reply": "Yes.", "handoff": False, "reason": "ok"}
    assert (done.provider, done.model, done.input_tokens, done.output_tokens) == (
        "gemini",
        other,
        1000,
        50,  # thinking tokens are billed as output
    )
    assert done.cost_inr == model_menu.cost_inr(other, 1000, 50)
    assert client.calls[0]["schema"] == registry.SCHEMA
    assert client.calls[0]["system"] == "s" and client.calls[0]["user"] == "u"
    assert client.calls[0]["model"] == other


def test_a_provider_failure_is_a_plain_failure() -> None:
    with pytest.raises(service.ModelUnavailable) as stopped:
        ask(registry.ProviderModel({}, client=lambda: Client(failure="timeout")))
    assert (stopped.value.reason, str(stopped.value)) == ("failed", "timeout")


def test_only_a_model_from_the_menu_is_used() -> None:
    assert registry.model_name({"model": "made-up-model"}) == admin_settings.DEFAULTS["model"]
    assert model_menu.MODELS[registry.model_name({})].provider == "gemini"


def test_settings_start_off_and_are_checked() -> None:
    assert admin_settings.DEFAULTS["enabled"] is False
    assert (admin_settings.DEFAULTS["cap_inr"], admin_settings.DEFAULTS["period"]) == (
        100,
        "daily",
    )
    assert admin_settings.validate({"enabled": True, "cap_inr": 300, "period": "monthly"}) == {
        **admin_settings.DEFAULTS,
        "enabled": True,
        "cap_inr": 300,
        "period": "monthly",
    }
    for bad, code in (
        ({"enabled": "yes"}, "enabled"),
        ({"provider": "elsewhere"}, "provider"),
        ({"model": "made-up-model"}, "model"),
        ({"cap_inr": -1}, "cap_inr"),
        ({"cap_inr": True}, "cap_inr"),
        ({"cap_inr": 12.5}, "cap_inr"),
        ({"cap_inr": admin_settings.MAX_CAP + 1}, "cap_inr"),
        ({"period": "weekly"}, "period"),
    ):
        with pytest.raises(admin_settings.SettingsError) as error:
            admin_settings.validate(bad)
        assert error.value.code == code
    # Keys Admin doesn't know are dropped, not stored.
    assert "key" not in admin_settings.validate({"key": "anything"})


def test_one_click_raise_and_the_periods() -> None:
    assert [admin_settings.raise_to(cap) for cap in (0, 100, 300, 400, 950)] == [
        100,
        300,
        400,
        500,
        1050,
    ]
    assert admin_settings.raise_to(admin_settings.MAX_CAP) == admin_settings.MAX_CAP
    now = datetime(2026, 10, 20, 15, 30, tzinfo=UTC)
    assert admin_settings.period_start("daily", now) == datetime(2026, 10, 20, tzinfo=UTC)
    assert admin_settings.period_start("monthly", now) == datetime(2026, 10, 1, tzinfo=UTC)
    assert admin_settings.period_start("lifetime", now) is None
    assert [admin_settings.period_key(p, now) for p in admin_settings.PERIODS] == [
        "2026-10-20",
        "2026-10",
        "lifetime",
    ]


def test_the_api_never_holds_a_model_key() -> None:
    """Owner rule: no provider key in the API's environment and no Root-only gate file.
    Only the runner (inside ``infisical run``) builds the provider's model."""
    for path in PACKAGE.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "GEMINI_API_KEY" not in source, path.name
        assert "gate_file" not in source.casefold() and "gate.json" not in source, path.name
        if path.name not in {"cli.py", "registry.py"}:
            assert "ProviderModel(" not in source, path.name
            assert "call_data.provider" not in source, path.name
