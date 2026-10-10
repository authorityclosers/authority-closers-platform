import {
  PROSPECT_FIELD_LABELS,
  parseProfileFields,
  type ProfileFields,
  type ProfileKey,
} from "./prospect-profile-contract";
export const PROSPECTS_PATH = "/prospects";
export const PROSPECTS_API = "/v1/conversation/prospects";
export const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export class ProspectsContractError extends Error {
  constructor(field: string) {
    super(`Prospects response violated contract: ${field}`);
    this.name = "ProspectsContractError";
  }
}

export type ProspectSummary = {
  prospect_id: string;
  name: string;
  revision: number;
  owner_person_id: string;
  stage: string | null;
  tags: string[];
  photo_url: string | null;
  contact: string | null;
  fields: unknown[];
  buyer_intent: unknown | null;
  next_step: string | null;
  last_promise: string | null;
  call_count: number;
  last_call: string | null;
  profile_fields?: ProfileFields;
  origin?: "person" | "detected";
  confirmed_at?: string | null;
};

export type ProspectListPage = {
  schema: string;
  prospects: ProspectSummary[];
  total: number;
  stage_filters: string[];
  next_offset: number | null;
};

export type ProspectCallSnapshotEvidence = {
  segment_id: string;
  quote: string;
  start_ms: number;
  end_ms: number;
};

export type ProspectCallSnapshotInterpretation = {
  source: {
    text: string;
    evidence: ProspectCallSnapshotEvidence[];
  };
  possible_concern: string;
  interpretation_kind: string;
};

export type ProspectCallSnapshot = {
  snapshot_id: string;
  snapshot_kind: string;
  source_revision: number;
  source_sha256: string;
  run_id: string | null;
  transcript_revision: string;
  review_status: string;
  interpretations: ProspectCallSnapshotInterpretation[];
};

export type ProspectCall = {
  submission_id: string;
  recording_id: string;
  created_at: string;
  duration_seconds: number;
  display_name: string | null;
  state: string;
  has_report: boolean;
  score: null;
  call_url: string;
  report_url: string | null;
  snapshot: ProspectCallSnapshot | null;
};

export type ProspectDetail = {
  schema: string;
  prospect: ProspectSummary;
  calls: ProspectCall[];
  next_offset: number | null;
  promises: unknown[];
  next_steps: unknown[];
  buyer_intent_history: unknown[];
};

function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ProspectsContractError("record");
  }
  return value as Record<string, unknown>;
}

export function parseProspectSummary(value: unknown): ProspectSummary {
  const item = record(value);
  if (typeof item.prospect_id !== "string" || !UUID_RE.test(item.prospect_id)) {
    throw new ProspectsContractError("prospect_id");
  }
  if (typeof item.name !== "string") {
    throw new ProspectsContractError("name");
  }
  if (
    typeof item.revision !== "number" ||
    !Number.isInteger(item.revision) ||
    item.revision < 1
  ) {
    throw new ProspectsContractError("revision");
  }
  if (
    typeof item.owner_person_id !== "string" ||
    !UUID_RE.test(item.owner_person_id)
  ) {
    throw new ProspectsContractError("owner_person_id");
  }
  if (item.stage !== null && typeof item.stage !== "string") {
    throw new ProspectsContractError("stage");
  }
  if (
    !Array.isArray(item.tags) ||
    item.tags.some((t) => typeof t !== "string")
  ) {
    throw new ProspectsContractError("tags");
  }
  if (item.photo_url !== null && typeof item.photo_url !== "string") {
    throw new ProspectsContractError("photo_url");
  }
  if (item.contact !== null && typeof item.contact !== "string") {
    throw new ProspectsContractError("contact");
  }
  if (!Array.isArray(item.fields)) {
    throw new ProspectsContractError("fields");
  }
  if (item.next_step !== null && typeof item.next_step !== "string") {
    throw new ProspectsContractError("next_step");
  }
  if (item.last_promise !== null && typeof item.last_promise !== "string") {
    throw new ProspectsContractError("last_promise");
  }
  if (
    typeof item.call_count !== "number" ||
    !Number.isInteger(item.call_count) ||
    item.call_count < 0
  ) {
    throw new ProspectsContractError("call_count");
  }
  if (item.last_call !== null && typeof item.last_call !== "string") {
    throw new ProspectsContractError("last_call");
  }

  let profileFields: ProfileFields | undefined;
  if (item.profile_fields !== undefined) {
    try {
      profileFields = parseProfileFields(item.profile_fields);
    } catch {
      throw new ProspectsContractError("profile_fields");
    }
  }
  if (
    item.origin !== undefined &&
    item.origin !== "person" &&
    item.origin !== "detected"
  )
    throw new ProspectsContractError("origin");
  if (
    item.confirmed_at !== undefined &&
    item.confirmed_at !== null &&
    typeof item.confirmed_at !== "string"
  )
    throw new ProspectsContractError("confirmed_at");
  return {
    prospect_id: item.prospect_id,
    name: item.name,
    revision: item.revision,
    owner_person_id: item.owner_person_id,
    stage: item.stage,
    tags: item.tags as string[],
    photo_url: item.photo_url,
    contact: item.contact,
    fields: item.fields,
    buyer_intent: item.buyer_intent ?? null,
    next_step: item.next_step,
    last_promise: item.last_promise,
    call_count: item.call_count,
    last_call: item.last_call,
    ...(profileFields ? { profile_fields: profileFields } : {}),
    ...(item.origin !== undefined
      ? { origin: item.origin as "person" | "detected" }
      : {}),
    ...(item.confirmed_at !== undefined
      ? { confirmed_at: item.confirmed_at as string | null }
      : {}),
  };
}

