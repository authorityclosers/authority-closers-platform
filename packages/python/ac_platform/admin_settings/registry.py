"""The Admin settings registry (admin revamp Phase 6, 19 Oct 2026).

Every setting Admin controls, where its value is read and how it is changed, as one
manifest. The Admin web (All settings), the admin command line and an MCP server read
this one list, so a setting added here appears in all three.

A change goes through the area's own route: its validation, revision check, audit and
idempotency stay where they are. The registry only says which route, which body and
which revision. Some areas take their whole document back ("merge"): the client reads
the document, sets the one field and sends it with the revision it read. Values are
never stored or cached here. Settings without a write are changed on their page (a
pinned approval, an owner's confirmation or an editor).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Literal

SCHEMA = "ac.admin-settings/1"

Kind = Literal["bool", "int", "enum", "money_paise", "text"]

EXECUTION = "/v1/admin/conversation/execution"
BUDGET = "/v1/admin/conversation/budget"
ANALYSIS = "/v1/admin/conversation/analysis-settings"
CALL_DATA = "/v1/admin/call-data"
CALL_DATA_SAVE = "/v1/admin/call-data/settings"
PROVIDERS = "/v1/admin/conversation/providers"
LEAD_DESK_AI = "/v1/admin/lead-desk-ai"
LEAD_DESK_AI_SAVE = "/v1/admin/lead-desk-ai/settings"
PIPELINE = "/v1/admin/analysis-pipeline"
PIPELINE_SAVE = "/v1/admin/analysis-pipeline/settings"

# Templates in a write body: the new value, the revision read with it, the reason the
# person gave, and (for a merge) the document read with the one field set.
VALUE, REVISION, REASON, MERGED = "$value", "$revision", "$reason", "$merged"


@dataclass(frozen=True)
class Read:
    path: str
    value: str  # JSON pointer into the read's answer
    revision: str | None = None
    changed_at: str | None = None


@dataclass(frozen=True)
class Merge:
    container: str  # JSON pointer to the document sent back whole
    key: tuple[str, ...]  # the field inside it


@dataclass(frozen=True)
class Write:
    method: Literal["POST", "PUT"]
    path: str
    body: dict[str, Any]
    idempotency_key: bool = True
    merge: Merge | None = None
    needs_reason: bool = False


@dataclass(frozen=True)
class Setting:
    id: str
    area: str
    label: str
    kind: Kind
    read: Read
    write: Write | None = None
    help: str = ""
    minimum: int | None = None
    maximum: int | None = None
    # A bound read from the answer (e.g. the approved budget cap), when it is not fixed.
    maximum_from: str | None = None
    options: tuple[tuple[str, str], ...] = ()
    # Options read from the answer: (pointer to a list, value field, label field).
    options_from: tuple[str, str, str] | None = None
    labels: dict[str, str] = field(default_factory=dict)
    why_not: str = ""


AREAS: tuple[dict[str, str], ...] = (
    {"key": "execution", "title": "Running and AI budget", "page": "/sales-xray/execution"},
    {"key": "analysis", "title": "Analysis engine", "page": "/sales-xray/analysis"},
    {"key": "call-data", "title": "Call data engine", "page": "/sales-xray/call-data"},
    {"key": "lead-desk-ai", "title": "AI replies to leads", "page": "/settings#lead-desk-ai"},
    {"key": "providers", "title": "AI providers and models", "page": "/sales-xray/providers"},
    {"key": "review", "title": "Review pipelines", "page": "/settings/review-pipelines"},
    {"key": "report", "title": "Report versions", "page": "/sales-xray/report-settings"},
    {
        "key": "analysis-pipeline",
        "title": "Analysis pipeline (one-pass trial)",
        "page": "/sales-xray/one-pass",
    },
)

ANALYSIS_READ = {"revision": "/revision", "changed_at": "/created_at"}
ANALYSIS_WRITE = {"expected_revision": REVISION, "settings": MERGED}


def _analysis(id: str, key: str, label: str, kind: Kind, help: str = "", **bounds: Any) -> Setting:
    return Setting(
        id=id,
        area="analysis",
        label=label,
        kind=kind,
        help=help,
        read=Read(ANALYSIS, f"/settings/{key}", **ANALYSIS_READ),
        write=Write("POST", ANALYSIS, ANALYSIS_WRITE, merge=Merge("/settings", (key,))),
        **bounds,
    )


def _call_data(pipeline: str, key: str, label: str, kind: Kind, **bounds: Any) -> Setting:
    return Setting(
        id=f"call_data.{pipeline}.{key}",
        area="call-data",
        label=label,
        kind=kind,
        read=Read(CALL_DATA, f"/config/{pipeline}/{key}", revision="/revision"),
        write=Write(
            "PUT",
            CALL_DATA_SAVE,
            {"expected_revision": REVISION, "config": MERGED},
            idempotency_key=False,
            merge=Merge("/config", (pipeline, key)),
        ),
        **bounds,
    )


def _lead_desk_ai(key: str, label: str, kind: Kind, **bounds: Any) -> Setting:
    """AI replies to lead messages: the Lead Desk's own switch, model and cap (20 Oct)."""
    return Setting(
        id=f"lead_desk_ai.{key}",
        area="lead-desk-ai",
        label=label,
        kind=kind,
        read=Read(LEAD_DESK_AI, f"/config/{key}", revision="/revision"),
        write=Write(
            "PUT",
            LEAD_DESK_AI_SAVE,
            {"expected_revision": REVISION, "config": MERGED},
            idempotency_key=False,
            merge=Merge("/config", (key,)),
        ),
        **bounds,
    )


