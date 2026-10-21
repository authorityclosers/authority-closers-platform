"""Every provider Sales X-Ray may use, as Admin's Providers hub lists them.

An entry says what the provider is for, where its own console is (usage, credit, keys), how
its models are listed, and which provider-registry adapter calls it today, if any. Model
lists come from OpenRouter's public catalogue by model-id prefix, from the registry's
adapters and from the price sheet; a provider OpenRouter does not list (Groq, Together,
Fireworks, Cerebras, the speech providers) shows its models once its own key is added.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Kind = Literal["llm", "speech", "router"]
KIND_LABEL: dict[Kind, str] = {
    "llm": "Language models",
    "speech": "Speech to text",
    "router": "Model routers",
}


@dataclass(frozen=True, slots=True)
class Provider:
    id: str
    name: str
    kind: Kind
    blurb: str
    # The provider's own console: usage, credit and keys live there.
    console: str
    # The provider registry's adapter id, when the analysis pipeline can call it.
    registry_id: str | None = None
    # OpenRouter model ids it serves ("google/"); "*" is every model (OpenRouter itself).
    prefixes: tuple[str, ...] = ()
    # Speaks the OpenAI API, so any OpenAI-compatible client reaches it.
    compatible: bool = False
    # Extra words people may search by.
    aliases: tuple[str, ...] = ()
    # How the provider treats the data Sales X-Ray sends, where an approval states it.
    data_terms: str = ""


PROVIDERS: tuple[Provider, ...] = (
    Provider(
        "openrouter",
        "OpenRouter",
        "router",
        "One key and one bill for hundreds of models from every major lab.",
        "https://openrouter.ai/settings/credits",
        prefixes=("*",),
        compatible=True,
        aliases=("router", "gateway"),
    ),
    Provider(
        "gemini",
        "Google Gemini",
        "llm",
        "Gemini Flash and Pro: fast, long context, native JSON and audio input.",
        "https://aistudio.google.com",
        registry_id="gemini",
        prefixes=("google/",),
        aliases=("google", "ai studio", "vertex"),
    ),
    Provider(
        "openai",
        "OpenAI",
        "llm",
        "GPT models with structured outputs.",
        "https://platform.openai.com",
        registry_id="openai",
        prefixes=("openai/",),
        compatible=True,
        aliases=("gpt", "chatgpt"),
        # Owner approval, 21 Oct 2026: an AI processor for real call analysis.
        data_terms=(
            "Approved for real call analysis (transcripts only). API data is not used to"
            " train OpenAI's models. Sales X-Ray sends store: false, so answers are not kept"
            " as application state. OpenAI keeps API data in its abuse-monitoring logs for up"
            " to 30 days (longer only where the law requires), and none there once it grants"
            " zero data retention."
        ),
    ),
    Provider(
        "anthropic",
        "Anthropic",
        "llm",
        "Claude models for careful reading and writing.",
        "https://console.anthropic.com",
        registry_id="anthropic",
        prefixes=("anthropic/",),
        aliases=("claude",),
    ),
    Provider(
        "groq",
        "Groq",
        "llm",
        "Open models at very high speed on Groq's own chips.",
        "https://console.groq.com",
        registry_id="groq",
        compatible=True,
        aliases=("llama", "gpt-oss"),
    ),
    Provider(
        "deepseek",
        "DeepSeek",
        "llm",
        "Low-cost reasoning and chat models.",
        "https://platform.deepseek.com",
        registry_id="deepseek",
        prefixes=("deepseek/",),
        compatible=True,
    ),
    Provider(
        "mistral",
        "Mistral",
        "llm",
        "European models, from small to large.",
        "https://console.mistral.ai",
        prefixes=("mistralai/",),
        compatible=True,
    ),
    Provider(
        "together",
        "Together AI",
        "llm",
        "Open models hosted for you, paid per token.",
        "https://api.together.ai",
        compatible=True,
    ),
    Provider(
        "fireworks",
        "Fireworks AI",
        "llm",
        "Fast hosted open models.",
        "https://fireworks.ai",
        compatible=True,
    ),
    Provider(
        "cerebras",
        "Cerebras",
        "llm",
        "Open models at very high speed on Cerebras chips.",
        "https://cloud.cerebras.ai",
        compatible=True,
    ),
    Provider(
        "elevenlabs",
        "ElevenLabs",
        "speech",
        "Scribe speech to text with speaker labels.",
        "https://elevenlabs.io/app/subscription",
        registry_id="elevenlabs",
        aliases=("scribe", "eleven labs"),
    ),
    Provider(
        "deepgram",
        "Deepgram",
        "speech",
        "Nova speech to text with word timings.",
        "https://console.deepgram.com",
        registry_id="deepgram",
        aliases=("nova",),
    ),
    Provider(
        "assemblyai",
        "AssemblyAI",
        "speech",
        "Speech to text with speaker labels.",
        "https://www.assemblyai.com/dashboard",
        aliases=("assembly ai",),
    ),
    Provider(
        "sarvam",
        "Sarvam",
        "speech",
        "Indian-language speech to text, including code-mixed Hindi.",
        "https://dashboard.sarvam.ai",
        registry_id="sarvam",
        aliases=("saaras", "hindi", "indic"),
    ),
    Provider(
        "gladia",
        "Gladia",
        "speech",
        "Multilingual speech to text.",
        "https://app.gladia.io",
    ),
    Provider(
        "speechmatics",
        "Speechmatics",
        "speech",
        "Speech to text in many languages.",
        "https://portal.speechmatics.com",
    ),
    Provider(
        "custom",
        "Custom (OpenAI-compatible)",
        "llm",
        "Any server that speaks the OpenAI API: your own vLLM, Ollama or a gateway.",
        "",
        registry_id="openai_compatible_gateway",
        compatible=True,
        aliases=("vllm", "ollama", "self-hosted", "local"),
    ),
)

BY_ID = {provider.id: provider for provider in PROVIDERS}


def find(query: str) -> list[Provider]:
    """Providers whose name, id, kind or aliases contain every word typed, in catalogue order."""

    words = query.lower().split()
    if not words:
        return list(PROVIDERS)

    def haystack(provider: Provider) -> str:
        return " ".join(
            (provider.id, provider.name, KIND_LABEL[provider.kind], *provider.aliases)
        ).lower()

    return [provider for provider in PROVIDERS if all(word in haystack(provider) for word in words)]
