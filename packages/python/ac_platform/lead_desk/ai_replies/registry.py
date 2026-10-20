"""The model behind AI replies: the provider and model chosen in Admin.

Only the AI replies runner (``ai_replies.cli``) asks the model, and only inside
``infisical run`` with the worker's provider launcher, exactly as the call data engine
does: the key exists in that child process and nowhere else. The API never holds a
model key; it queues work and acts on the runner's answers.

The client and price list are the call data engine's (``call_data.provider``,
``call_data.settings``): Gemini with JSON output, list-price cost from tokens.
Nothing here logs prompts or answers.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from typing import Any, Final
from uuid import UUID

from ac_platform.call_data import provider as text_models
from ac_platform.call_data import settings as model_menu
from ac_platform.lead_desk.ai_replies import admin_settings
from ac_platform.lead_desk.ai_replies.service import Completion, ModelUnavailable

SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "handoff": {"type": "boolean"},
        "reason": {
            "type": "string",
            "enum": ["ok", "human", "complaint", "price", "discount", "unsure", "off_topic"],
        },
    },
    "required": ["reply", "handoff", "reason"],
}


def model_name(config: Mapping[str, Any]) -> str:
    """The model Admin chose, from the call data menu (its first model otherwise)."""
    try:
        return str(admin_settings.validate(config)["model"])
    except admin_settings.SettingsError:
        return str(admin_settings.DEFAULTS["model"])


class ProviderModel:
    """The chosen provider's model, asked from inside the runner's ``infisical`` child."""

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        client: Callable[[], text_models.TextModel] = text_models.Gemini,
    ) -> None:
        self.provider = str(config.get("provider") or "gemini")
        self.model = model_name(config)
        self.client = client

    async def complete(self, *, tenant_id: UUID, system: str, user: str) -> Completion:
        if self.provider != "gemini":
            raise ModelUnavailable("failed", "provider_unsupported")
        try:
            answer = await asyncio.to_thread(
                self.client().generate_json,
                model=self.model,
                system=system,
                user=user,
                schema=SCHEMA,
            )
        except text_models.ProviderFailure as error:
            raise ModelUnavailable("failed", error.outcome) from None
        usage = answer.usage
        tokens_in = int(usage.get("promptTokenCount") or 0)
        # Thinking tokens are billed as output (as Admin's cost metrics count them).
        tokens_out = int(usage.get("candidatesTokenCount") or 0) + int(
            usage.get("thoughtsTokenCount") or 0
        )
        return Completion(
            text=json.dumps(answer.value, ensure_ascii=False),
            provider=self.provider,
            model=self.model,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cost_inr=model_menu.cost_inr(self.model, tokens_in, tokens_out),
        )