export function parseProspectListPage(value: unknown): ProspectListPage {
  const item = record(value);
  if (
    typeof item.schema !== "string" ||
    !item.schema.startsWith("ac.sales-xray.prospects/")
  ) {
    throw new ProspectsContractError("schema");
  }
  if (!Array.isArray(item.prospects)) {
    throw new ProspectsContractError("prospects");
  }
  if (
    typeof item.total !== "number" ||
    !Number.isInteger(item.total) ||
    item.total < 0
  ) {
    throw new ProspectsContractError("total");
  }
  if (
    !Array.isArray(item.stage_filters) ||
    item.stage_filters.some((s) => typeof s !== "string")
  ) {
    throw new ProspectsContractError("stage_filters");
  }
  if (
    item.next_offset !== null &&
    (typeof item.next_offset !== "number" ||
      !Number.isInteger(item.next_offset) ||
      item.next_offset < 0)
  ) {
    throw new ProspectsContractError("next_offset");
  }

  return {
    schema: item.schema,
    prospects: item.prospects.map(parseProspectSummary),
    total: item.total,
    stage_filters: item.stage_filters as string[],
    next_offset: item.next_offset,
  };
}

export function parseProspectCallSnapshot(
  value: unknown,
): ProspectCallSnapshot | null {
  if (value === null || value === undefined) return null;
  const item = record(value);
  if (typeof item.snapshot_id !== "string") {
    throw new ProspectsContractError("snapshot_id");
  }
  if (typeof item.snapshot_kind !== "string") {
    throw new ProspectsContractError("snapshot_kind");
  }
  if (typeof item.source_revision !== "number") {
    throw new ProspectsContractError("source_revision");
  }
  if (typeof item.source_sha256 !== "string") {
    throw new ProspectsContractError("source_sha256");
  }
  if (item.run_id !== null && typeof item.run_id !== "string") {
    throw new ProspectsContractError("run_id");
  }
  if (typeof item.transcript_revision !== "string") {
    throw new ProspectsContractError("transcript_revision");
  }
  if (typeof item.review_status !== "string") {
    throw new ProspectsContractError("review_status");
  }
  if (!Array.isArray(item.interpretations)) {
    throw new ProspectsContractError("interpretations");
  }

  const interpretations: ProspectCallSnapshotInterpretation[] =
    item.interpretations.map((interpRaw) => {
      const interp = record(interpRaw);
      const source = record(interp.source);
      if (typeof source.text !== "string") {
        throw new ProspectsContractError("interpretation.source.text");
      }
      if (!Array.isArray(source.evidence)) {
        throw new ProspectsContractError("interpretation.source.evidence");
      }
      const evidence: ProspectCallSnapshotEvidence[] = source.evidence.map(
        (evRaw) => {
          const ev = record(evRaw);
          if (typeof ev.segment_id !== "string") {
            throw new ProspectsContractError("evidence.segment_id");
          }
          if (typeof ev.quote !== "string") {
            throw new ProspectsContractError("evidence.quote");
          }
          if (typeof ev.start_ms !== "number") {
            throw new ProspectsContractError("evidence.start_ms");
          }
          if (typeof ev.end_ms !== "number") {
            throw new ProspectsContractError("evidence.end_ms");
          }
          return {
            segment_id: ev.segment_id,
            quote: ev.quote,
            start_ms: ev.start_ms,
            end_ms: ev.end_ms,
          };
        },
      );

      if (typeof interp.possible_concern !== "string") {
        throw new ProspectsContractError("interpretation.possible_concern");
      }
      if (typeof interp.interpretation_kind !== "string") {
        throw new ProspectsContractError("interpretation.interpretation_kind");
      }

      return {
        source: {
          text: source.text,
          evidence,
        },
        possible_concern: interp.possible_concern,
        interpretation_kind: interp.interpretation_kind,
      };
    });

  return {
    snapshot_id: item.snapshot_id,
    snapshot_kind: item.snapshot_kind,
    source_revision: item.source_revision,
    source_sha256: item.source_sha256,
    run_id: item.run_id,
    transcript_revision: item.transcript_revision,
    review_status: item.review_status,
    interpretations,
  };
}