def _pipeline(key: str, label: str, kind: Kind, **bounds: Any) -> Setting:
    """Which analysis pipeline this environment runs: today's, both side by side
    (development), or one pass (the owner's typed confirm on its page; owner, 21 Oct
    2026). The registry's write carries no confirm, so one_pass is refused here."""
    return Setting(
        id=f"analysis_pipeline.{key}",
        area="analysis-pipeline",
        label=label,
        kind=kind,
        read=Read(PIPELINE, f"/config/{key}", revision="/revision"),
        write=Write(
            "PUT",
            PIPELINE_SAVE,
            {"expected_revision": REVISION, "config": MERGED, "reason": REASON},
            idempotency_key=False,
            merge=Merge("/config", (key,)),
            needs_reason=key == "mode",
        ),
        **bounds,
    )


LANGUAGES = (
    ("en", "English"),
    ("hi-Deva+en", "Hindi and English"),
    ("mr-Deva+en", "Marathi and English"),
)
PROMPTS = tuple(
    (value, value) for value in ("coaching-v3", "coaching-v4", "coaching-v5", "coaching-v6")
)
MODEL_MENU = ("/models", "model", "label")
ON_OFF = {"true": "On", "false": "Off"}

SETTINGS: tuple[Setting, ...] = (
    Setting(
        id="execution.paused",
        area="execution",
        label="Analyses",
        kind="bool",
        help="Pause stops new analyses from starting; work already running finishes.",
        labels={"true": "Paused", "false": "Running"},
        read=Read(EXECUTION, "/control/paused", "/control/revision", "/control/changed_at"),
        write=Write("POST", EXECUTION, {"expected_revision": REVISION, "paused": VALUE}),
    ),
    Setting(
        id="budget.cap_paise",
        area="execution",
        label="AI budget",
        kind="money_paise",
        help="The most AI spend allowed in the budget's period, up to the owner's ceiling.",
        minimum=0,
        maximum_from="/approved_cap_paise",
        read=Read(BUDGET, "/budget/cap_paise", "/revision"),
        write=Write(
            "POST",
            BUDGET,
            {"expected_revision": REVISION, "new_cap_paise": VALUE, "reason": REASON},
            needs_reason=True,
        ),
    ),
    Setting(
        id="budget.ceiling_paise",
        area="execution",
        label="Budget ceiling",
        kind="money_paise",
        read=Read(BUDGET, "/settings/ceiling_paise"),
        why_not="The owner sets the ceiling and its period on the Running and AI budget page.",
    ),
    _analysis(
        "analysis.facts_max_requests",
        "c4_max_requests",
        "Facts: most AI requests per call",
        "int",
        minimum=1,
        maximum=64,
    ),
    _analysis(
        "analysis.facts_max_tokens",
        "c4_max_completion_tokens",
        "Facts: longest answer (tokens)",
        "int",
        minimum=256,
        maximum=4_000,
    ),
    _analysis(
        "analysis.report_max_tokens",
        "c5_max_completion_tokens",
        "Report: longest answer (tokens)",
        "int",
        minimum=256,
        maximum=8_000,
    ),
    _analysis(
        "analysis.report_detail",
        "c5_output_profile",
        "Report detail",
        "enum",
        options=(("standard", "Standard"), ("detailed", "Detailed")),
    ),
    _analysis(
        "analysis.coaching_prompt",
        "c5_coaching_prompt_revision",
        "Coaching prompt",
        "enum",
        options=PROMPTS,
    ),
    _analysis(
        "analysis.report_language",
        "report_language_default",
        "Report language",
        "enum",
        help="A language other than English needs coaching-v4 or later.",
        options=LANGUAGES,
    ),
    *(
        item
        for pipeline, title in (("fast", "Fast pipeline"), ("deep", "Deep pipeline"))
        for item in (
            _call_data(pipeline, "enabled", f"{title}", "bool", labels=ON_OFF),
            _call_data(pipeline, "model", f"{title}: model", "enum", options_from=MODEL_MENU),
            _call_data(
                pipeline,
                "daily_cap_inr",
                f"{title}: daily cap (₹)",
                "int",
                minimum=0,
                maximum=5_000,
            ),
            _call_data(
                pipeline,
                "max_call_minutes",
                f"{title}: longest call (minutes)",
                "int",
                minimum=1,
                maximum=120,
            ),
        )
    ),
    _lead_desk_ai(
        "enabled",
        "AI replies to lead messages",
        "bool",
        labels=ON_OFF,
        help="Lead messages go to the AI provider only while this is on, in this environment.",
    ),
    _lead_desk_ai("model", "AI replies: model", "enum", options_from=MODEL_MENU),
    _lead_desk_ai("cap_inr", "AI replies: cap (₹)", "int", minimum=0, maximum=50_000),
    _lead_desk_ai(
        "period",
        "AI replies: cap counted",
        "enum",
        options=(("daily", "Each day"), ("monthly", "Each month"), ("lifetime", "In total")),
    ),
    Setting(
        id="providers.paid_allowed",
        area="providers",
        label="Paid providers",
        kind="bool",
        labels={"true": "Allowed", "false": "Not allowed"},
        read=Read(
            PROVIDERS,
            "/current/configuration/policy/allow_paid",
            "/current/revision",
            "/current/created_at",
        ),
        why_not="Provider routes are saved and activated together on their page.",
    ),
    _pipeline(
        "mode",
        "Analysis pipeline",
        "enum",
        help="Both (development) runs the Google-only one-pass pipeline beside today's; "
        "people keep seeing today's. One pass (people see it) is the owner's action on the "
        "One-pass page: type one_pass, give the reason. Its spend cap is in AI spend.",
        options_from=("/modes", "value", "label"),
    ),
    _pipeline(
        "transcription_tier",
        "One pass: transcription tier",
        "enum",
        help="Flex is half price and may wait minutes.",
        options_from=("/tiers", "value", "label"),
    ),
    _pipeline(
        "analysis_tier",
        "One pass: analysis tier",
        "enum",
        help="Flex is half price and may wait minutes.",
        options_from=("/tiers", "value", "label"),
    ),
    _pipeline(
        "max_call_minutes",
        "One pass: longest call (minutes)",
        "int",
        minimum=1,
        maximum=120,
    ),
)


