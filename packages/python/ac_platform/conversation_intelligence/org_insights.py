"""The owner's and manager's company view (AUT-1798): all calls, combined.

Reads aggregate a narrow per-call projection (``conversation_insight_calls``)
with plain SQL, so an organisation with years of calls still answers in one
request. Two sources feed it:

- ``call``: the organisation's own analysed calls. One row per call with a
  saved report: owner, date, duration, report language, the report's outcome,
  the seller's talk share (only when the rep confirmed who the seller was),
  the eight skill states and the objections the report found.
- ``synthetic``: an approved sandbox organisation's authored dataset
  (``conversation_synthetic_records``), clearly labelled and never mixed with
  real teams; a sandbox organisation shows only its synthetic calls.

The projection is rebuilt, never trusted: ``refresh`` adds or replaces rows in
bounded batches, and every read re-checks the caller and, for real calls,
joins the live library scope so revoked or expired calls drop out at once.
Outcomes and skill states are what each report says. These figures are a
guide for coaching, never an official score (AC-SVAL).
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Integer,
    String,
    Text,
    case,
    cast,
    delete,
    func,
    literal,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement, Select

from ac_platform.conversation_intelligence.call_metrics_models import ConversationCallMetrics
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.insight_models import (
    OUTCOMES,
    SKILL_ORDER,
    ConversationInsightCall,
)
from ac_platform.conversation_intelligence.models import (
    ConversationProcessingPlan,
    ConversationReportDraft,
)
from ac_platform.conversation_intelligence.recovery_models import ConversationRetainedC5Version
from ac_platform.conversation_intelligence.speaker_map_models import (
    ConversationSpeakerMapRevision,
)
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
    ConversationSyntheticRecord,
)
from ac_platform.identity.models import Person

INDIA = "Asia/Kolkata"
CALL_BATCH = 200
SYNTHETIC_BATCH = 10_000
CALL_PAGE = 50
CACHE_SECONDS = 300
CACHE_SIZE = 64
_CACHE: OrderedDict[tuple[Any, ...], tuple[float, dict[str, Any]]] = OrderedDict()
RANGES = {"30d": 30, "90d": 90, "12m": 365}
NEXT_STEP = ("won", "booked", "follow_up")
SKILL_LABELS = {
    "human_connection_trust": "Human connection & trust",
    "discovery_deep_understanding": "Discovery & deep understanding",
    "qualification": "Qualification",
    "problem_impact_desire": "Problem, impact & desire",
    "solution_relevance_presentation": "Solution relevance & presentation",
    "certainty_objection_intelligence": "Certainty & objection intelligence",
    "closing_decision_management": "Closing & decision management",
    "communication_tonality": "Communication & tonality",
}
LANGUAGES = {
    "en": "English",
    "en-IN": "English",
    "hi-en": "Hindi + English",
    "mr-en": "Marathi + English",
    "hi-mr-en": "Hindi + Marathi + English",
    "gu-en": "Gujarati + English",
    "bn-en": "Bengali + English",
    "ta-en": "Tamil + English",
    "te-en": "Telugu + English",
    "kn-en": "Kannada + English",
    "ml-en": "Malayalam + English",
    "pa-en": "Punjabi + English",
}
MISTAKES = {
    "missing_decision_maker": "Missed the decision-maker",
    "talking_too_much": "Talked too much",
    "weak_objection_handling": "Weak objection handling",
    "no_discovery": "Skipped discovery",
    "no_next_step": "No clear next step",
    "discounting_early": "Discounted too early",
}

# What each report says about how the call ended, in one vocabulary.
_OVERVIEW_OUTCOMES = {
    "closed": "won",
    "follow_up": "follow_up",
    "future_date": "booked",
    "no_sale": "lost",
    "disqualified": "disqualified",
    "unclear": "unclear",
}
_CALL_MAP_OUTCOMES = {
    "won": "won",
    "lost": "lost",
    "follow_up": "follow_up",
    "disqualified": "disqualified",
    "none": "unclear",
}
_CALL_STATES = {
    "strongly_demonstrated": "S",
    "observed": "O",
    "needs_attention": "N",
    "insufficient_evidence": "U",
    "not_applicable": "-",
}
_STATUSES = {
    "observed": "O",
    "partial": "N",
    "insufficient_evidence": "U",
    "not_applicable": "-",
    "conflicted": "U",
    "unknown": "U",
}


@dataclass(frozen=True, slots=True)
class InsightFilters:
    """One window and optional narrowing; every value was validated by the route."""

    since: datetime | None
    until: datetime
    person: str | None = None
    team: str | None = None
    outcome: str | None = None
    language: str | None = None
    # True for an explicit from/to window, which is never moved.
    fixed: bool = False

    @classmethod
    def window(
        cls,
        now: datetime,
        *,
        span: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        person: str | None = None,
        team: str | None = None,
        outcome: str | None = None,
        language: str | None = None,
    ) -> InsightFilters:
        until = end or now
        fixed = start is not None or end is not None
        if span == "all" and not fixed:
            since = None
        elif start is not None:
            since = start
        else:
            since = until - timedelta(days=RANGES.get(span or "90d", 90))
        return cls(
            since=since,
            until=until,
            person=person,
            team=team,
            outcome=outcome,
            language=language,
            fixed=fixed,
        )

    def to_the_hour(self) -> InsightFilters:
        """The same window ending at the next whole hour (same length).

        For relative windows over authored history only: every record is in
        the past, so the window still holds every record up to now, and
        repeated reads within the hour share one cache entry. An explicit
        from/to window is returned as it is.
        """
        if self.fixed:
            return self
        end = self.until.replace(minute=0, second=0, microsecond=0)
        if end < self.until:
            end += timedelta(hours=1)
        shift = end - self.until
        return InsightFilters(
            since=None if self.since is None else self.since + shift,
            until=end,
            person=self.person,
            team=self.team,
            outcome=self.outcome,
            language=self.language,
        )

    def previous(self) -> InsightFilters | None:
        if self.since is None:
            return None
        length = self.until - self.since
        return InsightFilters(
            since=self.since - length,
            until=self.since,
            person=self.person,
            team=self.team,
            outcome=self.outcome,
            language=self.language,
        )


# --- projection of one real call -------------------------------------------------


def skill_states(dimensions: Any) -> str | None:
    """Eight characters in SKILL_ORDER; None unless all eight skills are present."""
    if not isinstance(dimensions, list):
        return None
    by_id: dict[str, str] = {}
    for item in dimensions:
        if not isinstance(item, Mapping):
            continue
        skill = item.get("dimension_id")
        state = _CALL_STATES.get(str(item.get("call_state")))
        if state is None:
            state = _STATUSES.get(str(item.get("status")))
        if isinstance(skill, str) and state is not None:
            by_id[skill] = state
    if any(skill not in by_id for skill in SKILL_ORDER):
        return None
    return "".join(by_id[skill] for skill in SKILL_ORDER)


def report_outcome(report: Mapping[str, Any]) -> str:
    overview = report.get("overview")
    if isinstance(overview, Mapping):
        observed = overview.get("outcome")
        if isinstance(observed, Mapping) and observed.get("kind") in _OVERVIEW_OUTCOMES:
            return _OVERVIEW_OUTCOMES[str(observed["kind"])]
    call_map = report.get("call_map")
    if isinstance(call_map, Mapping):
        outcome = call_map.get("outcome")
        if isinstance(outcome, Mapping) and outcome.get("kind") in _CALL_MAP_OUTCOMES:
            return _CALL_MAP_OUTCOMES[str(outcome["kind"])]
    return "unclear"


def objection_kinds(report: Mapping[str, Any]) -> str | None:
    """Up to three distinct objection kinds the report found, joined by '|'."""
    call_map = report.get("call_map")
    items = call_map.get("objections") if isinstance(call_map, Mapping) else None
    kinds: list[str] = []
    for item in items if isinstance(items, list) else []:
        kind = item.get("kind") if isinstance(item, Mapping) else None
        if not isinstance(kind, str):
            continue
        name = " ".join(kind.replace("_", " ").split()).lower()[:60]
        if name and "|" not in name and name not in kinds:
            kinds.append(name)
    return "|".join(kinds[:3]) or None


def seller_talk_share(summary: Any, speakers: Any) -> int | None:
    """The seller's share of talk, only when the rep confirmed who the seller is."""
    if not isinstance(summary, Mapping) or not isinstance(speakers, list):
        return None
    sellers = {
        row.get("speaker_id")
        for row in speakers
        if isinstance(row, Mapping) and row.get("role") in ("you", "salesperson")
    }
    measured = summary.get("speakers")
    if not sellers or not isinstance(measured, Mapping):
        return None
    shares = [
        value.get("talk_share")
        for speaker, value in measured.items()
        if speaker in sellers and isinstance(value, Mapping)
    ]
    numbers = [share for share in shares if isinstance(share, int | float)]
    if not numbers:
        return None
    return max(0, min(100, round(sum(numbers) * 100)))