export function parseProspectCall(value: unknown): ProspectCall {
  const item = record(value);
  if (
    typeof item.submission_id !== "string" ||
    !UUID_RE.test(item.submission_id)
  ) {
    throw new ProspectsContractError("call.submission_id");
  }
  if (
    typeof item.recording_id !== "string" ||
    !UUID_RE.test(item.recording_id)
  ) {
    throw new ProspectsContractError("call.recording_id");
  }
  if (typeof item.created_at !== "string") {
    throw new ProspectsContractError("call.created_at");
  }
  if (typeof item.duration_seconds !== "number" || item.duration_seconds < 0) {
    throw new ProspectsContractError("call.duration_seconds");
  }
  if (item.display_name !== null && typeof item.display_name !== "string") {
    throw new ProspectsContractError("call.display_name");
  }
  if (typeof item.state !== "string") {
    throw new ProspectsContractError("call.state");
  }
  if (typeof item.has_report !== "boolean") {
    throw new ProspectsContractError("call.has_report");
  }
  // Score remains strictly null; do not add or infer scoring/readiness
  if (item.score !== null) {
    throw new ProspectsContractError("call.score");
  }
  if (typeof item.call_url !== "string") {
    throw new ProspectsContractError("call.call_url");
  }
  if (item.report_url !== null && typeof item.report_url !== "string") {
    throw new ProspectsContractError("call.report_url");
  }

  return {
    submission_id: item.submission_id,
    recording_id: item.recording_id,
    created_at: item.created_at,
    duration_seconds: item.duration_seconds,
    display_name: item.display_name,
    state: item.state,
    has_report: item.has_report,
    score: null,
    call_url: item.call_url,
    report_url: item.report_url,
    snapshot: parseProspectCallSnapshot(item.snapshot),
  };
}

export function parseProspectDetail(value: unknown): ProspectDetail {
  const item = record(value);
  if (
    typeof item.schema !== "string" ||
    !item.schema.startsWith("ac.sales-xray.prospects/")
  ) {
    throw new ProspectsContractError("schema");
  }
  const prospect = parseProspectSummary(item.prospect);
  if (!Array.isArray(item.calls)) {
    throw new ProspectsContractError("calls");
  }
  const calls = item.calls.map(parseProspectCall);
  if (
    item.next_offset !== null &&
    (typeof item.next_offset !== "number" ||
      !Number.isInteger(item.next_offset) ||
      item.next_offset < 0)
  ) {
    throw new ProspectsContractError("next_offset");
  }
  if (!Array.isArray(item.promises)) {
    throw new ProspectsContractError("promises");
  }
  if (!Array.isArray(item.next_steps)) {
    throw new ProspectsContractError("next_steps");
  }
  if (!Array.isArray(item.buyer_intent_history)) {
    throw new ProspectsContractError("buyer_intent_history");
  }

  return {
    schema: item.schema,
    prospect,
    calls,
    next_offset: item.next_offset,
    promises: item.promises,
    next_steps: item.next_steps,
    buyer_intent_history: item.buyer_intent_history,
  };
}

