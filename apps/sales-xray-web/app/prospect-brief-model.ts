import type {
  ReportEvidence,
  SalesReport,
  Transcript,
} from "./report-contract";
import {
  PROSPECT_FIELD_LABELS,
  profileValueText,
  type FactLabel,
  type ProfileField,
  type ProfileKey,
} from "./prospect-profile-contract";
import type { ProspectCall, ProspectSummary } from "./prospects-client";
import { reportStoryModel, type Line } from "./report-story-model";

/**
 * Prospect's Information (binding spec 9 Oct, section 2) as six short
 * sections. Facts come from two places only: the prospect's own profile
 * (a person's edit wins and is locked; heard values carry their quote) and
 * the latest analysed call's Report. Nothing is scored or guessed; anything
 * missing is named once, as Unknown.
 */

export type BriefSource = {
  quote: string;
  start_ms: number;
  end_ms: number;
  /** The call this was heard on, when known. */
  callId?: string;
};

export type BriefFact = {
  label: string;
  value: string;
  fact: FactLabel;
  source?: BriefSource;
  /** Who set it: a person (locked) or what was heard on a call. */
  basis?: "person" | "call";
  /** A profile field a person may edit here. */
  editKey?: ProfileKey;
  earlier?: { value: string; source?: BriefSource };
  differs?: { value: string; source?: BriefSource }[];
  list?: string[];
};

export type BriefSection = {
  facts: BriefFact[];
  /** Named once, never filled in. Editable ones can be added by a person. */
  unknown: { label: string; editKey?: ProfileKey; locked?: boolean }[];
};

export type ProspectBrief = {
  name: string;
  headline: string | null;
  sections: [
    BriefSection,
    BriefSection,
    BriefSection,
    BriefSection,
    BriefSection,
    BriefSection,
  ];
  /** The call the call-based facts came from. */
  basedOn: { callId: string; label: string } | null;
  history: { callId: string; label: string; at: string; url: string }[];
};

export const BRIEF_SECTIONS = [
  {
    title: "What You Need to Know Now",
    subtitle: "Everything you need before the next conversation.",
  },
  {
    title: "What They Want — & Why",
    subtitle: "Problems, impact, goals and what matters to them.",
  },
  {
    title: "Can & Will They Buy?",
    subtitle: "Qualification without guessing.",
  },
  {
    title: "How They'll Decide",
    subtitle: "People, approvals and the decision process.",
  },
  {
    title: "What's Holding Them Back",
    subtitle: "Blockers, objections and concerns.",
  },
  {
    title: "What Happens Next",
    subtitle: "Commitments, the next event and the next move.",
  },
] as const;

export type LatestCall = {
  callId: string;
  report: SalesReport;
  transcript?: Transcript;
  roles?: { seller?: string | null; prospect?: string | null };
};

const fromEvidence = (
  evidence: ReportEvidence | undefined,
  callId?: string,
): BriefSource | undefined =>
  evidence
    ? {
        quote: evidence.quote,
        start_ms: evidence.start_ms,
        end_ms: evidence.end_ms,
        ...(callId ? { callId } : {}),
      }
    : undefined;

function profileFact(
  key: ProfileKey,
  field: ProfileField | undefined,
  label: string = PROSPECT_FIELD_LABELS[key],
): BriefFact | null {
  if (field?.state !== "known") return null;
  const source = (evidence?: {
    submission_id: string;
    quote: string;
    start_ms: number;
    end_ms: number;
  }) =>
    evidence
      ? {
          quote: evidence.quote,
          start_ms: evidence.start_ms,
          end_ms: evidence.end_ms,
          callId: evidence.submission_id,
        }
      : undefined;
  return {
    label,
    value: profileValueText(field.value),
    fact: field.heard_differently?.length
      ? "Contradiction"
      : field.changed_from
        ? "Changed"
        : "Observed",
    basis: field.basis === "person" ? "person" : "call",
    editKey: key,
    source: source(field.evidence),
    ...(field.changed_from
      ? {
          earlier: {
            value: profileValueText(field.changed_from.value),
            source: source(field.changed_from.evidence),
          },
        }
      : {}),
    ...(field.heard_differently?.length
      ? {
          differs: field.heard_differently.map((item) => ({
            value: profileValueText(item.value),
            source: source(item.evidence),
          })),
        }
      : {}),
  };
}

function lineFact(
  label: string,
  line: Line | null | undefined,
  callId: string | undefined,
): BriefFact | null {
  if (!line) return null;
  return {
    label,
    value: line.text,
    fact: line.inferred ? "Inferred" : "Observed",
    basis: "call",
    source: fromEvidence(line.sources.at(-1), callId),
  };
}