def report_language(manifest: Any) -> str | None:
    if not isinstance(manifest, Mapping):
        return None
    language = manifest.get("report_language")
    if not isinstance(language, str):
        return "en"
    return {"hi-Deva+en": "hi-en", "mr-Deva+en": "mr-en"}.get(language, language)[:32]


# --- the service -----------------------------------------------------------------


def _count(column: Any, code: str) -> ColumnElement[Any]:
    """How many of the eight skill characters equal ``code`` (portable SQL)."""
    return func.length(column) - func.length(func.replace(column, code, ""))


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


def _share(part: int | None, whole: int | None) -> float | None:
    return None if not whole else round((part or 0) / whole, 4)


def _mask_email(email: str | None) -> str:
    if not email or "@" not in email:
        return "Former member"
    local, domain = email.rsplit("@", 1)
    return f"{local[:1]}***@{domain}"


class OrganisationInsights:
    """Aggregates for one organisation; the caller has already been admitted."""

    def __init__(
        self,
        database: AsyncSession,
        tenant_id: UUID,
        *,
        scope_ids: Select[Any] | None = None,
        scope_rows: Select[Any] | None = None,
        recordings: bool = False,
    ) -> None:
        # scope_ids selects the in-scope submission ids as text; scope_rows
        # selects (submission_id, owner_person_id, created_at, seconds,
        # recording_id) for refresh. Both come from the live library scope.
        self.database, self.tenant_id = database, tenant_id
        self.scope_ids, self.scope_rows = scope_ids, scope_rows
        # Admin opens a real call in the review console by its recording; the
        # Sales Xray answer never carries internal recording ids.
        self.recordings = recordings
        self._source: str | None = None

    async def source(self) -> str:
        if self._source is None:
            sandbox = await self.database.scalar(
                select(ConversationSandboxOrganisation.tenant_id).where(
                    ConversationSandboxOrganisation.tenant_id == self.tenant_id
                )
            )
            self._source = "synthetic" if sandbox is not None else "call"
        return self._source

    @property
    def _postgres(self) -> bool:
        return self.database.get_bind().dialect.name == "postgresql"

    # --- refresh ---------------------------------------------------------------

    async def pending(self) -> int:
        """Calls not yet (or no longer) matching the projection."""
        if await self.source() == "synthetic":
            return await self._synthetic_pending()
        candidates = self._call_candidates()
        if candidates is None:
            return 0
        todo = await self.database.scalar(
            select(func.count()).select_from(self._call_todo(candidates).subquery())
        )
        stale = await self.database.scalar(
            select(func.count()).where(*self._call_stale(candidates))
        )
        return int(todo or 0) + int(stale or 0)

    async def refresh(self, *, now: datetime) -> dict[str, int]:
        if await self.source() == "synthetic":
            projected = await self._refresh_synthetic(now)
        else:
            projected = await self._refresh_calls(now)
        return {"projected": projected, "pending": await self.pending()}

    def _call_candidates(self) -> Any:
        """Every call the library shows with a report, its report and speaker map.

        The report is the one the call's report page shows: a recovered report
        of the recording's current generation first, else its newest draft.
        One SQL statement over the library scope; nothing is sized to the
        organisation in Python.
        """
        if self.scope_rows is None:
            return None
        scope = self.scope_rows.subquery()
        draft, recovered = ConversationReportDraft, ConversationRetainedC5Version
        draft_id = (
            select(draft.id)
            .where(
                draft.tenant_id == self.tenant_id,
                draft.recording_id == scope.c.recording_id,
                draft.person_id == scope.c.recording_person_id,
                draft.erased_at.is_(None),
                draft.payload.is_not(None),
            )
            .order_by(draft.created_at.desc(), draft.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        recovered_id = (
            select(recovered.id)
            .where(
                recovered.tenant_id == self.tenant_id,
                recovered.recording_id == scope.c.recording_id,
                recovered.person_id == scope.c.recording_person_id,
                recovered.generation == scope.c.generation,
                recovered.erased_at.is_(None),
                recovered.payload.is_not(None),
            )
            .order_by(recovered.created_at.desc(), recovered.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        # A rep's later seller choice changes talk share without a new report,
        # so a projected row follows the report and the latest speaker map.
        map_revision = (
            select(func.max(ConversationSpeakerMapRevision.revision))
            .where(
                ConversationSpeakerMapRevision.tenant_id == self.tenant_id,
                ConversationSpeakerMapRevision.submission_id == scope.c.submission_id,
            )
            .scalar_subquery()
        )
        inner = select(
            scope.c.submission_id,
            scope.c.owner,
            scope.c.created_at,
            scope.c.seconds,
            scope.c.recording_id,
            cast(scope.c.submission_id, String).label("call_key"),
            draft_id.label("draft_id"),
            recovered_id.label("recovered_id"),
            map_revision.label("map_revision"),
        ).subquery()
        ref = (
            case(
                (
                    inner.c.recovered_id.is_not(None),
                    literal("r") + cast(inner.c.recovered_id, String),
                ),
                else_=literal("d") + cast(inner.c.draft_id, String),
            )
            + literal(":")
            + cast(func.coalesce(inner.c.map_revision, 0), String)
        )
        return (
            select(*inner.c, ref.label("ref"))
            .where(or_(inner.c.draft_id.is_not(None), inner.c.recovered_id.is_not(None)))
            .subquery()
        )

    def _call_todo(self, candidates: Any) -> Select[Any]:
        row = ConversationInsightCall
        return select(candidates).where(
            ~select(row.call_key)
            .where(
                row.tenant_id == self.tenant_id,
                row.source == "call",
                row.call_key == candidates.c.call_key,
                row.source_ref == candidates.c.ref,
            )
            .exists()
        )

    def _call_stale(self, candidates: Any) -> list[ColumnElement[bool]]:
        """Projected rows whose call left the library (revoked, expired, erased)."""
        row = ConversationInsightCall
        return [
            row.tenant_id == self.tenant_id,
            row.source == "call",
            row.call_key.not_in(select(candidates.c.call_key)),
        ]

    async def _refresh_calls(self, now: datetime) -> int:
        candidates = self._call_candidates()
        if candidates is None:
            return 0
        await self.database.execute(
            delete(ConversationInsightCall).where(*self._call_stale(candidates))
        )
        batch = list(
            (
                await self.database.execute(
                    self._call_todo(candidates).order_by(candidates.c.call_key).limit(CALL_BATCH)
                )
            ).all()
        )
        if not batch:
            return 0
        submissions = [item.submission_id for item in batch]
        payloads: dict[UUID, Any] = {}
        drafts = [item.draft_id for item in batch if item.recovered_id is None]
        if drafts:
            for identifier, payload in await self.database.execute(
                select(ConversationReportDraft.id, ConversationReportDraft.payload).where(
                    ConversationReportDraft.id.in_(drafts)
                )
            ):
                payloads[identifier] = payload
        recovered = [item.recovered_id for item in batch if item.recovered_id is not None]
        if recovered:
            for identifier, payload in await self.database.execute(
                select(
                    ConversationRetainedC5Version.id, ConversationRetainedC5Version.payload
                ).where(ConversationRetainedC5Version.id.in_(recovered))
            ):
                payloads[identifier] = payload
        metrics: dict[UUID, Any] = {}
        # Ordered oldest first, so the newest summary and map win.
        for submission_id, summary in await self.database.execute(
            select(ConversationCallMetrics.submission_id, ConversationCallMetrics.summary)
            .where(
                ConversationCallMetrics.tenant_id == self.tenant_id,
                ConversationCallMetrics.submission_id.in_(submissions),
                ConversationCallMetrics.erased_at.is_(None),
            )
            .order_by(ConversationCallMetrics.created_at)
        ):
            metrics[submission_id] = summary
        speakers: dict[UUID, Any] = {}
        for submission_id, rows in await self.database.execute(
            select(
                ConversationSpeakerMapRevision.submission_id,
                ConversationSpeakerMapRevision.speakers,
            )
            .where(
                ConversationSpeakerMapRevision.tenant_id == self.tenant_id,
                ConversationSpeakerMapRevision.submission_id.in_(submissions),
            )
            .order_by(ConversationSpeakerMapRevision.revision)
        ):
            speakers[submission_id] = rows
        languages: dict[UUID, Any] = {}
        for recording_id, manifest in await self.database.execute(
            select(ConversationProcessingPlan.recording_id, ConversationProcessingPlan.manifest)
            .where(
                ConversationProcessingPlan.tenant_id == self.tenant_id,
                ConversationProcessingPlan.recording_id.in_([item.recording_id for item in batch]),
                ConversationProcessingPlan.erased_at.is_(None),
            )
            .order_by(ConversationProcessingPlan.created_at, ConversationProcessingPlan.id)
        ):
            languages[recording_id] = report_language(manifest)
        values = []
        for item in batch:
            report = payloads.get(item.recovered_id or item.draft_id)
            if not isinstance(report, Mapping):
                continue
            values.append(
                {
                    "tenant_id": self.tenant_id,
                    "source": "call",
                    "call_key": item.call_key,
                    "source_ref": item.ref,
                    "person_key": None if item.owner is None else str(item.owner),
                    "team_key": None,
                    "occurred_at": item.created_at,
                    "duration_ms": None if item.seconds is None else int(item.seconds) * 1000,
                    "language": languages.get(item.recording_id),
                    "outcome": report_outcome(report),
                    "talk_share": seller_talk_share(
                        metrics.get(item.submission_id), speakers.get(item.submission_id)
                    ),
                    "skills": skill_states(report.get("dimensions")),
                    "objection": objection_kinds(report),
                    "focus": None,
                    "deal_value": None,
                    "coaching_done": None,
                    "projected_at": now,
                }
            )
        if values:
            # An upsert: two viewers refreshing at once both succeed.
            statement = postgresql_insert(ConversationInsightCall).values(values)
            await self.database.execute(
                statement.on_conflict_do_update(
                    index_elements=["tenant_id", "source", "call_key"],
                    set_={
                        name: getattr(statement.excluded, name)
                        for name in values[0]
                        if name not in {"tenant_id", "source", "call_key"}
                    },
                )
            )
        return len(batch)

    async def _synthetic_pending(self) -> int:
        """Authored calls not yet projected, or imported again since the last refresh."""
        if not self._postgres:
            return 0
        record = ConversationSyntheticRecord
        clean = func.strpos(cast(record.payload, Text), "\\u0000") == 0
        keys = (
            select(record.synthetic_key)
            .where(
                record.tenant_id == self.tenant_id,
                record.kind.in_(("call_summary", "call")),
                clean,
            )
            .distinct()
            .subquery()
        )
        available = await self.database.scalar(select(func.count()).select_from(keys)) or 0
        projected, last = (
            await self.database.execute(
                select(func.count(), func.max(ConversationInsightCall.projected_at)).where(
                    ConversationInsightCall.tenant_id == self.tenant_id,
                    ConversationInsightCall.source == "synthetic",
                )
            )
        ).one()
        missing = max(0, available - int(projected or 0))
        if missing or last is None:
            return missing
        newer = await self.database.scalar(
            select(func.count()).where(
                record.tenant_id == self.tenant_id,
                record.kind.in_(("call_summary", "call")),
                record.imported_at > last,
                clean,
            )
        )
        return int(newer or 0)

    async def _refresh_synthetic(self, now: datetime) -> int:
        """Project authored call summaries (and summary-less full calls) in SQL."""
        if not self._postgres:
            return 0
        skills = """(
            SELECT CASE WHEN count(*) = 8 THEN string_agg(
                CASE s->>'state'
                    WHEN 'Strongly Demonstrated' THEN 'S'
                    WHEN 'Observed' THEN 'O'
                    WHEN 'Needs Attention' THEN 'N'
                    WHEN 'Not Applicable' THEN '-'
                    ELSE 'U' END, '' ORDER BY s->>'skill_id') END
            FROM jsonb_array_elements(
                CASE WHEN jsonb_typeof(p->'report'->'your_skills_on_this_call') = 'array'
                THEN p->'report'->'your_skills_on_this_call' ELSE '[]'::jsonb END) s
            WHERE s->>'skill_id' ~ '^skill-[1-8]$'
            HAVING count(DISTINCT s->>'skill_id') = 8
        )"""
        outcome = """CASE {value}
            WHEN 'Won' THEN 'won' WHEN 'Meeting Booked' THEN 'booked'
            WHEN 'Follow-up Set' THEN 'follow_up' WHEN 'Deferred' THEN 'deferred'
            WHEN 'Lost' THEN 'lost' WHEN 'Disqualified' THEN 'disqualified'
            ELSE 'unclear' END"""
        # A missing or non-numeric value stays NULL (greatest/least would turn NULL into a bound).
        number = (
            "(CASE WHEN jsonb_typeof({value}) = 'number' "
            "THEN least({high}, greatest(0, round(({value})::numeric))) END)"
        )
        talk = (
            "{payload}->'report'->'how_the_call_played_out'->'metrics'"
            "->'speaker_talk_share_percent'->'rep'"
        )
        upsert = """
            ON CONFLICT (tenant_id, source, call_key) DO UPDATE SET
                source_ref = excluded.source_ref, person_key = excluded.person_key,
                team_key = excluded.team_key, occurred_at = excluded.occurred_at,
                duration_ms = excluded.duration_ms, language = excluded.language,
                outcome = excluded.outcome, talk_share = excluded.talk_share,
                skills = excluded.skills, objection = excluded.objection,
                focus = excluded.focus, deal_value = excluded.deal_value,
                coaching_done = excluded.coaching_done, projected_at = excluded.projected_at
        """
        # A JSON string holding \u0000 can't become jsonb; such an authored
        # record is skipped instead of failing every batch after it.
        clean = "strpos(payload::text, '\\u0000') = 0"
        people = f"""people AS (
            SELECT DISTINCT ON (synthetic_key) synthetic_key AS rep,
                left(payload::jsonb->'fields'->>'team_id', 160) AS team
            FROM conversation_synthetic_records
            WHERE tenant_id = :tenant AND kind = 'people' AND {clean}
            ORDER BY synthetic_key, revision DESC
        )"""  # noqa: S608 - constant fragments only; values are bound parameters
        # Built only from the constant fragments above; every value is a bound parameter.
        summaries = f"""
            WITH {people},
            latest AS (
                SELECT DISTINCT ON (synthetic_key) synthetic_key, revision
                FROM conversation_synthetic_records
                WHERE tenant_id = :tenant AND kind = 'call_summary' AND {clean}
                ORDER BY synthetic_key, revision DESC
            ),
            bundles AS (
                SELECT synthetic_key, max(revision) AS revision
                FROM conversation_synthetic_records
                WHERE tenant_id = :tenant AND kind = 'call' AND {clean}
                GROUP BY synthetic_key
            ),
            todo AS (
                SELECT l.synthetic_key, l.revision, b.revision AS bundle_revision,
                    's' || l.revision || 'c' || coalesce(b.revision, 0) AS ref
                FROM latest l LEFT JOIN bundles b USING (synthetic_key)
                WHERE NOT EXISTS (
                    SELECT 1 FROM conversation_insight_calls i
                    WHERE i.tenant_id = :tenant AND i.source = 'synthetic'
                      AND i.call_key = l.synthetic_key
                      AND i.source_ref = 's' || l.revision || 'c' || coalesce(b.revision, 0)
                )
                ORDER BY l.synthetic_key
                LIMIT :limit
            ),
            -- MATERIALIZED: parse each payload once (an inlined cast re-parses per field).
            src AS MATERIALIZED (
                SELECT t.synthetic_key, t.ref, r.occurred_at,
                    r.payload::jsonb AS p, b.payload::jsonb AS bp
                FROM todo t
                JOIN conversation_synthetic_records r ON r.tenant_id = :tenant
                    AND r.kind = 'call_summary' AND r.synthetic_key = t.synthetic_key
                    AND r.revision = t.revision
                LEFT JOIN conversation_synthetic_records b ON b.tenant_id = :tenant
                    AND b.kind = 'call' AND b.synthetic_key = t.synthetic_key
                    AND b.revision = t.bundle_revision
            )
            INSERT INTO conversation_insight_calls (
                tenant_id, source, call_key, source_ref, person_key, team_key, occurred_at,
                duration_ms, language, outcome, talk_share, skills, objection, focus,
                deal_value, coaching_done, projected_at)
            SELECT :tenant, 'synthetic', t.synthetic_key, t.ref,
                left(p->>'rep_id', 160), people.team, t.occurred_at,
                {number.format(value="p->'duration_ms'", high=2147483647)}::integer,
                left(p->>'language_mix', 32),
                {outcome.format(value="p->>'outcome'")},
                {number.format(value=talk.format(payload="bp"), high=100)}::smallint,
                {skills},
                left(lower(p->>'objection'), 200),
                CASE WHEN p->>'mistake_present' = 'true' THEN left(p->>'primary_weakness', 64) END,
                {number.format(value="p->'quoted_net_value_inr'", high="1e15")}::bigint,
                {number.format(value="p->'coaching_completed_count'", high=32767)}::smallint,
                :now
            FROM src t
            LEFT JOIN people ON people.rep = p->>'rep_id'
            {upsert}
        """  # noqa: S608
        full_calls = f"""
            WITH {people},
            latest AS (
                SELECT DISTINCT ON (synthetic_key) synthetic_key, revision
                FROM conversation_synthetic_records c
                WHERE tenant_id = :tenant AND kind = 'call' AND {clean}
                  AND NOT EXISTS (
                    SELECT 1 FROM conversation_synthetic_records s
                    WHERE s.tenant_id = :tenant AND s.kind = 'call_summary'
                      AND s.synthetic_key = c.synthetic_key)
                ORDER BY synthetic_key, revision DESC
            ),
            todo AS (
                SELECT l.synthetic_key, l.revision, 'c' || l.revision AS ref
                FROM latest l
                WHERE NOT EXISTS (
                    SELECT 1 FROM conversation_insight_calls i
                    WHERE i.tenant_id = :tenant AND i.source = 'synthetic'
                      AND i.call_key = l.synthetic_key AND i.source_ref = 'c' || l.revision)
                ORDER BY l.synthetic_key
                LIMIT :limit
            ),
            src AS MATERIALIZED (
                SELECT t.synthetic_key, t.ref, r.occurred_at, r.payload::jsonb AS p
                FROM todo t
                JOIN conversation_synthetic_records r ON r.tenant_id = :tenant
                    AND r.kind = 'call' AND r.synthetic_key = t.synthetic_key
                    AND r.revision = t.revision
            )
            INSERT INTO conversation_insight_calls (
                tenant_id, source, call_key, source_ref, person_key, team_key, occurred_at,
                duration_ms, language, outcome, talk_share, skills, objection, focus,
                deal_value, coaching_done, projected_at)
            SELECT :tenant, 'synthetic', t.synthetic_key, t.ref,
                left(p->'metadata'->>'rep_id', 160), people.team, t.occurred_at,
                {number.format(value="p->'metadata'->'duration_ms'", high=2147483647)}::integer,
                left(p->'metadata'->>'language_mix', 32),
                {outcome.format(value="p->'metadata'->>'outcome'")},
                {number.format(value=talk.format(payload="p"), high=100)}::smallint,
                {skills},
                left(lower(p->'metadata'->>'objection_category'), 200),
                NULL,
                {number.format(value="p->'metadata'->'net_deal_value_inr'", high="1e15")}::bigint,
                NULL,
                :now
            FROM src t
            LEFT JOIN people ON people.rep = p->'metadata'->>'rep_id'
            {upsert}
        """  # noqa: S608
        values = {"tenant": self.tenant_id, "limit": SYNTHETIC_BATCH, "now": now}
        first = await self.database.execute(text(summaries), values)
        projected = int(getattr(first, "rowcount", 0) or 0)
        if projected < SYNTHETIC_BATCH:
            values["limit"] = SYNTHETIC_BATCH - projected
            second = await self.database.execute(text(full_calls), values)
            projected += int(getattr(second, "rowcount", 0) or 0)
        return projected

    # --- reads -----------------------------------------------------------------

    async def _where(self, filters: InsightFilters) -> list[ColumnElement[bool]]:
        row = ConversationInsightCall
        source = await self.source()
        clauses: list[ColumnElement[bool]] = [
            row.tenant_id == self.tenant_id,
            row.source == source,
            row.occurred_at < filters.until,
        ]
        if source == "call":
            # Only calls the library still shows: revoked or expired calls drop out.
            if self.scope_ids is None:
                clauses.append(literal(False))
            else:
                clauses.append(row.call_key.in_(self.scope_ids))
        if filters.since is not None:
            clauses.append(row.occurred_at >= filters.since)
        for column, value in (
            (row.person_key, filters.person),
            (row.team_key, filters.team),
            (row.outcome, filters.outcome),
            (row.language, filters.language),
        ):
            if value is not None:
                clauses.append(column == value)
        return clauses

    def _bucket(self, filters: InsightFilters) -> tuple[str, ColumnElement[Any]]:
        row = ConversationInsightCall
        span = (filters.until - filters.since) if filters.since is not None else None
        unit = "week" if span is not None and span <= timedelta(days=120) else "month"
        if self._postgres:
            local = func.timezone(INDIA, row.occurred_at)
            return unit, func.date(func.date_trunc(unit, local))
        # SQLite (unit tests): calendar month or ISO-ish week start, in UTC.
        if unit == "month":
            return unit, func.strftime("%Y-%m-01", row.occurred_at)
        return unit, func.date(row.occurred_at, "weekday 1", "-7 days")

    async def _totals(self, where: Sequence[ColumnElement[bool]]) -> dict[str, Any]:
        row = ConversationInsightCall
        result = (
            await self.database.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(row.duration_ms), 0),
                    func.count(func.distinct(row.person_key)),
                    func.sum(case((row.outcome == "won", 1), else_=0)),
                    func.sum(case((row.outcome.in_(NEXT_STEP), 1), else_=0)),
                    func.avg(row.talk_share),
                    func.count(row.talk_share),
                    func.sum(_count(row.skills, "N")),
                    func.sum(_count(row.skills, "O") + _count(row.skills, "S")),
                    func.sum(case((row.outcome == "won", row.deal_value), else_=None)),
                    func.min(row.occurred_at),
                    func.max(row.occurred_at),
                ).where(*where)
            )
        ).one()
        (
            calls,
            milliseconds,
            people,
            won,
            next_step,
            talk,
            talk_calls,
            needs,
            observed,
            value,
            first,
            last,
        ) = result
        return {
            "calls": calls,
            "minutes": round((milliseconds or 0) / 60_000),
            "people": people,
            "won": won or 0,
            "next_step": next_step or 0,
            "next_step_share": _share(next_step, calls),
            "win_share": _share(won, calls),
            "talk_share": None if talk is None else round(float(talk)),
            "talk_calls": talk_calls,
            "needs_attention_share": _share(needs, (needs or 0) + (observed or 0)),
            "won_value": None if value is None else int(value),
            "first_at": _iso(first),
            "last_at": _iso(last),
        }

    async def overview(self, filters: InsightFilters, *, now: datetime) -> dict[str, Any]:
        """Every aggregate for one window. Synthetic history is cached briefly per
        projection state (rows and last projection time), so a refresh or a new
        window always reads fresh; real calls are always read live."""
        source = await self.source()
        if source != "synthetic":
            return {**await self._overview(filters, now=now), "pending": await self.pending()}
        filters = filters.to_the_hour()
        count, projected = (
            await self.database.execute(
                select(func.count(), func.max(ConversationInsightCall.projected_at)).where(
                    ConversationInsightCall.tenant_id == self.tenant_id,
                    ConversationInsightCall.source == source,
                )
            )
        ).one()
        key = (self.tenant_id, source, filters, count, projected)
        moment = monotonic()
        cached = _CACHE.get(key)
        if cached is not None and moment - cached[0] < CACHE_SECONDS:
            _CACHE.move_to_end(key)
            result = cached[1]
        else:
            result = await self._overview(filters, now=now)
            _CACHE[key] = (moment, result)
            while len(_CACHE) > CACHE_SIZE:
                _CACHE.popitem(last=False)
        return {**result, "pending": await self.pending()}

    async def _overview(self, filters: InsightFilters, *, now: datetime) -> dict[str, Any]:
        row = ConversationInsightCall
        source = await self.source()
        where = await self._where(filters)
        totals = await self._totals(where)
        previous_filters = filters.previous()
        previous = (
            await self._totals(await self._where(previous_filters))
            if previous_filters is not None
            else None
        )
        unit, bucket = self._bucket(filters)
        needs, observed = _count(row.skills, "N"), _count(row.skills, "O") + _count(row.skills, "S")
        trend = [
            {
                "at": str(at),
                "calls": calls,
                "won": won or 0,
                "next_step": next_step or 0,
                "needs_attention_share": _share(n, (n or 0) + (o or 0)),
                "talk_share": None if talk is None else round(float(talk)),
            }
            for at, calls, won, next_step, n, o, talk in await self.database.execute(
                select(
                    bucket,
                    func.count(),
                    func.sum(case((row.outcome == "won", 1), else_=0)),
                    func.sum(case((row.outcome.in_(NEXT_STEP), 1), else_=0)),
                    func.sum(needs),
                    func.sum(observed),
                    func.avg(row.talk_share),
                )
                .where(*where)
                .group_by(bucket)
                .order_by(bucket)
            )
        ]
        # One scan: calls per outcome, and per skill strong, observed, needs
        # attention and not enough evidence (summed over the outcomes below).
        skill_columns = []
        for index in range(len(SKILL_ORDER)):
            character = func.substr(row.skills, index + 1, 1)
            for code in ("S", "O", "N", "U"):
                skill_columns.append(func.sum(case((character == code, 1), else_=0)))
        outcomes = {outcome: 0 for outcome in OUTCOMES}
        skill_totals = [0] * len(skill_columns)
        for outcome, calls, *sums in await self.database.execute(
            select(row.outcome, func.count(), *skill_columns).where(*where).group_by(row.outcome)
        ):
            outcomes[outcome] = calls
            skill_totals = [
                total + (value or 0) for total, value in zip(skill_totals, sums, strict=True)
            ]
        skills = [
            {
                "id": skill,
                "label": SKILL_LABELS[skill],
                "strong": skill_totals[index * 4] or 0,
                "observed": skill_totals[index * 4 + 1] or 0,
                "needs_attention": skill_totals[index * 4 + 2] or 0,
                "unknown": skill_totals[index * 4 + 3] or 0,
            }
            for index, skill in enumerate(SKILL_ORDER)
        ]
        people = await self._groups(row.person_key, where, filters)
        teams = await self._groups(row.team_key, where, filters) if source == "synthetic" else []
        names = await self._names([item["key"] for item in people if item["key"]])
        team_names = await self._team_names()
        for item in people:
            item["name"] = names.get(item["key"] or "", {}).get("name", "Unassigned")
            item["team"] = names.get(item["key"] or "", {}).get("team")
        for item in teams:
            item["name"] = team_names.get(item["key"] or "", "No team")
        return {
            "source": source,
            "synthetic": source == "synthetic",
            "generated_at": _iso(now),
            "window": {
                "from": _iso(filters.since),
                "to": _iso(filters.until),
                "unit": unit,
            },
            "totals": totals,
            "previous": previous,
            "trend": trend,
            "outcomes": [{"outcome": key, "calls": value} for key, value in outcomes.items()],
            "skills": skills,
            "people": people,
            "teams": teams,
            "objections": await self._objections(where),
            "mistakes": await self._mistakes(where),
            "talk": await self._talk(where),
            "calls": {
                "strongest": await self._ranked(where, strongest=True, names=names),
                "weakest": await self._ranked(where, strongest=False, names=names),
            },
            "facets": await self._facets(team_names),
        }

    async def _groups(
        self,
        key: Any,
        where: Sequence[ColumnElement[bool]],
        filters: InsightFilters,
    ) -> list[dict[str, Any]]:
        row = ConversationInsightCall
        midpoint = (
            filters.since + (filters.until - filters.since) / 2
            if filters.since is not None
            else None
        )
        columns: list[Any] = [
            key,
            func.count(),
            func.coalesce(func.sum(row.duration_ms), 0),
            func.sum(case((row.outcome == "won", 1), else_=0)),
            func.sum(case((row.outcome.in_(NEXT_STEP), 1), else_=0)),
            func.avg(row.talk_share),
            func.max(row.occurred_at),
            func.max(row.coaching_done),
        ]
        for index in range(len(SKILL_ORDER)):
            character = func.substr(row.skills, index + 1, 1)
            columns.append(func.sum(case((character.in_(("S", "O")), 1), else_=0)))
            columns.append(func.sum(case((character == "N", 1), else_=0)))
        needs = _count(row.skills, "N")
        observed = _count(row.skills, "O") + _count(row.skills, "S")
        if midpoint is not None:
            early = row.occurred_at < midpoint
            columns += [
                func.sum(case((early, needs), else_=0)),
                func.sum(case((early, observed), else_=0)),
                func.sum(case((early, 0), else_=needs)),
                func.sum(case((early, 0), else_=observed)),
            ]
        groups = []
        for values in await self.database.execute(
            select(*columns).where(*where).group_by(key).order_by(func.count().desc()).limit(200)
        ):
            (group, calls, milliseconds, won, next_step, talk, last, coaching) = values[:8]
            cells = values[8 : 8 + 2 * len(SKILL_ORDER)]
            change = None
            if midpoint is not None:
                early_n, early_o, late_n, late_o = values[8 + 2 * len(SKILL_ORDER) :]
                before = _share(early_n, (early_n or 0) + (early_o or 0))
                after = _share(late_n, (late_n or 0) + (late_o or 0))
                if before is not None and after is not None:
                    change = round(after - before, 4)
            groups.append(
                {
                    "key": group,
                    "calls": calls,
                    "minutes": round((milliseconds or 0) / 60_000),
                    "won": won or 0,
                    "next_step": next_step or 0,
                    "talk_share": None if talk is None else round(float(talk)),
                    "last_at": _iso(last),
                    "coaching_done": coaching,
                    "skills": [
                        {
                            "id": skill,
                            "observed": cells[index * 2] or 0,
                            "needs_attention": cells[index * 2 + 1] or 0,
                        }
                        for index, skill in enumerate(SKILL_ORDER)
                    ],
                    # Change in the share of skill moments needing attention,
                    # second half of the window against the first (lower is better).
                    "needs_attention_change": change,
                }
            )
        return groups

    async def _objections(self, where: Sequence[ColumnElement[bool]]) -> list[dict[str, Any]]:
        row = ConversationInsightCall
        if not self._postgres:
            return []
        kind = (
            func.unnest(func.string_to_array(row.objection, "|"))
            .table_valued("value")
            .render_derived()
        )
        statement = (
            select(
                kind.c.value,
                func.count(),
                func.sum(case((row.outcome == "won", 1), else_=0)),
            )
            .select_from(row)
            .join(kind, literal(True))
            .where(*where, row.objection.is_not(None))
            .group_by(kind.c.value)
            .order_by(func.count().desc(), kind.c.value)
            .limit(8)
        )
        return [
            {
                "kind": value,
                "label": str(value).replace("_", " ").capitalize(),
                "calls": calls,
                "won": won or 0,
            }
            for value, calls, won in await self.database.execute(statement)
        ]

    async def _mistakes(self, where: Sequence[ColumnElement[bool]]) -> list[dict[str, Any]]:
        row = ConversationInsightCall
        return [
            {
                "kind": focus,
                "label": MISTAKES.get(focus, str(focus).replace("_", " ").capitalize()),
                "calls": calls,
            }
            for focus, calls in await self.database.execute(
                select(row.focus, func.count())
                .where(*where, row.focus.is_not(None))
                .group_by(row.focus)
                .order_by(func.count().desc(), row.focus)
                .limit(6)
            )
        ]

    async def _talk(self, where: Sequence[ColumnElement[bool]]) -> list[dict[str, Any]]:
        row = ConversationInsightCall
        band = case(
            (row.talk_share < 40, literal("under_40")),
            (row.talk_share < 50, literal("40_50")),
            (row.talk_share < 60, literal("50_60")),
            (row.talk_share < 70, literal("60_70")),
            else_=literal("70_plus"),
        )
        counts: dict[str, int] = {
            key: calls
            for key, calls in await self.database.execute(
                select(band, func.count()).where(*where, row.talk_share.is_not(None)).group_by(band)
            )
        }
        labels = (
            ("under_40", "Under 40%"),
            ("40_50", "40–50%"),
            ("50_60", "50–60%"),
            ("60_70", "60–70%"),
            ("70_plus", "70% or more"),
        )
        return [{"band": key, "label": label, "calls": counts.get(key, 0)} for key, label in labels]

    async def _ranked(
        self,
        where: Sequence[ColumnElement[bool]],
        *,
        strongest: bool,
        names: Mapping[str, Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        row = ConversationInsightCall
        needs = _count(row.skills, "N")
        strong = _count(row.skills, "S")
        observed = _count(row.skills, "O")
        order = (
            (needs.asc(), strong.desc(), observed.desc(), row.occurred_at.desc())
            if strongest
            else (needs.desc(), strong.asc(), observed.asc(), row.occurred_at.desc())
        )
        rows = await self.database.execute(
            select(
                row.call_key,
                row.person_key,
                row.occurred_at,
                row.outcome,
                row.skills,
                row.duration_ms,
            )
            .where(*where, row.skills.is_not(None))
            .order_by(*order, row.call_key)
            .limit(5)
        )
        return await self._with_recordings(
            [
                self._call_row(key, person, at, outcome, skills, duration, names=names)
                for key, person, at, outcome, skills, duration in rows
            ]
        )

    def _call_row(
        self,
        key: str,
        person: str | None,
        at: datetime,
        outcome: str,
        skills: str | None,
        duration: int | None,
        *,
        names: Mapping[str, Mapping[str, Any]],
        **extra: Any,
    ) -> dict[str, Any]:
        who = names.get(person or "", {})
        return {
            "key": key,
            "person_key": person,
            "person": who.get("name", "Unassigned"),
            "team": who.get("team"),
            "at": _iso(at),
            "outcome": outcome,
            "duration_ms": duration,
            "skills": skills,
            "observed": None if skills is None else sum(c in "SO" for c in skills),
            "needs_attention": None if skills is None else skills.count("N"),
            **extra,
        }

    async def calls(
        self, filters: InsightFilters, *, offset: int = 0, limit: int = CALL_PAGE
    ) -> dict[str, Any]:
        row = ConversationInsightCall
        where = await self._where(filters)
        total = await self.database.scalar(select(func.count()).where(*where)) or 0
        rows = list(
            (
                await self.database.execute(
                    select(
                        row.call_key,
                        row.person_key,
                        row.occurred_at,
                        row.outcome,
                        row.skills,
                        row.duration_ms,
                        row.language,
                        row.talk_share,
                        row.objection,
                        row.deal_value,
                    )
                    .where(*where)
                    .order_by(row.occurred_at.desc(), row.call_key)
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        names = await self._names({person for _, person, *_ in rows if person})
        source = await self.source()
        return {
            "source": source,
            "synthetic": source == "synthetic",
            "total": total,
            "offset": offset,
            "next_offset": offset + len(rows) if offset + len(rows) < total else None,
            "items": await self._with_recordings(
                [
                    self._call_row(
                        key,
                        person,
                        at,
                        outcome,
                        skills,
                        duration,
                        names=names,
                        language=language,
                        talk_share=talk,
                        objections=[] if not objection else objection.split("|"),
                        deal_value=value,
                    )
                    for (
                        key,
                        person,
                        at,
                        outcome,
                        skills,
                        duration,
                        language,
                        talk,
                        objection,
                        value,
                    ) in rows
                ]
            ),
        }

    async def _with_recordings(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Each real call's recording, so Admin can open it in the review console."""
        if not self.recordings:
            return items
        if await self.source() != "call" or not items:
            for item in items:
                item["recording_id"] = None
            return items
        submissions = []
        for item in items:
            try:
                submissions.append(UUID(item["key"]))
            except ValueError:
                continue
        recordings = {
            str(submission): str(recording)
            for submission, recording in await self.database.execute(
                select(
                    ConversationGuestSubmission.submission_id,
                    ConversationGuestSubmission.recording_id,
                ).where(
                    ConversationGuestSubmission.tenant_id == self.tenant_id,
                    ConversationGuestSubmission.submission_id.in_(submissions),
                )
            )
        }
        for item in items:
            item["recording_id"] = recordings.get(item["key"])
        return items

    # --- names and facets ------------------------------------------------------

    async def _names(self, keys: Iterable[str]) -> dict[str, dict[str, Any]]:
        wanted = {key for key in keys if key}
        if not wanted:
            return {}
        if await self.source() == "synthetic":
            teams = await self._team_names()
            return {
                key: {
                    "name": value["name"],
                    "team": teams.get(value["team"] or "", value["team"]),
                    "team_key": value["team"],
                }
                for key, value in (await self._synthetic_people()).items()
                if key in wanted
            }
        people: dict[str, dict[str, Any]] = {}
        ids = []
        for key in wanted:
            try:
                ids.append(UUID(key))
            except ValueError:
                continue
        for person in await self.database.scalars(select(Person).where(Person.id.in_(ids))):
            people[str(person.id)] = {
                "name": person.display_name or _mask_email(person.email),
                "team": None,
            }
        return people

    async def _synthetic_people(self) -> dict[str, dict[str, Any]]:
        if not self._postgres:
            return {}
        rows = await self.database.execute(
            text(
                """
                SELECT DISTINCT ON (synthetic_key) synthetic_key,
                    left(payload::jsonb->'fields'->>'name', 120),
                    left(payload::jsonb->'fields'->>'team_id', 160),
                    left(payload::jsonb->'fields'->>'title', 60)
                FROM conversation_synthetic_records
                WHERE tenant_id = :tenant AND kind = 'people'
                  AND strpos(payload::text, '\\u0000') = 0
                ORDER BY synthetic_key, revision DESC
                """
            ),
            {"tenant": self.tenant_id},
        )
        return {
            key: {"name": name or key, "team": team, "title": title}
            for key, name, team, title in rows
        }

    async def _team_names(self) -> dict[str, str]:
        if await self.source() != "synthetic" or not self._postgres:
            return {}
        rows = await self.database.execute(
            text(
                """
                WITH teams AS (
                    SELECT DISTINCT payload::jsonb->'fields'->>'team_id' AS team, business_id
                    FROM conversation_synthetic_records
                    WHERE tenant_id = :tenant AND kind = 'people'
                  AND strpos(payload::text, '\\u0000') = 0
                ), worlds AS (
                    SELECT DISTINCT ON (synthetic_key) synthetic_key,
                        left(payload::jsonb->>'name', 120) AS name
                    FROM conversation_synthetic_records
                    WHERE tenant_id = :tenant AND kind = 'world'
                      AND strpos(payload::text, '\\u0000') = 0
                    ORDER BY synthetic_key, revision DESC
                )
                SELECT teams.team, coalesce(worlds.name, teams.business_id)
                FROM teams LEFT JOIN worlds ON worlds.synthetic_key = teams.business_id
                WHERE teams.team IS NOT NULL
                """
            ),
            {"tenant": self.tenant_id},
        )
        names: dict[str, str] = {}
        for team, name in rows:
            names[str(team)[:160]] = str(name)
        return names

    async def _facets(self, team_names: Mapping[str, str]) -> dict[str, Any]:
        row = ConversationInsightCall
        source = await self.source()
        base = [row.tenant_id == self.tenant_id, row.source == source]
        if source == "call":
            base.append(
                row.call_key.in_(self.scope_ids) if self.scope_ids is not None else literal(False)
            )
        people_keys = [
            key
            for (key,) in await self.database.execute(
                select(row.person_key).where(*base, row.person_key.is_not(None)).distinct()
            )
        ]
        names = await self._names(people_keys)
        languages = [
            value
            for (value,) in await self.database.execute(
                select(row.language).where(*base, row.language.is_not(None)).distinct()
            )
        ]
        return {
            "people": sorted(
                (
                    {
                        "key": key,
                        "name": names.get(key, {}).get("name", "Unassigned"),
                        "team": names.get(key, {}).get("team"),
                    }
                    for key in people_keys
                ),
                key=lambda item: (str(item["name"]).lower(), item["key"]),
            ),
            "teams": sorted(
                ({"key": key, "name": name} for key, name in team_names.items()),
                key=lambda item: item["name"].lower(),
            ),
            "languages": sorted(
                ({"key": key, "label": LANGUAGES.get(key, key)} for key in languages),
                key=lambda item: item["label"],
            ),
            "outcomes": list(OUTCOMES),
        }


async def erase_insights_for_recording(
    database: AsyncSession, *, tenant_id: UUID, recording_id: UUID
) -> int:
    """Purge a call's projected row when the canonical recording erasure completes.

    The row holds only codes and numbers derived from the call's report, but it
    is still call-linked data: it goes with the call, in the same transaction,
    without waiting for the next refresh.
    """
    submissions = select(cast(ConversationGuestSubmission.submission_id, String)).where(
        ConversationGuestSubmission.tenant_id == tenant_id,
        ConversationGuestSubmission.recording_id == recording_id,
    )
    result = await database.execute(
        delete(ConversationInsightCall).where(
            ConversationInsightCall.tenant_id == tenant_id,
            ConversationInsightCall.source == "call",
            ConversationInsightCall.call_key.in_(submissions),
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


def scope_columns(scope: Select[Any]) -> tuple[Select[Any], Select[Any]]:
    """The two selects OrganisationInsights needs from a library scope query."""
    from ac_platform.conversation_intelligence.acquisition_models import (
        ConversationAcquisitionUsage as Usage,
    )
    from ac_platform.conversation_intelligence.acquisition_models import (
        ConversationVisitorClaim as Claim,
    )
    from ac_platform.conversation_intelligence.models import ConversationRecording as Recording

    owner = func.coalesce(Usage.person_id, Claim.person_id)
    ids = scope.with_only_columns(cast(Usage.submission_id, String), maintain_column_froms=True)
    rows = scope.with_only_columns(
        Usage.submission_id.label("submission_id"),
        owner.label("owner"),
        Usage.created_at.label("created_at"),
        cast(Usage.reserved_seconds, Integer).label("seconds"),
        Recording.id.label("recording_id"),
        Recording.person_id.label("recording_person_id"),
        Recording.generation.label("generation"),
        maintain_column_froms=True,
    )
    return ids, rows


__all__ = [
    "InsightFilters",
    "erase_insights_for_recording",
    "OrganisationInsights",
    "objection_kinds",
    "report_language",
    "report_outcome",
    "scope_columns",
    "seller_talk_share",
    "skill_states",
]