export async function fetchProspectsList({
  search = "",
  stage = null,
  offset = 0,
  signal,
}: {
  search?: string;
  stage?: string | null;
  offset?: number;
  signal?: AbortSignal;
} = {}): Promise<ProspectListPage> {
  const params = new URLSearchParams();
  if (search.trim()) params.set("search", search.trim());
  if (stage !== null && stage !== undefined) params.set("stage", stage);
  if (offset > 0) params.set("offset", String(offset));

  const qs = params.toString();
  const url = `${PROSPECTS_API}${qs ? `?${qs}` : ""}`;
  const response = await fetch(url, {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    headers: { accept: "application/json" },
    signal,
  });

  if (!response.ok) {
    let detail: string | undefined;
    try {
      const data = await response.json();
      if (
        data &&
        typeof data === "object" &&
        typeof (data as { detail?: unknown }).detail === "string"
      ) {
        detail = (data as { detail: string }).detail;
      }
    } catch {}
    if (response.status === 401) {
      throw new Error(detail || "Sign in to read your prospects.");
    }
    if (response.status === 403) {
      throw new Error(
        detail || "Prospects are not enabled for this workspace.",
      );
    }
    if (response.status === 422) {
      throw new Error(detail || "Use the prospect page's supported filters.");
    }
    throw new Error(
      detail ||
        "Prospects could not be loaded. Try again; your completed work remains private.",
    );
  }

  const json = await response.json();
  return parseProspectListPage(json);
}

export async function fetchProspectDetail({
  prospectId,
  offset = 0,
  signal,
}: {
  prospectId: string;
  offset?: number;
  signal?: AbortSignal;
}): Promise<ProspectDetail> {
  if (!UUID_RE.test(prospectId)) {
    throw new Error("Invalid prospect identifier.");
  }
  const params = new URLSearchParams();
  if (offset > 0) params.set("offset", String(offset));
  const qs = params.toString();
  const url = `${PROSPECTS_API}/${prospectId}${qs ? `?${qs}` : ""}`;
  const response = await fetch(url, {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    headers: { accept: "application/json" },
    signal,
  });

  if (!response.ok) {
    let detail: string | undefined;
    try {
      const data = await response.json();
      if (
        data &&
        typeof data === "object" &&
        typeof (data as { detail?: unknown }).detail === "string"
      ) {
        detail = (data as { detail: string }).detail;
      }
    } catch {}
    if (response.status === 401) {
      throw new Error(detail || "Sign in to read your prospects.");
    }
    if (response.status === 403) {
      throw new Error(
        detail || "Prospects are not enabled for this workspace.",
      );
    }
    if (response.status === 404) {
      throw new Error(detail || "This prospect is unavailable.");
    }
    throw new Error(
      detail ||
        "Prospect could not be loaded. Try again; your completed work remains private.",
    );
  }

  const json = await response.json();
  return parseProspectDetail(json);
}

/** Save only a person's typed value; the server appends and locks the revision. */
export async function editProspectField(
  prospectId: string,
  revision: number,
  key: ProfileKey,
  typedText: string,
): Promise<void> {
  const max =
    key === "name" || key === "phone" ? 160 : key === "email" ? 320 : 2048;
  if (
    !UUID_RE.test(prospectId) ||
    !Number.isSafeInteger(revision) ||
    revision < 1 ||
    !Object.hasOwn(PROSPECT_FIELD_LABELS, key) ||
    !typedText.trim() ||
    typedText.length > max
  ) {
    throw new Error("Enter a value within the field's limit.");
  }
  const response = await fetch(`${PROSPECTS_API}/${prospectId}/fields`, {
    method: "PUT",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({
      expected_revision: revision,
      fields: { [key]: { kind: "text", text: typedText } },
    }),
  });
  if (!response.ok) {
    throw new Error(
      response.status === 409
        ? "This prospect changed. Reload it before saving your edit."
        : "Your edit could not be saved. Try again.",
    );
  }
  const item = record(await response.json());
  const prospect = record(item.prospect);
  if (
    item.schema !== "ac.sales-xray.prospect-fields/1" ||
    prospect.prospect_id !== prospectId ||
    !Number.isSafeInteger(prospect.revision) ||
    (prospect.revision as number) < revision
  ) {
    throw new ProspectsContractError("saved_field");
  }
  const saved = parseProfileFields(prospect.profile_fields)[key];
  if (
    saved?.state !== "known" ||
    saved.basis !== "person" ||
    !saved.locked ||
    saved.value.kind !== "text" ||
    saved.value.text !== typedText
  ) {
    throw new ProspectsContractError("saved_field");
  }
}