def _area_title(key: str) -> str:
    return next(area["title"] for area in AREAS if area["key"] == key)


def setting_view(item: Setting) -> dict[str, Any]:
    write = item.write
    return {
        "id": item.id,
        "area": item.area,
        "area_title": _area_title(item.area),
        "label": item.label,
        "kind": item.kind,
        "help": item.help or None,
        "read": {
            "path": item.read.path,
            "value": item.read.value,
            "revision": item.read.revision,
            "changed_at": item.read.changed_at,
        },
        "write": None
        if write is None
        else {
            "method": write.method,
            "path": write.path,
            "body": write.body,
            "idempotency_key": write.idempotency_key,
            "merge": None
            if write.merge is None
            else {"container": write.merge.container, "key": list(write.merge.key)},
            "needs_reason": write.needs_reason,
        },
        "minimum": item.minimum,
        "maximum": item.maximum,
        "maximum_from": item.maximum_from,
        "options": [{"value": value, "label": label} for value, label in item.options],
        "options_from": None
        if item.options_from is None
        else dict(zip(("list", "value", "label"), item.options_from, strict=True)),
        "labels": item.labels or None,
        "why_not": item.why_not or None,
    }


def manifest() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "areas": [dict(area) for area in AREAS],
        "settings": [setting_view(item) for item in SETTINGS],
    }


def find(setting_id: str) -> Setting | None:
    return next((item for item in SETTINGS if item.id == setting_id), None)


def pointer(document: Any, path: str) -> Any:
    """RFC 6901 JSON pointer; None when any step is missing."""
    if path in ("", "/"):
        return document
    current = document
    for raw in path.lstrip("/").split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def request_body(
    item: Setting, read_answer: dict[str, Any], value: Any, reason: str | None = None
) -> dict[str, Any]:
    """The change's body, from the read's answer (revision, document) and the new value.

    The same steps the web, the command line and MCP take; kept here as the reference
    and tested against the areas' own request models.
    """
    if item.write is None:
        raise ValueError(item.why_not or "This setting is changed on its page.")
    if item.write.needs_reason and not (reason and reason.strip()):
        raise ValueError("Give a reason for this change.")
    merged: Any = None
    if item.write.merge is not None:
        merged = copy.deepcopy(pointer(read_answer, item.write.merge.container))
        if not isinstance(merged, dict):
            raise ValueError("The current settings could not be read.")
        target = merged
        for part in item.write.merge.key[:-1]:
            target = target.setdefault(part, {})
        target[item.write.merge.key[-1]] = value
    revision = pointer(read_answer, item.read.revision) if item.read.revision else None
    fill = {VALUE: value, REVISION: revision, REASON: (reason or "").strip(), MERGED: merged}
    return {key: fill.get(template, template) for key, template in item.write.body.items()}