/** Sentences the prospect said about a problem or goal, in their own words. */
function ownWords(latest: LatestCall | undefined): BriefFact | null {
  const prospect = latest?.roles?.prospect;
  const transcript = latest?.transcript;
  if (!prospect || !transcript) return null;
  const said = transcript.segments.filter(
    (segment) =>
      segment.speaker_id === prospect &&
      segment.text.trim().length >= 24 &&
      /\b(want|need|problem|struggl|depend|goal|reach|grow|can't|cannot|doesn't|don't|without)\b/i.test(
        segment.text,
      ),
  );
  if (!said.length) return null;
  return {
    label: "In their own words",
    value: said[0].text,
    fact: "Observed",
    basis: "call",
    source: {
      quote: said[0].text,
      start_ms: said[0].start_ms,
      end_ms: said[0].end_ms,
      callId: latest.callId,
    },
    list: said.slice(0, 3).map((segment) => segment.text),
  };
}

function section(
  fields: Partial<Record<ProfileKey, ProfileField>>,
  entries: (BriefFact | null | undefined | false)[],
  unknown: (string | [string, ProfileKey] | false | null | undefined)[],
): BriefSection {
  const facts = entries.filter((entry): entry is BriefFact => Boolean(entry));
  const named = new Set(facts.map((fact) => fact.label));
  return {
    facts,
    unknown: unknown
      .filter((item): item is string | [string, ProfileKey] => Boolean(item))
      .map((item) => {
        if (typeof item === "string") return { label: item };
        const field = fields[item[1]];
        // A person who set "Unknown" made a decision; it stays visible and locked.
        return field?.state === "unknown" && field.locked
          ? { label: item[0], editKey: item[1], locked: true }
          : { label: item[0], editKey: item[1] };
      })
      .filter(
        (item) =>
          !named.has(item.label) &&
          !(item.editKey && fields[item.editKey]?.state === "known"),
      ),
  };
}

function callLabel(call: ProspectCall) {
  const date = new Date(call.created_at);
  const when = Number.isNaN(date.getTime())
    ? call.created_at
    : date.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  return call.display_name
    ? `${call.display_name} · ${when}`
    : `Call · ${when}`;
}

