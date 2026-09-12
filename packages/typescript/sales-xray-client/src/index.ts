export type Presentation = "standalone" | "lms" | "free-course" | "website";
export const presentations: readonly Presentation[] = [
  "standalone",
  "lms",
  "free-course",
  "website",
];
export interface TranscriptSegment {
  id: string;
  speaker_id: string;
  start_ms: number;
  end_ms: number;
  text: string;
}
export interface ConversationCapabilities {
  product: "Sales Xray";
  intake: "unavailable" | "enabled";
  provider_processing: "disabled";
  numeric_publication: "withheld";
  reasons: string[];
}
export interface ChannelMeasurement {
  channel_index?: number;
  measurement?: string;
  label: string;
  unit: string;
  clock: string;
  window_ms: number;
  hop_ms: number;
  display_stride?: number;
  points: { start_ms: number; value: number | null }[];
}
export interface ConversationExample {
  id: string;
  title: string;
  duration_ms: number;
  state: "example";
  transcript: {
    segments: TranscriptSegment[];
    revision?: string;
    provenance?: string;
  };
  measurements: Record<string, unknown>;
  profile: {
    name: string;
    declared_total: 100;
    source_total: 95;
    numeric_score: null;
  };
}
export interface LocalCheckpoint {
  schema_version: "sales-xray-checkpoint.v1";
  run_id: string;
  revision: string;
  source: {
    sha256: string;
    duration_ms: number;
    name?: string;
    provenance: string;
  };
  transcript: {
    segments: TranscriptSegment[];
    revision: string;
    provenance: string;
  };
  channels: ChannelMeasurement[];
  signal_metadata?: {
    schema: string;
    source_rate: number;
    source_channels: number;
    source_codec: string;
    source_track_start_seconds: number | null;
    source_track_time_base: string | null;
    source_mapping_status: string;
    container_video_sync_certified: false;
    feature_sha256: string;
    decoded_rate: number;
    decoded_channels: number;
    rows: number;
  };
}
const record = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const bounded = (v: unknown, max = 200): v is string =>
  typeof v === "string" && v.length > 0 && v.length <= max;
const finite = (v: unknown): v is number =>
  typeof v === "number" && Number.isFinite(v) && v >= 0;
