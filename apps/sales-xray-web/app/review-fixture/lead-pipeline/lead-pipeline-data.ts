/**
 * Fictional data for the Lead OS fixture and its tests: the "Inside sales with
 * demos" stages, their moves (the same graph the server keeps) and a board of
 * fictional leads. No customer is named.
 */

import type {
  LeadDetail,
  LeadEvent,
  LeadRow,
  Stage,
} from "../../leads/leads-client";
import type {
  Board,
  BoardColumn,
  Group,
  GroupRow,
  MoveOption,
  Need,
  PipelineReport,
} from "../../leads/pipeline/pipeline-client";

const HOUR = 3_600_000;
const at = (hours: number) => new Date(Date.now() + hours * HOUR).toISOString();

type Spec = {
  step: string;
  label: string;
  kind: Stage;
  milestone: string;
  group: Group;
  needs: Need[];
  rot: number | null;
};

const STAGES: Spec[] = [
  {
    step: "new",
    label: "New Lead",
    kind: "new",
    milestone: "lead",
    group: "active",
    needs: [],
    rot: 1,
  },
  {
    step: "not_connected",
    label: "Not Connected",
    kind: "not_connected",
    milestone: "unreachable",
    group: "active",
    needs: ["nc_reason"],
    rot: 48,
  },
  {
    step: "interested",
    label: "Interested (In Follow-Up)",
    kind: "interested",
    milestone: "qualified",
    group: "active",
    needs: ["next_action"],
    rot: 72,
  },
  {
    step: "discussion_incomplete",
    label: "Discussion Incomplete",
    kind: "follow_up",
    milestone: "contacted",
    group: "active",
    needs: ["next_action"],
    rot: 24,
  },
  {
    step: "meeting_scheduled",
    label: "Meeting / Demo Scheduled",
    kind: "interested",
    milestone: "appointment_booked",
    group: "active",
    needs: ["meeting"],
    rot: null,
  },
  {
    step: "demo_completed",
    label: "Demo / Zoom Meeting Completed",
    kind: "interested",
    milestone: "appointment_done",
    group: "active",
    needs: ["next_action"],
    rot: 120,
  },
  {
    step: "won",
    label: "Closed / Won",
    kind: "won",
    milestone: "won",
    group: "won",
    needs: [],
    rot: null,
  },
  {
    step: "lost",
    label: "Closed / Lost",
    kind: "lost",
    milestone: "lost",
    group: "lost",
    needs: ["reason"],
    rot: null,
  },
  {
    step: "junk",
    label: "Junk Lead",
    kind: "junk",
    milestone: "disqualified",
    group: "junk",
    needs: ["reason"],
    rot: null,
  },
];

const WORKING = [
  "not_connected",
  "interested",
  "discussion_incomplete",
  "meeting_scheduled",
];
const GRAPH: Record<string, string[]> = {
  new: [...WORKING, "lost", "junk"],
  not_connected: [
    "interested",
    "discussion_incomplete",
    "meeting_scheduled",
    "lost",
    "junk",
  ],
  interested: ["discussion_incomplete", "meeting_scheduled", "lost", "junk"],
  discussion_incomplete: ["interested", "meeting_scheduled", "lost", "junk"],
  meeting_scheduled: [
    "demo_completed",
    "not_connected",
    "interested",
    "discussion_incomplete",
    "lost",
    "junk",
  ],
  demo_completed: ["won", "lost", "junk"],
  won: [
    "interested",
    "discussion_incomplete",
    "meeting_scheduled",
    "demo_completed",
    "junk",
  ],
  lost: [...WORKING, "demo_completed", "junk"],
  junk: ["new", "not_connected", "interested", "discussion_incomplete"],
};
const LOST = [
  ["not_interested", "Not interested"],
  ["chose_other", "Chose another provider"],
  ["declined_offer", "Declined the offer"],
  ["decided_not_to_proceed", "Decided not to proceed"],
  ["no_response", "No response after follow-ups"],
  ["price", "Price or budget"],
  ["not_now", "Not the right time"],
  ["not_a_fit", "Not a fit"],
  ["other", "Other"],
];
const JUNK = [
  ["fake", "Fake enquiry"],
  ["invalid_number", "Wrong or invalid number"],
  ["someone_else", "Number belongs to someone else"],
  ["unusable_contact", "Contact details unusable"],
  ["unreachable_verified", "Switched off or unreachable after checks"],
  ["spam_test", "Spam or test entry"],
  ["other", "Other"],
];
const spec = (step: string) =>
  STAGES.find((item) => item.step === step) as Spec;

