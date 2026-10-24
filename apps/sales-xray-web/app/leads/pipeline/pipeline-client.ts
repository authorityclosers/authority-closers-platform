/**
 * Lead OS (24 Oct 2026): the pipeline board, stage moves, reopen and meetings
 * (/v1/lead-desk). One lead, one current stage: every move changes the same
 * record and adds one line to its history. The server checks each move against
 * the business's stage list; the board and the stage sheet show only the moves
 * it allows (each column carries them) and ask only for what each one needs.
 */

import {
  commandId,
  deskJson,
  deskRequest,
  readLead,
  type LeadDetail,
  type LeadRow,
} from "../leads-client";

export type Group = "active" | "won" | "lost" | "junk";
export type MoveAction = "move" | "close" | "reopen" | "reclassify";
/** What a stage asks for on the way in (needs are required, asks offered). */
export type Need =
  | "next_action"
  | "meeting"
  | "reason"
  | "nc_reason"
  | "reason_note"
  | "note"
  | "confirm";

export type Reason = { key: string; label: string };

export type MoveOption = {
  step: string;
  label: string;
  kind: string;
  milestone?: string;
  group: Group;
  action: MoveAction;
  needs: Need[];
  asks: Need[];
  reasons: Reason[];
};

export type BoardColumn = {
  step: string;
  label: string;
  kind: string;
  milestone: string;
  count: number;
  overdue: number;
  no_next: number;
  cards: LeadRow[];
  next_cursor: string | null;
  rot_hours: number | null;
  moves: MoveOption[];
};

export type BoardGroup = {
  group: Group;
  label: string;
  count: number;
  columns: BoardColumn[];
};

export type Board = {
  pipeline: string;
  version: number;
  total: number;
  groups: BoardGroup[];
  generated_at: string;
};

export type MeetingMode =
  | "zoom"
  | "google_meet"
  | "phone"
  | "in_person"
  | "other";

export const MEETING_MODES: { key: MeetingMode; label: string }[] = [
  { key: "zoom", label: "Zoom" },
  { key: "google_meet", label: "Google Meet" },
  { key: "phone", label: "Phone call" },
  { key: "in_person", label: "In person" },
];

export type MeetingInput = {
  starts_at: string;
  duration_minutes?: number;
  mode: MeetingMode;
  link?: string;
  location?: string;
  agenda?: string;
};

export type MeetingView = {
  meeting_id: string;
  revision: number;
  status: "scheduled" | "done" | "missed" | "cancelled";
  starts_at: string;
  duration_minutes: number;
  mode: MeetingMode;
  mode_label: string;
  link: string | null;
  location: string | null;
  agenda: string | null;
  outcome_note: string | null;
  host_person_id: string | null;
  host_name: string | null;
};

export type BoardFilters = {
  pipeline?: string | null;
  owner?: string | null;
  source?: string | null;
  q?: string;
};

function boardQuery(filters: BoardFilters, extra: Record<string, string> = {}) {
  const query = new URLSearchParams(extra);
  if (filters.pipeline) query.set("pipeline", filters.pipeline);
  if (filters.owner) query.set("owner", filters.owner);
  if (filters.source) query.set("source", filters.source);
  if (filters.q?.trim()) query.set("q", filters.q.trim().slice(0, 80));
  const asked = query.toString();
  return asked ? `?${asked}` : "";
}

/** Every live stage as a column, each lead in exactly one. */
export function readBoard(filters: BoardFilters = {}, signal?: AbortSignal) {
  return deskRequest<Board>(`/board${boardQuery(filters)}`, { signal });
}

/** The next cards of one column ("Show more"). */
export async function readColumn(
  step: string,
  cursor: string,
  filters: BoardFilters = {},
  signal?: AbortSignal,
): Promise<BoardColumn | null> {
  const board = await deskRequest<Board>(
    `/board/column${boardQuery(filters, { step, cursor })}`,
    { signal },
  );
  return board.groups.flatMap((group) => group.columns)[0] ?? null;
}

/** What a seller gives with a move: only what the stage asks for. */
export type MoveInput = {
  note?: string;
  reason?: string;
  reasonNote?: string;
  ncReason?: string;
  nextActionAt?: string;
  nextActionNote?: string;
  meeting?: {
    startsAt: string;
    durationMinutes?: number;
    mode: MeetingMode;
    link?: string;
    location?: string;
    agenda?: string;
  };
  contact?: "call" | "reply" | "seller_said";
  source?: "seller" | "ai_suggestion";
  suggestionRef?: string;
  via?:
    | "board"
    | "sheet"
    | "after_call"
    | "table"
    | "bulk"
    | "meeting"
    | "chat";
};