export function parseSegments(
  value: unknown,
  duration: number,
): TranscriptSegment[] {
  if (!Array.isArray(value) || value.length > 10000)
    throw new Error("The transcript segment list is invalid or too large.");
  const ids = new Set<string>();
  return value.map((v) => {
    if (
      !record(v) ||
      !bounded(v.id) ||
      ids.has(v.id) ||
      !bounded(v.speaker_id) ||
      !finite(v.start_ms) ||
      !finite(v.end_ms) ||
      v.end_ms <= v.start_ms ||
      v.end_ms > duration ||
      !bounded(v.text, 20000)
    )
      throw new Error(
        "A transcript segment has missing identity, text, or invalid source timing.",
      );
    ids.add(v.id);
    return {
      id: v.id,
      speaker_id: v.speaker_id,
      start_ms: v.start_ms,
      end_ms: v.end_ms,
      text: v.text,
    };
  });
}
export function validateCheckpoint(v: unknown): LocalCheckpoint {
  if (record(v) && v.schema === "ac.sales-xray.signal-checkpoint/1")
    return validateSignalCheckpoint(v);
  if (
    !record(v) ||
    v.schema_version !== "sales-xray-checkpoint.v1" ||
    !bounded(v.run_id) ||
    !bounded(v.revision) ||
    !record(v.source) ||
    typeof v.source.sha256 !== "string" ||
    !/^[a-f0-9]{64}$/.test(v.source.sha256) ||
    !finite(v.source.duration_ms) ||
    v.source.duration_ms === 0 ||
    !bounded(v.source.provenance, 4000) ||
    !record(v.transcript) ||
    !bounded(v.transcript.revision) ||
    !bounded(v.transcript.provenance, 4000)
  )
    throw new Error(
      "Use a Sales Xray checkpoint with a source SHA-256, source clock, transcript revision and provenance.",
    );
  const segments = parseSegments(v.transcript.segments, v.source.duration_ms);
  if (!Array.isArray(v.channels) || v.channels.length > 16)
    throw new Error("The checkpoint channel list is invalid.");
  const channels = v.channels.map((c) => {
    if (
      !record(c) ||
      !bounded(c.label) ||
      !bounded(c.unit) ||
      !bounded(c.clock) ||
      !finite(c.window_ms) ||
      c.window_ms === 0 ||
      !finite(c.hop_ms) ||
      c.hop_ms === 0 ||
      !Array.isArray(c.points) ||
      c.points.length > 5000
    )
      throw new Error(
        "Each measurement channel needs its own clock, window and hop.",
      );
    let last = -1;
    const duration = v.source as Record<string, unknown>;
    const points = c.points.map((p) => {
      if (
        !record(p) ||
        !finite(p.start_ms) ||
        p.start_ms <= last ||
        p.start_ms > (duration.duration_ms as number) ||
        (p.value !== null &&
          (typeof p.value !== "number" || !Number.isFinite(p.value)))
      )
        throw new Error(
          "Measurement points must be finite or null and ordered on the source clock.",
        );
      last = p.start_ms;
      return { start_ms: p.start_ms, value: p.value };
    });
    return {
      label: c.label,
      unit: c.unit,
      clock: c.clock,
      window_ms: c.window_ms,
      hop_ms: c.hop_ms,
      points,
    };
  });
  return {
    schema_version: "sales-xray-checkpoint.v1",
    run_id: v.run_id,
    revision: v.revision,
    source: {
      sha256: v.source.sha256,
      duration_ms: v.source.duration_ms,
      provenance: v.source.provenance,
      ...(bounded(v.source.name) ? { name: v.source.name } : {}),
    },
    transcript: {
      segments,
      revision: v.transcript.revision,
      provenance: v.transcript.provenance,
    },
    channels,
  };
}
function validateSignalCheckpoint(v: Record<string, unknown>): LocalCheckpoint {
  const a = v.acoustics;
  const t = v.timebase;
  const d = v.display;
  if (
    v.stage !== "C1" ||
    typeof v.source_sha256 !== "string" ||
    !/^[a-f0-9]{64}$/.test(v.source_sha256) ||
    typeof v.feature_sha256 !== "string" ||
    !/^[a-f0-9]{64}$/.test(v.feature_sha256) ||
    !finite(v.source_rate) ||
    !finite(v.source_channels) ||
    !bounded(v.source_codec) ||
    !record(a) ||
    a.format !== "ac.audioatlas.features/1" ||
    a.source_sha256 !== v.source_sha256 ||
    a.feature_sha256 !== v.feature_sha256 ||
    !finite(a.rate) ||
    a.rate === 0 ||
    !finite(a.sample_count) ||
    a.sample_count === 0 ||
    !finite(a.channels) ||
    !finite(a.rows) ||
    !finite(a.window_samples) ||
    a.window_samples === 0 ||
    !finite(a.hop_samples) ||
    a.hop_samples === 0 ||
    !record(t) ||
    t.clock !== "decoded_audio_track" ||
    t.rate !== a.rate ||
    t.container_video_sync_certified !== false ||
    !bounded(t.source_mapping_status) ||
    !record(d) ||
    !Array.isArray(d.channels) ||
    d.channels.length > 2
  )
    throw new Error(
      "The C1 checkpoint has incompatible source, feature or decoded-clock metadata.",
    );
  const duration = (a.sample_count / a.rate) * 1000;
  const channels: ChannelMeasurement[] = [];
  for (const c of d.channels) {
    if (
      !record(c) ||
      !finite(c.channel) ||
      c.channel >= a.channels ||
      !finite(c.display_stride) ||
      c.display_stride < 1 ||
      !Array.isArray(c.time_s) ||
      c.time_s.length > 5000 ||
      !Array.isArray(c.dbfs) ||
      !Array.isArray(c.f0_hz) ||
      c.dbfs.length !== c.time_s.length ||
      c.f0_hz.length !== c.time_s.length
    )
      throw new Error("The C1 display channels are invalid or too large.");
    for (const [key, label, unit] of [
      ["dbfs", "Level", "dBFS"],
      ["f0_hz", "Fundamental frequency", "Hz"],
    ] as const) {
      let last = -1;
      const values = c[key] as unknown[];
      const points = c.time_s.map((time, index) => {
        const value = values[index];
        if (
          !finite(time) ||
          time <= last ||
          time * 1000 > duration ||
          (value !== null &&
            (typeof value !== "number" || !Number.isFinite(value)))
        )
          throw new Error(
            "C1 measurement points must retain ordered decoded-track times and finite or null values.",
          );
        last = time;
        return { start_ms: time * 1000, value: value as number | null };
      });
      channels.push({
        channel_index: c.channel,
        measurement: key,
        label: `Channel ${c.channel + 1} · ${label}`,
        unit,
        clock: "decoded_audio_track",
        window_ms: (a.window_samples / a.rate) * 1000,
        hop_ms: (a.hop_samples / a.rate) * 1000,
        display_stride: c.display_stride,
        points,
      });
    }
  }
  return {
    schema_version: "sales-xray-checkpoint.v1",
    run_id: `c1-${v.source_sha256.slice(0, 24)}`,
    revision: v.feature_sha256,
    source: {
      sha256: v.source_sha256,
      duration_ms: duration,
      name: "Local audio · acoustic checkpoint",
      provenance:
        "Native AudioAtlas C1 measurements. Decoded audio-track clock; source origin, codec delay and container/video synchronization remain uncertified.",
    },
    transcript: {
      segments: [],
      revision: "unavailable-C1-only",
      provenance:
        "C1 acoustic checkpoint only. No transcript, speaker attribution or sales inference was performed.",
    },
    channels,
    signal_metadata: {
      schema: "ac.sales-xray.signal-checkpoint/1",
      source_rate: v.source_rate,
      source_channels: v.source_channels,
      source_codec: v.source_codec,
      source_track_start_seconds:
        typeof t.source_track_start_seconds === "number" &&
        Number.isFinite(t.source_track_start_seconds)
          ? t.source_track_start_seconds
          : null,
      source_track_time_base:
        typeof t.source_track_time_base === "string"
          ? t.source_track_time_base
          : null,
      source_mapping_status: t.source_mapping_status,
      container_video_sync_certified: false,
      feature_sha256: v.feature_sha256,
      decoded_rate: a.rate,
      decoded_channels: a.channels,
      rows: a.rows,
    },
  };
}
export function createEntryUrl(input: {
  origin: string;
  allowedOrigins: readonly string[];
  presentation: Presentation;
  runId?: string;
}): string {
  const origin = new URL(input.origin);
  if (
    origin.username ||
    origin.password ||
    origin.pathname !== "/" ||
    origin.search ||
    origin.hash ||
    !input.allowedOrigins.includes(origin.origin) ||
    !(
      origin.protocol === "https:" ||
      (origin.protocol === "http:" &&
        ["localhost", "127.0.0.1"].includes(origin.hostname))
    ) ||
    !presentations.includes(input.presentation)
  )
    throw new Error(
      "Sales Xray requires an approved exact origin and presentation.",
    );
  const url = new URL("/", origin);
  url.searchParams.set("presentation", input.presentation);
  if (input.runId !== undefined) {
    if (!/^[a-zA-Z0-9_-]{1,128}$/.test(input.runId))
      throw new Error("Invalid run identifier.");
    url.searchParams.set("run", input.runId);
  }
  return url.toString();
}
async function read(path: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(`/v1/conversation/${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok)
    throw new Error(
      response.status === 401 || response.status === 403
        ? "This view needs an authorized AC session."
        : "The conversation service is unavailable. Your local files are unchanged.",
    );
  return response.json();
}
export async function loadCapabilities(
  signal?: AbortSignal,
): Promise<ConversationCapabilities> {
  const v = await read("capabilities", signal);
  if (
    !record(v) ||
    v.product !== "Sales Xray" ||
    !["unavailable", "enabled"].includes(String(v.intake)) ||
    v.provider_processing !== "disabled" ||
    v.numeric_publication !== "withheld" ||
    !Array.isArray(v.reasons) ||
    v.reasons.some((r) => typeof r !== "string")
  )
    throw new Error(
      "The service capabilities are incompatible with this client. Intake remains unavailable.",
    );
  return v as unknown as ConversationCapabilities;
}
export async function loadExample(
  signal?: AbortSignal,
): Promise<ConversationExample> {
  const v = await read("example", signal);
  if (
    !record(v) ||
    !bounded(v.id) ||
    !bounded(v.title) ||
    !finite(v.duration_ms) ||
    v.duration_ms === 0 ||
    v.state !== "example" ||
    !record(v.transcript) ||
    !record(v.measurements) ||
    !record(v.profile) ||
    !bounded(v.profile.name) ||
    v.profile.declared_total !== 100 ||
    v.profile.source_total !== 95 ||
    v.profile.numeric_score !== null
  )
    throw new Error(
      "The example response is invalid. No analysis has been inferred.",
    );
  const segments = parseSegments(v.transcript.segments, v.duration_ms);
  return {
    id: v.id,
    title: v.title,
    duration_ms: v.duration_ms,
    state: "example",
    transcript: {
      segments,
      ...(bounded(v.transcript.revision)
        ? { revision: v.transcript.revision }
        : {}),
      ...(bounded(v.transcript.provenance, 4000)
        ? { provenance: v.transcript.provenance }
        : {}),
    },
    measurements: v.measurements,
    profile: {
      name: v.profile.name,
      declared_total: 100,
      source_total: 95,
      numeric_score: null,
    },
  };
}
export function createReviewProposal(
  checkpoint: { run_id: string; revision: string; transcript_revision: string },
  lane: "contextual" | "measurements",
  segmentId: string,
  proposal: string,
) {
  if (!bounded(proposal.trim(), 6000) || !bounded(segmentId))
    throw new Error(
      "Choose source evidence and describe the proposed correction.",
    );
  return {
    schema_version: "sales-xray-review-proposal.v1",
    state: "local_unsubmitted_proposal",
    ...checkpoint,
    lane,
    segment_id: segmentId,
    proposed_correction: proposal.trim(),
    reviewer_identity: null,
    submitted: false,
    numeric_publication: "withheld",
  };
}

/** Local collision guard; canonical server revision checks remain required. */
export function assertCheckpointRevision(
  existing: readonly LocalCheckpoint[],
  next: LocalCheckpoint,
): void {
  const previous = existing.find(
    (v) => v.run_id === next.run_id && v.revision === next.revision,
  );
  if (previous && JSON.stringify(previous) !== JSON.stringify(next))
    throw new Error(
      "This run revision is already open with different content. Export a new immutable revision before importing.",
    );
}

export interface MeasurementAnchor {
  kind: "measurement_point";
  series_index: number;
  series_label: string;
  physical_channel_index: number | null;
  measurement: string;
  measurement_revision: string;
  time_ms: number;
  value: number | null;
  unit: string;
  clock: string;
  window_ms: number;
  hop_ms: number;
  display_stride: number | null;
}

export function createMeasurementProposal(
  checkpoint: LocalCheckpoint,
  seriesIndex: number,
  pointIndex: number,
  correction: string,
  audioSourceMatched: boolean,
) {
  const series =
    Number.isInteger(seriesIndex) && seriesIndex >= 0
      ? checkpoint.channels[seriesIndex]
      : undefined;
  const point =
    series && Number.isInteger(pointIndex) && pointIndex >= 0
      ? series.points[pointIndex]
      : undefined;
  if (!series || !point || !bounded(correction.trim(), 6000))
    throw new Error(
      "Choose an exact measurement point and describe its proposed correction.",
    );
  const anchor: MeasurementAnchor = {
    kind: "measurement_point",
    series_index: seriesIndex,
    series_label: series.label,
    physical_channel_index: series.channel_index ?? null,
    measurement: series.measurement ?? series.label,
    measurement_revision:
      checkpoint.signal_metadata?.feature_sha256 ?? checkpoint.revision,
    time_ms: point.start_ms,
    value: point.value,
    unit: series.unit,
    clock: series.clock,
    window_ms: series.window_ms,
    hop_ms: series.hop_ms,
    display_stride: series.display_stride ?? null,
  };
  return {
    schema_version: "sales-xray-measurement-review-proposal.v1",
    state: "local_unsubmitted_proposal",
    run_id: checkpoint.run_id,
    revision: checkpoint.revision,
    lane: "measurements",
    anchor,
    source_evidence: {
      source_sha256: checkpoint.source.sha256,
      feature_sha256: checkpoint.signal_metadata?.feature_sha256 ?? null,
      provenance: checkpoint.source.provenance,
      audio_sha256_matched: audioSourceMatched,
      checkpoint_authorship_verified: false,
      feature_binary_verified: false,
      container_video_sync_certified: false,
    },
    transcript_revision: null,
    segment_id: null,
    proposed_correction: correction.trim(),
    reviewer_identity: null,
    submitted: false,
    numeric_publication: "withheld",
  };
}
