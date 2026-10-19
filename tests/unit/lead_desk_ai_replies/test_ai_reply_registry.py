"""AI replies' model: off until Root clears the gate and the key is there, under a daily cap."""

import asyncio
import json
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from ac_platform.call_data import provider as text_models
from ac_platform.call_data import settings as model_menu
from ac_platform.lead_desk.ai_replies import registry, service

KEYED = {"GEMINI_API_KEY": "fixture-key", "AC_LEAD_DESK_AI_DAILY_CAP_INR": "50"}


def gate(tmp_path: Path, cleared: list[str] | None) -> Path:
    path = tmp_path / "gate.json"
    if cleared is not None:
        path.write_text(json.dumps({"cleared": cleared}))
    return path


class Sessions:
    """A session maker whose database says how much was spent today."""

    def __init__(self, spent: Decimal) -> None:
        self.spent = spent

    @asynccontextmanager
    async def __call__(self) -> Any:
        spent = self.spent

        class Db:
            async def scalar(self, query: Any) -> Decimal:
                return spent

        yield Db()


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


def model(
    tmp_path: Path,
    client: Client,
    *,
    cleared: list[str] | None,
    env: dict[str, str],
    spent: str = "0",
) -> registry.GatedModel:
    return registry.GatedModel(
        Sessions(Decimal(spent)),  # type: ignore[arg-type]
        client=lambda: client,
        path=gate(tmp_path, cleared),
        env=env,
    )


def ask(gated: registry.GatedModel) -> service.Completion:
    return asyncio.run(gated.complete(tenant_id=uuid4(), system="s", user="u"))


def test_off_until_the_gate_is_cleared_and_the_key_is_there(tmp_path: Path) -> None:
    client = Client()
    for cleared, env, why in (
        (None, KEYED, "gate"),
        ([], KEYED, "gate"),
        (["deepgram"], KEYED, "gate"),
        (["gemini"], {}, "key"),
    ):
        path = gate(tmp_path, cleared)
        assert registry.available(path=path, env=env) == (False, why)
        with pytest.raises(service.ModelUnavailable) as stopped:
            ask(model(tmp_path, client, cleared=cleared, env=env))
        assert stopped.value.reason == "off"
    assert client.calls == []  # nothing was sent anywhere
    assert registry.available(path=gate(tmp_path, ["gemini"]), env=KEYED) == (True, None)


def test_the_answer_with_its_tokens_and_list_price_cost(tmp_path: Path) -> None:
    client = Client()
    done = ask(model(tmp_path, client, cleared=["gemini"], env=KEYED))
    name = registry.model_name(KEYED)
    assert model_menu.MODELS[name].provider == "gemini"
    assert json.loads(done.text) == {"reply": "Yes.", "handoff": False, "reason": "ok"}
    assert (done.provider, done.model, done.input_tokens, done.output_tokens) == (
        "gemini",
        name,
        1000,
        50,
    )
    assert done.cost_inr == model_menu.cost_inr(name, 1000, 50)
    assert client.calls[0]["schema"] == registry.SCHEMA
    assert client.calls[0]["system"] == "s" and client.calls[0]["user"] == "u"


def test_the_daily_cap_pauses_replies(tmp_path: Path) -> None:
    client = Client()
    with pytest.raises(service.ModelUnavailable) as stopped:
        ask(model(tmp_path, client, cleared=["gemini"], env=KEYED, spent="50"))
    assert stopped.value.reason == "budget" and client.calls == []
    assert registry.daily_cap({}) == Decimal("100")
    assert registry.daily_cap({"AC_LEAD_DESK_AI_DAILY_CAP_INR": "x"}) == Decimal("100")
    assert registry.daily_cap({"AC_LEAD_DESK_AI_DAILY_CAP_INR": "-5"}) == Decimal("0")


def test_a_provider_failure_is_a_plain_failure(tmp_path: Path) -> None:
    with pytest.raises(service.ModelUnavailable) as stopped:
        ask(model(tmp_path, Client(failure="timeout"), cleared=["gemini"], env=KEYED))
    assert (stopped.value.reason, str(stopped.value)) == ("failed", "timeout")


def test_only_a_model_from_the_menu_is_used() -> None:
    other = next(iter(model_menu.MODELS))
    assert registry.model_name({"AC_LEAD_DESK_AI_MODEL": other}) == other
    assert registry.model_name({"AC_LEAD_DESK_AI_MODEL": "made-up-model"}) == registry.model_name(
        {}
    )