export function movesFrom(step: string): MoveOption[] {
  const from = spec(step);
  return STAGES.filter((item) => GRAPH[step].includes(item.step)).map(
    (item) => ({
      step: item.step,
      label: item.label,
      kind: item.kind,
      milestone: item.milestone,
      group: item.group,
      action:
        from.group !== "active"
          ? item.group === "active"
            ? "reopen"
            : "reclassify"
          : item.group === "active"
            ? "move"
            : "close",
      needs: item.needs,
      asks: [
        ...(item.group === "lost" ||
        item.group === "won" ||
        item.group === "junk"
          ? (["confirm"] as Need[])
          : []),
        ...(item.kind === "not_connected" ? (["next_action"] as Need[]) : []),
        "note",
      ],
      reasons: (item.group === "lost"
        ? LOST
        : item.group === "junk"
          ? JUNK
          : []
      ).map(([key, label]) => ({ key, label })),
    }),
  );
}

const OWNER = "00000000-0000-4000-8000-000000000002";

function row(
  index: number,
  name: string,
  step: string,
  extra: Partial<LeadRow> = {},
): LeadRow {
  const item = spec(step);
  return {
    lead_id: `00000000-0000-4000-9000-${String(index).padStart(12, "0")}`,
    revision: 3,
    name,
    company: null,
    city: "Pune",
    language: null,
    interest: "Demo",
    phone_last4: String(4300 + index),
    stage: item.kind,
    stage_label: item.label,
    source: "meta",
    source_label: "Meta lead form",
    owner_person_id: OWNER,
    owner_name: index % 2 ? "kavya fictional" : "arjun sample",
    why: item.label,
    why_kind: item.group === "active" ? "open" : "closed",
    next_action_at: item.group === "active" ? at(5 + index) : null,
    created_at: at(-30 - index * 6),
    attempts: 1,
    calls: 1,
    last_result: null,
    last_result_label: null,
    test_data: true,
    step,
    pipeline: "main",
    stage_at: at(-(index % 4 === 0 ? 90 : 3)),
    group: item.group,
    last_contact_at: at(-2 - index),
    no_next_action: false,
    ...extra,
  };
}

export const CARDS: Record<string, LeadRow[]> = {
  new: [
    row(1, "asha fictional", "new", {
      next_action_at: null,
      overdue: true,
      last_contact_at: null,
      why: "New lead · Meta lead form",
    }),
    row(2, "rohan sample", "new", {
      next_action_at: null,
      last_contact_at: null,
      why: "New lead · Website form",
    }),
  ],
  not_connected: [
    row(3, "meera fictional", "not_connected", {
      next_action_at: at(-3),
      overdue: true,
      why: "Try again · did not pick · 2 tries",
    }),
    row(4, "vikram sample", "not_connected", {
      why: "Try again · busy in another call · 1 try",
    }),
  ],
  interested: [
    row(5, "neha fictional", "interested", {
      next_action_note: "Wants the brochure on WhatsApp",
    }),
    row(6, "farhan sample", "interested", {
      next_action_at: null,
      no_next_action: true,
      why: "Interested (In Follow-Up)",
    }),
  ],
  discussion_incomplete: [
    row(7, "pooja fictional", "discussion_incomplete", {
      next_action_note: "Driving; call this evening",
    }),
  ],
  meeting_scheduled: [
    row(8, "sanjay sample", "meeting_scheduled", {
      next_action_at: at(26),
      next_action_note: "Zoom meeting",
    }),
  ],
  demo_completed: [
    row(9, "divya fictional", "demo_completed", {
      next_action_note: "Discussing with her partner",
    }),
  ],
  won: [row(10, "kiran sample", "won")],
  lost: [
    row(11, "anil fictional", "lost", {
      outcome_reason: "price",
      outcome_reason_label: "Price or budget",
    }),
  ],
  junk: [
    row(12, "test entry", "junk", {
      outcome_reason: "fake",
      outcome_reason_label: "Fake enquiry",
    }),
  ],
};