export type Moved = {
  leadId: string;
  revision: number;
  stage: string;
  step: string;
  stepLabel: string;
  stageAt: string | null;
  meetingId: string | null;
};

function clean<T extends object>(value: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(value).filter(([, item]) => item !== "" && item != null),
  ) as Partial<T>;
}

/** Move a lead to one of its stages (board, stage sheet, table). */
export function moveLead(
  lead: Pick<LeadRow, "lead_id" | "revision">,
  step: string,
  input: MoveInput = {},
  command = commandId(),
) {
  return deskRequest<Moved>(
    `/leads/${encodeURIComponent(lead.lead_id)}/stage`,
    deskJson("POST", {
      commandId: command,
      expectedRevision: lead.revision,
      step,
      ...clean(input),
    }),
  );
}

/** Back to work from Won, Lost or Junk: the stage it was closed from by default. */
export function reopenLead(
  lead: Pick<LeadRow, "lead_id" | "revision">,
  input: { step?: string; next_action_at?: string; note?: string },
  command = commandId(),
) {
  return deskRequest<LeadDetail>(
    `/leads/${encodeURIComponent(lead.lead_id)}/reopen`,
    deskJson("POST", {
      command_id: command,
      expected_revision: lead.revision,
      ...clean(input),
    }),
  );
}

/** Book the lead's meeting, or move the one booked (it stays one meeting). */
export function scheduleMeeting(
  lead: Pick<LeadRow, "lead_id" | "revision">,
  meeting: MeetingInput,
  command = commandId(),
) {
  return deskRequest<LeadDetail>(
    `/leads/${encodeURIComponent(lead.lead_id)}/meetings`,
    deskJson("POST", {
      command_id: command,
      expected_revision: lead.revision,
      meeting: clean(meeting),
    }),
  );
}

/** It happened: the lead goes to the meeting-held stage. */
export function meetingDone(
  lead: Pick<LeadRow, "revision">,
  meetingId: string,
  input: { note?: string; next_action_at?: string },
  command = commandId(),
) {
  return deskRequest<LeadDetail>(
    `/meetings/${encodeURIComponent(meetingId)}/done`,
    deskJson("POST", {
      command_id: command,
      expected_revision: lead.revision,
      ...clean(input),
    }),
  );
}

/** Missed or cancelled: where the lead stands now. */
export function meetingNotHeld(
  lead: Pick<LeadRow, "revision">,
  meetingId: string,
  input: {
    status: "missed" | "cancelled";
    step: string;
    nc_reason?: string;
    next_action_at?: string;
    note?: string;
  },
  command = commandId(),
) {
  return deskRequest<LeadDetail>(
    `/meetings/${encodeURIComponent(meetingId)}/not-held`,
    deskJson("POST", {
      command_id: command,
      expected_revision: lead.revision,
      ...clean(input),
    }),
  );
}

/* ---------- the pipeline's numbers ---------- */

export type ReportPeriod = 7 | 30 | 90;

export type Conversion = {
  key: string;
  label: string;
  entered: number;
  passed: number;
  rate: number | null;
};

export type GroupRow = {
  key: string;
  label: string;
  leads: number;
  active: number;
  overdue: number;
  no_next: number;
  created: number;
  connected: number;
  junk: number;
  won: number;
  meetings: number;
  connect_rate: number | null;
  junk_rate: number | null;
  first_response_minutes: number | null;
};

export type PipelineReport = {
  pipeline: string;
  days: number;
  generated_at: string;
  total: number;
  enough: boolean;
  groups: Record<string, number>;
  stages: {
    step: string;
    label: string;
    kind: string;
    group: Group;
    count: number;
  }[];
  first_connect: Conversion;
  first_connect_minutes: number | null;
  conversions: Conversion[];
  show_rate: number | null;
  lost_now: { label: string; count: number }[];
  lost_moves: { label: string; count: number }[];
  junk_now: number;
  junk_moves: number;
  overdue: number;
  no_next: number;
  sellers: GroupRow[];
  sources: GroupRow[];
  mine: boolean;
};

/** Each lead counted once; conversions from history, Junk left out. */
export function readPipelineReport(
  { days, pipeline }: { days: ReportPeriod; pipeline?: string | null },
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({ days: String(days) });
  if (pipeline) query.set("pipeline", pipeline);
  return deskRequest<PipelineReport>(`/reports/pipeline?${query}`, { signal });
}

/** After a move, the lead as it stands (its new revision, history and moves). */
export function readMoved(moved: Pick<Moved, "leadId">) {
  return readLead(moved.leadId);
}
