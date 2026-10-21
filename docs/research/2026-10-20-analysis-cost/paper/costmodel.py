"""Cost model for Sales X-Ray call analysis (research, 20 Oct 2026).

cost(call of m audio minutes) = STT(m) + sum over LLM stages of
    [(I_fix + I_var*m) * p_in * (1 - cached_share*(1 - cache_ratio)) + (O_fix + O_var*m) * p_out] * batch_factor

Token shapes for today's pipeline are the measured staging fits (anatomy section 1.1). Shapes (b)-(d) are
*design estimates* to be replaced by benchmark measurements in phase 3. Prices: list prices read live on
20 Oct 2026 (Google pricing page, OpenRouter /api/v1/models, provider pages). Rupees at the Admin sheet's 100/$.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass

FX = 100.0  # Admin price sheet; live rate ~96.5
AUDIO_TOK_PER_MIN = 1920  # Gemini: 32 tokens per second of audio (ai.google.dev/gemini-api/docs/audio)

# (input $/M, output $/M, audio-input $/M or None, cached-input ratio of input price)
LLM = {
    "gemini-3.8-flash": (0.75, 3.75, 0.75, 0.10),
    "gemini-3.8-flash-batch": (0.375, 1.875, 0.375, 0.10),
    "gemini-3.8-flash-flex": (0.375, 1.875, 0.375, 0.10),
    "gemini-3.5-flash-lite": (0.30, 2.50, 0.30, 0.10),
    "gemini-3.5-flash-lite-flex": (0.15, 1.25, 0.15, 0.10),
    "gemini-3.1-flash-lite-flex": (0.125, 0.75, 0.25, 0.10),
    "gemini-3.1-flash-lite": (0.25, 1.50, 0.50, 0.10),
    "gemini-2.5-flash-lite": (0.10, 0.40, 0.30, 0.10),
    "gemini-2.5-flash-lite-batch": (0.05, 0.20, 0.15, 0.20),
    "claude-haiku-5.5": (0.10, 0.50, None, 0.10),
    "gpt-6-luna": (0.10, 0.50, None, 0.10),
    "deepseek-v4.1-flash": (0.14, 0.42, None, 0.03),  # DeepInfra fp8 (reputable host)
    "glm-5.3-flash": (0.15, 0.50, None, 0.2),  # Z.ai first party
    "qwen3.8-flash": (0.15, 0.47, None, 0.107),
    "mimo-v2.6-flash": (0.14, 0.28, None, 0.02),
    "gpt-oss-20b": (0.018, 0.09, None, 0.5),
}

# $ per audio minute
STT = {
    "scribe-v2": 0.22 / 60,
    "groq-whisper-large-v3-turbo": 0.04 / 60,
    "groq-whisper-large-v3": 0.111 / 60,
    "assemblyai-universal-2+diar": (0.15 + 0.02) / 60,
    "assemblyai-universal-3.5-pro+diar": (0.21 + 0.02) / 60,
    "deepgram-nova-3-multi": 0.0052,
    "sarvam-batch-diar-payg": 0.59 / FX,
    "none": 0.0,
}


@dataclass(frozen=True)
class Stage:
    name: str
    i_fix: float
    i_var: float  # per audio minute (text tokens)
    o_fix: float
    o_var: float
    audio: bool = False  # the stage takes the audio itself (AUDIO_TOK_PER_MIN audio tokens per minute)
    cached_share: float = 0.0  # share of the text input that is a cache hit


TODAY = [  # measured, staging fits
    Stage("C4 facts", 0, 735, 92, 60),
    Stage("C5 report", 4122, 617, 3456, 37),
    Stage("pointer review", 792, 419, 4187, 3),
    Stage("call-data fast", 1263, 400, 1761, 7),
    Stage("call-data deep", 965, 807, 2342, 519),
]
TODAY_NO_CALLDATA = TODAY[:3]
TODAY_NO_DEEP_LABELS = TODAY[:4] + [Stage("call-data deep extract only", 965, 400, 1761, 7)]
# today's stages, prompts reordered so the transcript is a shared prefix: 5 of 6 reads hit the implicit cache
TODAY_CACHED = [Stage(s.name, s.i_fix, s.i_var, s.o_fix, s.o_var, cached_share=(0.0 if i == 0 else 0.6)) for i, s in enumerate(TODAY)]

# (b) one text pass: transcript once, one compact JSON with facts + pointers + report + call data.
ONE_PASS = [Stage("one pass", 4500, 430, 4200, 110)]
# (b') two passes over one cached transcript prefix (facts+call data, then report+pointers).
TWO_PASS_CACHED = [Stage("facts+data", 3000, 430, 1800, 90), Stage("report+pointers", 3500, 480, 3000, 30, cached_share=0.75)]
# (c) audio in, one call: transcript (speaker+time segments, ~560 tok/min) + the compact analysis JSON.
AUDIO_ONE_CALL = [Stage("audio->transcript+analysis", 4500, 0, 4200, 560 + 110, audio=True)]
# (c') audio in for the transcript only, then the text pass (b) on a cheaper text model.
AUDIO_TRANSCRIBE = [Stage("audio->transcript", 600, 0, 50, 560, audio=True)]
# (d) hybrid: local classifiers/features replace segment labels and measured stats; the LLM writes facts + wording
# from the transcript once, with a much smaller fixed output (labels and numbers come from the classifiers).
HYBRID_TEXT = [Stage("facts+wording", 3500, 430, 2500, 60)]


def llm_cost(stages: list[Stage], model: str, m: float) -> float:
    p_in, p_out, p_audio, cache_ratio = LLM[model]
    usd = 0.0
    for s in stages:
        text_in = s.i_fix + s.i_var * m
        eff_in = text_in * (1 - s.cached_share * (1 - cache_ratio))
        usd += eff_in * p_in / 1e6 + (s.o_fix + s.o_var * m) * p_out / 1e6
        if s.audio:
            if p_audio is None:
                raise ValueError(f"{model} takes no audio")
            usd += AUDIO_TOK_PER_MIN * m * p_audio / 1e6
    return usd


def call_cost(stt: str, stages_by_model: list[tuple[list[Stage], str]], m: float) -> dict[str, float]:
    usd = STT[stt] * m + sum(llm_cost(st, model, m) for st, model in stages_by_model)
    return {"usd_per_call": usd, "inr_per_call": usd * FX, "inr_per_min": usd * FX / m, "usd_per_min": usd / m}


SCENARIOS = {
    "a. today (Scribe + 3.8 Flash, all stages)": ("scribe-v2", [(TODAY, "gemini-3.8-flash")]),
    "a. today without call-data fast+deep": ("scribe-v2", [(TODAY_NO_CALLDATA, "gemini-3.8-flash")]),
    "a. today, all stages on 3.8 Flash batch": ("scribe-v2", [(TODAY, "gemini-3.8-flash-batch")]),
    "a. today, all stages on 2.5 Flash-Lite": ("scribe-v2", [(TODAY, "gemini-2.5-flash-lite")]),
    "a. today on Flex": ("scribe-v2", [(TODAY, "gemini-3.8-flash-flex")]),
    "a. today on Flex, deep labels off, transcript-first prompts (cache)": ("scribe-v2", [(TODAY_CACHED[:4] + [Stage("deep extract", 965, 400, 1761, 7, cached_share=0.6)], "gemini-3.8-flash-flex")]),
    "b. Scribe + one pass 3.8 Flash": ("scribe-v2", [(ONE_PASS, "gemini-3.8-flash")]),
    "b. Scribe + one pass 3.8 Flash Flex": ("scribe-v2", [(ONE_PASS, "gemini-3.8-flash-flex")]),
    "b. Scribe + one pass 3.1 Flash-Lite Flex": ("scribe-v2", [(ONE_PASS, "gemini-3.1-flash-lite-flex")]),
    "b. Scribe + one pass 2.5 Flash-Lite": ("scribe-v2", [(ONE_PASS, "gemini-2.5-flash-lite")]),
    "b. Scribe + one pass 3.1 Flash-Lite": ("scribe-v2", [(ONE_PASS, "gemini-3.1-flash-lite")]),
    "b. Scribe + two cached passes 3.8 Flash": ("scribe-v2", [(TWO_PASS_CACHED, "gemini-3.8-flash")]),
    "c. audio one call 3.8 Flash": ("none", [(AUDIO_ONE_CALL, "gemini-3.8-flash")]),
    "c. audio one call 3.1 Flash-Lite": ("none", [(AUDIO_ONE_CALL, "gemini-3.1-flash-lite")]),
    "c. audio one call 2.5 Flash-Lite": ("none", [(AUDIO_ONE_CALL, "gemini-2.5-flash-lite")]),
    "c. audio one call 2.5 Flash-Lite batch": ("none", [(AUDIO_ONE_CALL, "gemini-2.5-flash-lite-batch")]),
    "c'. 3.1 FL Flex audio->transcript + one pass 3.8 Flash Flex": ("none", [(AUDIO_TRANSCRIBE, "gemini-3.1-flash-lite-flex"), (ONE_PASS, "gemini-3.8-flash-flex")]),
    "c'. 3.1 FL Flex audio->transcript + one pass 3.1 FL Flex": ("none", [(AUDIO_TRANSCRIBE, "gemini-3.1-flash-lite-flex"), (ONE_PASS, "gemini-3.1-flash-lite-flex")]),
    "c. audio one call 3.1 Flash-Lite Flex": ("none", [(AUDIO_ONE_CALL, "gemini-3.1-flash-lite-flex")]),
    "c. audio one call 3.8 Flash Flex": ("none", [(AUDIO_ONE_CALL, "gemini-3.8-flash-flex")]),
    "c'. 2.5 FL audio->transcript + one pass 2.5 FL": ("none", [(AUDIO_TRANSCRIBE, "gemini-2.5-flash-lite"), (ONE_PASS, "gemini-2.5-flash-lite")]),
    "c'. 2.5 FL audio->transcript + one pass 3.8 Flash": ("none", [(AUDIO_TRANSCRIBE, "gemini-2.5-flash-lite"), (ONE_PASS, "gemini-3.8-flash")]),
    "d. Scribe + hybrid 3.8 Flash": ("scribe-v2", [(HYBRID_TEXT, "gemini-3.8-flash")]),
    "d. Scribe + hybrid 2.5 Flash-Lite": ("scribe-v2", [(HYBRID_TEXT, "gemini-2.5-flash-lite")]),
    "d. 2.5 FL audio->transcript + hybrid 2.5 FL": ("none", [(AUDIO_TRANSCRIBE, "gemini-2.5-flash-lite"), (HYBRID_TEXT, "gemini-2.5-flash-lite")]),
    "new provider*: Groq turbo + one pass DeepSeek V4.1 Flash": ("groq-whisper-large-v3-turbo", [(ONE_PASS, "deepseek-v4.1-flash")]),
    "new provider*: Groq turbo + one pass Haiku 5.5": ("groq-whisper-large-v3-turbo", [(ONE_PASS, "claude-haiku-5.5")]),
    "new provider*: Groq turbo + hybrid GLM-5.3 Flash": ("groq-whisper-large-v3-turbo", [(HYBRID_TEXT, "glm-5.3-flash")]),
    "new provider*: AssemblyAI U2 + one pass Haiku 5.5": ("assemblyai-universal-2+diar", [(ONE_PASS, "claude-haiku-5.5")]),
    "new provider*: Scribe + today's stages on DeepSeek V4.1 Flash": ("scribe-v2", [(TODAY, "deepseek-v4.1-flash")]),
}


def main() -> None:
    lengths = [4.5, 13.8, 60.0]
    rows = []
    for name, (stt, sbm) in SCENARIOS.items():
        r = {"scenario": name}
        for m in lengths:
            c = call_cost(stt, sbm, m)
            r[f"inr_per_min@{m}"] = round(c["inr_per_min"], 3)
            r[f"usd_per_min@{m}"] = round(c["usd_per_min"], 5)
        rows.append(r)
    if "--json" in sys.argv:
        print(json.dumps(rows, indent=1))
        return
    print(f"{'scenario':58s} " + " ".join(f"{'₹/min@'+str(m):>11s}" for m in lengths) + f" {'$/min@13.8':>11s}")
    for r in rows:
        print(f"{r['scenario']:58s} " + " ".join(f"{r[f'inr_per_min@{m}']:11.3f}" for m in lengths) + f" {r['usd_per_min@13.8']:11.5f}")


if __name__ == "__main__":
    main()