export function fixtureBoard(): Board {
  const columns: BoardColumn[] = STAGES.map((item) => {
    const cards = CARDS[item.step] ?? [];
    return {
      step: item.step,
      label: item.label,
      kind: item.kind,
      milestone: item.milestone,
      count:
        cards.length + (item.step === "lost" ? 6 : item.step === "won" ? 3 : 0),
      overdue: cards.filter((card) => card.overdue).length,
      no_next: cards.filter((card) => card.no_next_action).length,
      cards,
      next_cursor: null,
      rot_hours: item.rot,
      moves: movesFrom(item.step),
    };
  });
  const groups = (["active", "won", "lost", "junk"] as const).map((group) => {
    const own = columns.filter((column) => spec(column.step).group === group);
    return {
      group,
      label: { active: "Active", won: "Won", lost: "Lost", junk: "Junk" }[
        group
      ],
      count: own.reduce((sum, column) => sum + column.count, 0),
      columns: own,
    };
  });
  return {
    pipeline: "main",
    version: 4,
    total: groups.reduce((sum, group) => sum + group.count, 0),
    groups,
    generated_at: new Date().toISOString(),
  };
}

const event = (
  hours: number,
  fields: Partial<LeadEvent> & Pick<LeadEvent, "kind">,
): LeadEvent => ({
  at: at(hours),
  actor_name: "kavya fictional",
  stage: null,
  stage_label: null,
  reason: null,
  reason_label: null,
  connected: null,
  note: null,
  next_action_at: null,
  owner_name: null,
  previous_owner_name: null,
  allocation_reason: null,
  source_label: null,
  submission_id: null,
  simulated: null,
  duration_seconds: null,
  ...fields,
});

const EVENTS: LeadEvent[] = [
  event(-2, {
    kind: "meeting",
    meeting_action: "rescheduled",
    starts_at: at(26),
    from_starts_at: at(4),
    mode_label: "Zoom",
  }),
  event(-20, {
    kind: "stage",
    action: "move",
    from_label: "Discussion Incomplete",
    stage_label: "Meeting / Demo Scheduled",
    move_source: "seller",
  }),
  event(-20.1, {
    kind: "meeting",
    meeting_action: "scheduled",
    starts_at: at(4),
    mode_label: "Zoom",
  }),
  event(-30, {
    kind: "result",
    connected: true,
    action: "move",
    from_label: "Interested (In Follow-Up)",
    stage_label: "Discussion Incomplete",
    note: "Busy at work, asked to talk tomorrow",
    move_source: "seller",
  }),
  event(-52, {
    kind: "result",
    connected: true,
    action: "move",
    from_label: "Not Connected",
    stage_label: "Interested (In Follow-Up)",
    move_source: "ai_suggestion",
  }),
  event(-70, {
    kind: "result",
    connected: false,
    action: "move",
    from_label: "New Lead",
    stage_label: "Not Connected",
    reason: "did_not_pick",
    reason_label: "Did not pick",
    move_source: "seller",
  }),
  event(-71, {
    kind: "assigned",
    actor_name: null,
    owner_name: "kavya fictional",
    allocation_reason: "Speaks Marathi",
  }),
  event(-72, {
    kind: "captured",
    actor_name: null,
    source_label: "Meta lead form",
  }),
];