export function prospectBrief(
  prospect: ProspectSummary,
  calls: ProspectCall[],
  latest?: LatestCall,
): ProspectBrief {
  const fields = prospect.profile_fields ?? {};
  const field = (key: ProfileKey, label?: string) =>
    profileFact(key, fields[key], label);
  const story = latest
    ? reportStoryModel(latest.report, latest.transcript, {
        roles: latest.roles,
      })
    : null;
  const callId = latest?.callId;
  const deal = story?.deal;

  const role =
    fields.role?.state === "known" ? profileValueText(fields.role.value) : null;
  const business =
    fields.business?.state === "known"
      ? profileValueText(fields.business.value)
      : null;
  const headline = [role, business].filter(Boolean).join(" · ") || null;

  const stage: BriefFact | null = prospect.stage
    ? {
        label: "Deal stage",
        value: prospect.stage,
        fact: "Observed",
        basis: "person",
      }
    : deal?.outcome.status
      ? {
          label: "Deal stage",
          value: deal.outcome.status,
          fact: "Observed",
          basis: "call",
          source: fromEvidence(deal.outcome.detail?.sources.at(-1), callId),
        }
      : null;
  const nextStep =
    field("next_step") ??
    (prospect.next_step
      ? ({
          label: PROSPECT_FIELD_LABELS.next_step,
          value: prospect.next_step,
          fact: "Observed",
          basis: "person",
        } satisfies BriefFact)
      : lineFact("Next step", story?.picture.nextStep, callId));
  const actsNext: BriefFact | null =
    deal && (deal.prospectCommitments.length || deal.sellerCommitments.length)
      ? {
          label: "Who acts next",
          value:
            deal.prospectCommitments.length && deal.sellerCommitments.length
              ? "Both: you and the prospect"
              : deal.prospectCommitments.length
                ? "The prospect"
                : "You",
          fact: "Observed",
          basis: "call",
        }
      : null;
  const question: BriefFact | null = deal?.unclear[0]
    ? {
        label: "Biggest unanswered question",
        value: deal.unclear[0],
        fact: "Unknown",
        basis: "call",
      }
    : null;
  const followUp = lineFact("Follow-up", deal?.nextEvent, callId);
  const blocker = lineFact("Current blocker", deal?.blocker, callId);

  const name: BriefFact =
    field("name") ??
    ({
      label: PROSPECT_FIELD_LABELS.name,
      value: prospect.name,
      fact: "Observed",
      ...(prospect.profile_fields ? { editKey: "name" as const } : {}),
    } satisfies BriefFact);
  const now = section(
    fields,
    [
      name,
      field("role"),
      field("business"),
      field("main_pain"),
      blocker,
      field("decision_maker"),
      stage,
      nextStep,
      followUp,
      actsNext,
      question,
    ],
    [
      ["Role", "role"],
      ["Company", "business"],
      ["Main problem", "main_pain"],
      "Main goal",
      "Current blocker",
      ["Decision-maker", "decision_maker"],
      "Deal stage",
      ["Next step", "next_step"],
      "Follow-up",
      "Fit",
      "Urgency",
    ],
  );

  const want = section(
    fields,
    [
      field("industry"),
      field("team_size"),
      field("turnover", "Revenue / turnover"),
      field("city"),
      field("timeline"),
      ownWords(latest),
    ],
    [
      ["Industry", "industry"],
      ["Team size", "team_size"],
      ["Revenue / turnover", "turnover"],
      ["Main problem", "main_pain"],
      "Impact",
      "Desired outcome",
      ["Timeline", "timeline"],
      "Why it matters",
    ],
  );

  // Each value appears once: decision-maker and timeline live in their own
  // sections, so here they only count as answered.
  const buy = section(
    fields,
    [field("budget", "Budget discussed")],
    [
      "Need",
      "Desire",
      ["Budget discussed", "budget"],
      "Willingness to invest",
      fields.decision_maker?.state !== "known" && [
        "Authority",
        "decision_maker",
      ],
      "Urgency",
      fields.timeline?.state !== "known" && ["Timing", "timeline"],
      "Fit",
      "Implementation readiness",
    ],
  );

  const decide = section(
    fields,
    [
      field("decision_maker", "Main decision-maker"),
      followUp && { ...followUp, label: "Important decision event" },
    ],
    [
      ["Main decision-maker", "decision_maker"],
      "Other stakeholders",
      "Decision process",
      "Decision criteria",
      "Important decision event",
    ],
  );

  const objections: BriefFact[] = (latest?.report.objection_analysis ?? [])
    .slice(0, 3)
    .map((finding) => ({
      label: "Objection · open",
      value: `${finding.title}. ${finding.explanation}`,
      fact: "Observed",
      basis: "call",
      source: fromEvidence(finding.evidence[0], callId),
    }));
  const concerns: BriefFact[] = calls
    .flatMap((call) =>
      (call.snapshot?.interpretations ?? []).map(
        (item): BriefFact => ({
          label: "Possible concern",
          value: item.possible_concern,
          fact: "Inferred",
          basis: "call",
          source: fromEvidence(item.source.evidence[0], call.submission_id),
        }),
      ),
    )
    .filter((item) => item.value !== deal?.blocker?.text)
    .slice(0, 3);
  const holding = section(
    fields,
    [blocker, ...objections, ...concerns],
    [
      "Current blocker",
      !objections.length && "Objections",
      "Certainty",
      "Previous attempts",
      "Alternatives",
    ],
  );

  const next = section(
    fields,
    [
      deal?.action
        ? {
            label: "Recommended next move",
            value: deal.action,
            fact: "Inferred",
            basis: "call",
          }
        : null,
      followUp && { ...followUp, label: "Next event" },
      ...(deal?.prospectCommitments ?? []).map((item) =>
        lineFact("Prospect agreed to", item, callId),
      ),
      ...(deal?.sellerCommitments ?? []).map((item) =>
        lineFact("You agreed to", item, callId),
      ),
      prospect.last_promise
        ? {
            label: "Recorded commitment",
            value: prospect.last_promise,
            fact: "Observed",
            basis: "person",
          }
        : null,
      deal?.unclear.length
        ? {
            label: "Still needs to become clear",
            value: deal.unclear.join(" "),
            fact: "Unknown",
            basis: "call",
            list: deal.unclear,
          }
        : null,
    ],
    [
      ["Next step", "next_step"],
      "Next event",
      !deal?.prospectCommitments.length && "Prospect commitment",
      !deal?.sellerCommitments.length && "Your commitment",
    ],
  );

  const analysed = calls.find((call) => call.submission_id === callId);
  return {
    name: prospect.name,
    headline,
    sections: [now, want, buy, decide, holding, next],
    basedOn: analysed
      ? { callId: analysed.submission_id, label: callLabel(analysed) }
      : null,
    history: calls.map((call) => ({
      callId: call.submission_id,
      label: callLabel(call),
      at: call.created_at,
      url: call.report_url ?? call.call_url,
    })),
  };
}