export const LEAD = row(8, "sanjay sample", "meeting_scheduled", {
  next_action_at: at(26),
});

export function fixtureDetail(): LeadDetail {
  return {
    lead: LEAD,
    phone: "+919876504308",
    email: null,
    owner_reason: null,
    next_action_note: "Zoom meeting",
    fields: [],
    source_fields: [],
    events: EVENTS,
    can_edit: true,
    can_assign: true,
    reps: [],
    call_mode: "phone",
    moves: movesFrom("meeting_scheduled"),
    meeting: {
      meeting_id: "00000000-0000-4000-a000-000000000001",
      revision: 2,
      status: "scheduled",
      starts_at: at(26),
      duration_minutes: 30,
      mode: "zoom",
      mode_label: "Zoom",
      link: "https://zoom.us/j/1234567890",
      location: null,
      agenda: "Plan walkthrough",
      outcome_note: null,
      host_person_id: OWNER,
      host_name: "kavya fictional",
    },
  };
}

const tally = (label: string, extra: Partial<GroupRow>): GroupRow => ({
  key: label,
  label,
  leads: 0,
  active: 0,
  overdue: 0,
  no_next: 0,
  created: 0,
  connected: 0,
  junk: 0,
  won: 0,
  meetings: 0,
  connect_rate: null,
  junk_rate: null,
  first_response_minutes: null,
  ...extra,
});

/** The pipeline's numbers for the fictional team (counts only). */
export function fixtureReport(): PipelineReport {
  const board = fixtureBoard();
  const columns = board.groups.flatMap((group) => group.columns);
  return {
    pipeline: "main",
    days: 30,
    generated_at: new Date().toISOString(),
    total: board.total,
    enough: true,
    groups: Object.fromEntries(
      board.groups.map((group) => [group.group, group.count]),
    ),
    stages: columns.map((column) => ({
      step: column.step,
      label: column.label,
      kind: column.kind,
      group: spec(column.step).group,
      count: column.count,
    })),
    first_connect: {
      key: "new_to_connect",
      label: "New lead to a first conversation",
      entered: 18,
      passed: 13,
      rate: 0.722,
    },
    first_connect_minutes: 14,
    conversions: [
      {
        key: "interested_to_meeting",
        label: "Interested to a meeting booked",
        entered: 9,
        passed: 5,
        rate: 0.556,
      },
      {
        key: "meeting_to_held",
        label: "Meeting booked to meeting held",
        entered: 5,
        passed: 4,
        rate: 0.8,
      },
      {
        key: "held_to_won",
        label: "Meeting held to Won",
        entered: 4,
        passed: 3,
        rate: 0.75,
      },
    ],
    show_rate: 0.8,
    lost_now: [
      { label: "Price or budget", count: 3 },
      { label: "Not the right time", count: 2 },
      { label: "Chose another provider", count: 1 },
      { label: "Not recorded", count: 1 },
    ],
    lost_moves: [{ label: "Price or budget", count: 2 }],
    junk_now: 1,
    junk_moves: 1,
    overdue: 2,
    no_next: 1,
    sellers: [
      tally("Kavya Fictional", {
        won: 2,
        active: 5,
        overdue: 1,
        meetings: 1,
        first_response_minutes: 9,
      }),
      tally("Arjun Sample", {
        won: 1,
        active: 4,
        overdue: 1,
        no_next: 1,
        first_response_minutes: 21,
      }),
    ],
    sources: [
      tally("Meta lead form", {
        created: 12,
        connected: 8,
        junk: 2,
        connect_rate: 0.8,
        junk_rate: 0.167,
      }),
      tally("Website form", {
        created: 6,
        connected: 5,
        junk: 0,
        connect_rate: 0.833,
        junk_rate: 0,
      }),
    ],
    mine: false,
  };
}
