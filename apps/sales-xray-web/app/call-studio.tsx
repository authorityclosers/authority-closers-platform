"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  AudioLines,
  ArrowRight,
  Check,
  ChevronDown,
  FileText,
  LoaderCircle,
  Play,
  Printer,
  Upload,
  X,
} from "lucide-react";
import { BrandMark } from "@ac/ui";
import { RecordingMeasurements } from "./recording-measurements";
import { ReportExplorer } from "./report-explorer";
import { REPORT_NAVIGATION_COPY } from "./report-navigation-copy";
import { DipakOverview } from "./dipak-overview";
import { FindingEvidence } from "./finding-evidence";
import { ReportFactors } from "./report-factors";
import { formatTranscriptTime, ReportTranscript } from "./report-transcript";
import { REPORT_SECTION_COPY } from "./report-section-copy";
import { AccountNavigation } from "./account-navigation";
import { parseReportLanguage } from "./report-language";
import {
  parseJobResponse,
  parseJobStatus,
  parseSavedRecordings,
  parseTranscript,
  ReportContractError,
  encodeConversationId,
  type SavedRecording,
  type Transcript,
  type Finding,
  type Job,
} from "./report-contract";

type Quote = {
  id: string;
  recording_id: string;
  source_revision: string;
  recipe_revision: string;
  cost_label: string;
  privacy_summary: string;
  providers: string[];
  expires_at: string;
  quote_fingerprint: string;
  privacy_revision: string;
  output_kind?: "measurements" | "report";
};

const time = (ms: number) =>
  `${Math.floor(ms / 60000)
    .toString()
    .padStart(2, "0")}:${Math.floor((ms / 1000) % 60)
    .toString()
    .padStart(2, "0")}`;

const evidenceTime = (startMs: number, endMs: number) => {
  const range = `${formatTranscriptTime(startMs)}–${formatTranscriptTime(endMs)}`;
  return endMs - startMs < 1_000 ? `${range} · under 1 sec` : range;
};
type ProcessingPlanStage = {
  stage: "C2" | "C4" | "C5";
  provider: string;
  model: string;
  max_requests: number;
  privacy_revision: string;
  privacy_notice: string;
};
export type ProcessingPlan = {
  report_language?: import("./report-language").ReportLanguage;
  coaching_prompt_revision?:
    | "coaching-v1"
    | "coaching-v2"
    | "coaching-v3"
    | "coaching-v4";
  id: string;
  recording_id: string;
  plan_fingerprint: string;
  privacy_revision: "sales-xray-processing-plan-v1";
  accepted: boolean;
  state: "quoted" | "active" | "held" | "completed" | "cancelled";
  cost_label: string;
  max_cost_paise: number;
  automatic_c5_repair_cost_paise: number;
  max_entitlement_seconds: number;
  expires_at_epoch: number;
  stages: ProcessingPlanStage[];
  current_stage: string | null;
  report_ready: boolean;
  report_run_id: string | null;
  automatic_progression: true;
  failure_code: string | null;
};
type Workspace = {
  intake_enabled: boolean;
  authenticated: boolean;
  sign_in_url: string | null;
  message: string;
};

const PLAN_STATES = new Set([
  "quoted",
  "active",
  "held",
  "completed",
  "cancelled",
]);
const PLAN_STAGES = new Set(["C2", "C4", "C5"]);
const PROCESSING_STAGES = new Set(["C1", "C2", "C3", "C4", "C5", "C6"]);
const LOCAL_MEASUREMENT_RECIPES = new Set([
  "audioatlas-48000-v1",
  "audioatlas-16000-v1",
]);

type EvidenceMoment = Finding["evidence"][number] & {
  findingTitle: string;
  key: string;
};

const DISPLAY_COPY = {
  uploadStep: "Upload your call",
  analyzeStep: "Analyze",
  reportStep: "Read your report",
  sourceMomentsHeading: "Moments from your call",
  sourceMomentsIntro: "Listen to the moments behind each finding.",
  playMoment: "Play source moment",
  printReport: "Print / save PDF",
  playbackUnavailable:
    "This moment is linked, but source playback is unavailable. Verify the authorized recording to listen.",
  playbackBlocked:
    "Playback was blocked. Press play in the audio controls to continue from this moment.",
  playingMoment: "Playing source moment",
};

function evidenceMoments(report: Job["report"]): EvidenceMoment[] {
  if (!report) return [];
  const seen = new Set<string>();
  const moments: EvidenceMoment[] = [];
  const groups: Array<[string, Finding[]]> = [
    ["strength", report.strengths],
    ["missed", report.missed_opportunities],
    ["improvement", report.improvements],
    ["objection", report.objection_analysis],
    ["closing", report.closing_analysis],
  ];
  for (const [, findings] of groups) {
    for (const finding of findings) {
      for (const evidence of finding.evidence) {
        const key = `${evidence.segment_id}:${evidence.start_ms}:${evidence.end_ms}`;
        if (seen.has(key)) continue;
        seen.add(key);
        moments.push({ ...evidence, findingTitle: finding.title, key });
      }
    }
  }
  return moments.sort((a, b) => a.start_ms - b.start_ms);
}

function planObject(value: unknown, code: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new ReportContractError(`${code}_invalid`);
  return value as Record<string, unknown>;
}

function planText(value: unknown, code: string, max = 2_000): string {
  if (typeof value !== "string" || !value.trim() || value.length > max)
    throw new ReportContractError(`${code}_invalid`);
  return value;
}

function planInteger(
  value: unknown,
  code: string,
  min: number,
  max: number,
): number {
  if (
    !Number.isInteger(value) ||
    (value as number) < min ||
    (value as number) > max
  )
    throw new ReportContractError(`${code}_invalid`);
  return value as number;
}

export function parseProcessingPlan(
  value: unknown,
  recordingId: string,
): ProcessingPlan {
  const plan = planObject(value, "plan");
  const expectedKeys = [
    "id",
    "recording_id",
    "plan_fingerprint",
    "privacy_revision",
    "accepted",
    "state",
    "cost_label",
    "max_cost_paise",
    "automatic_c5_repair_cost_paise",
    "max_entitlement_seconds",
    "expires_at_epoch",
    "stages",
    "current_stage",
    "report_ready",
    "report_run_id",
    "automatic_progression",
    "failure_code",
    "report_language",
    "coaching_prompt_revision",
  ];
  if (Object.keys(plan).some((key) => !expectedKeys.includes(key)))
    throw new ReportContractError("plan_unknown_field");
  const id = planText(plan.id, "plan_id", 128);
  encodeConversationId(id, "plan_id");
  if (planText(plan.recording_id, "plan_recording_id", 128) !== recordingId)
    throw new ReportContractError("plan_recording_id_mismatch");
  const fingerprint = planText(plan.plan_fingerprint, "plan_fingerprint", 64);
  if (!/^[a-f0-9]{64}$/.test(fingerprint))
    throw new ReportContractError("plan_fingerprint_invalid");
  if (plan.privacy_revision !== "sales-xray-processing-plan-v1")
    throw new ReportContractError("plan_privacy_revision_invalid");
  if (typeof plan.accepted !== "boolean")
    throw new ReportContractError("plan_accepted_invalid");
  const state = planText(
    plan.state,
    "plan_state",
    32,
  ) as ProcessingPlan["state"];
  if (!PLAN_STATES.has(state))
    throw new ReportContractError("plan_state_invalid");
  const maximumCost = planInteger(
    plan.max_cost_paise,
    "plan_cost_limit",
    0,
    2_147_483_647,
  );
  const automaticRepairCost =
    plan.automatic_c5_repair_cost_paise === undefined
      ? 0
      : planInteger(
          plan.automatic_c5_repair_cost_paise,
          "plan_repair_cost_limit",
          0,
          2_147_483_647,
        );
  const costLabel =
    maximumCost === 0
      ? "₹0 · approved allowance"
      : `Up to ₹${Math.floor(maximumCost / 100)}.${String(maximumCost % 100).padStart(2, "0")} · approved budget`;
  if (plan.cost_label !== costLabel)
    throw new ReportContractError("plan_cost_invalid");
  const maxEntitlement = planInteger(
    plan.max_entitlement_seconds,
    "plan_entitlement",
    0,
    86_400,
  );
  const expires = planInteger(
    plan.expires_at_epoch,
    "plan_expiry",
    1,
    4_102_444_800,
  );
  if (!Array.isArray(plan.stages) || plan.stages.length !== 3)
    throw new ReportContractError("plan_stages_invalid");
  const stages = plan.stages.map((value, index) => {
    const stage = planObject(value, `plan_stage_${index}`);
    const keys = [
      "stage",
      "provider",
      "model",
      "max_requests",
      "privacy_revision",
      "privacy_notice",
    ];
    if (Object.keys(stage).some((key) => !keys.includes(key)))
      throw new ReportContractError(`plan_stage_${index}_unknown_field`);
    const name = planText(
      stage.stage,
      `plan_stage_${index}_name`,
      8,
    ) as ProcessingPlanStage["stage"];
    if (!PLAN_STAGES.has(name))
      throw new ReportContractError(`plan_stage_${index}_name_invalid`);
    return {
      stage: name,
      provider: planText(stage.provider, `plan_stage_${index}_provider`, 128),
      model: planText(stage.model, `plan_stage_${index}_model`, 256),
      max_requests: planInteger(
        stage.max_requests,
        `plan_stage_${index}_requests`,
        1,
        64,
      ),
      privacy_revision: planText(
        stage.privacy_revision,
        `plan_stage_${index}_privacy`,
        128,
      ),
      privacy_notice: planText(
        stage.privacy_notice,
        `plan_stage_${index}_notice`,
        2_000,
      ),
    };
  });
  if (new Set(stages.map((stage) => stage.stage)).size !== stages.length)
    throw new ReportContractError("plan_stages_duplicate");
  const current =
    plan.current_stage === null
      ? null
      : planText(plan.current_stage, "plan_current_stage", 8);
  if (current !== null && !PROCESSING_STAGES.has(current))
    throw new ReportContractError("plan_current_stage_invalid");
  const reportRunId =
    plan.report_run_id === null
      ? null
      : planText(plan.report_run_id, "plan_report_run_id", 128);
  if (reportRunId !== null)
    encodeConversationId(reportRunId, "plan_report_run_id");
  if (
    typeof plan.report_ready !== "boolean" ||
    plan.automatic_progression !== true
  )
    throw new ReportContractError("plan_progress_invalid");
  const failure =
    plan.failure_code === null
      ? null
      : planText(plan.failure_code, "plan_failure_code", 128);
  const languageOptions: Pick<
    ProcessingPlan,
    "report_language" | "coaching_prompt_revision"
  > = {};
  if (
    plan.report_language !== undefined ||
    plan.coaching_prompt_revision !== undefined
  ) {
    languageOptions.report_language = parseReportLanguage(plan.report_language);
    if (
      !["coaching-v1", "coaching-v2", "coaching-v3", "coaching-v4"].includes(
        String(plan.coaching_prompt_revision),
      ) ||
      (plan.coaching_prompt_revision !== "coaching-v4" &&
        languageOptions.report_language !== "en")
    )
      throw new ReportContractError("plan_language_revision_invalid");
    languageOptions.coaching_prompt_revision =
      plan.coaching_prompt_revision as ProcessingPlan["coaching_prompt_revision"];
  }
  return {
    ...languageOptions,
    id,
    recording_id: recordingId,
    plan_fingerprint: fingerprint,
    privacy_revision: "sales-xray-processing-plan-v1",
    accepted: plan.accepted,
    state,
    cost_label: costLabel,
    max_cost_paise: maximumCost,
    automatic_c5_repair_cost_paise: automaticRepairCost,
    max_entitlement_seconds: maxEntitlement,
    expires_at_epoch: expires,
    stages,
    current_stage: current,
    report_ready: plan.report_ready,
    report_run_id: reportRunId,
    automatic_progression: true,
    failure_code: failure,
  };
}

function processingStageLabel(stage: string | null): string {
  switch (stage) {
    case "C1":
      return "Measuring the recording";
    case "C2":
      return "Transcribing the call";
    case "C3":
      return "Aligning transcript evidence";
    case "C4":
      return "Extracting conversation facts";
    case "C5":
      return "Preparing the coaching draft";
    case "C6":
      return "Saving the report";
    default:
      return "Preparing the approved analysis";
  }
}

function processingPlanMessage(plan: ProcessingPlan): string {
  if (plan.state === "held")
    return "Processing is paused. Saved results remain available; review the approval before continuing.";
  if (plan.state === "cancelled")
    return "This analysis was cancelled. Your recording remains private.";
  if (plan.state === "completed" && !plan.report_ready)
    return "Analysis finished without a saved report. No report is shown.";
  if (plan.report_ready)
    return "The report is saved. We are loading its verified transcript.";
  return `${processingStageLabel(plan.current_stage)}. The server will continue through the approved stages.`;
}

function recordingDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "Saved call"
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

function recordingTitle(recording: SavedRecording): string {
  return `Sales call · ${recordingDate(recording.created_at)}`;
}

function recordingStatus(recording: SavedRecording): string {
  if (recording.has_report || recording.latest_run?.has_report)
    return "Report ready";
  if (recording.latest_run?.state === "completed")
    return "Analysis ready · report unavailable";
  if (recording.latest_run?.state === "failed") return "Analysis failed";
  if (recording.latest_run?.state === "cancelled") return "Analysis cancelled";
  if (recording.latest_run) return "Analysis pending";
  return "Ready to play";
}

async function readTranscript(
  recordingId: string,
  sourceSha256: string,
  signal?: AbortSignal,
): Promise<Transcript> {
  const safeRecordingId = encodeConversationId(recordingId, "recording_id");
  const response = await api<unknown>(
    `/recordings/${safeRecordingId}/transcript`,
    { signal },
  );
  return parseTranscript(response, sourceSha256);
}

type ReportStatus = {
  payload: unknown;
  job: Job;
  hasReport: boolean;
};

async function readReportStatus(
  recordingId: string,
  runId: string,
  signal?: AbortSignal,
): Promise<ReportStatus> {
  encodeConversationId(recordingId, "recording_id");
  const safeRunId = encodeConversationId(runId, "run_id");
  const response = await api<unknown>(`/runs/${safeRunId}/report`, { signal });
  const job = parseJobStatus(response, {
    runId,
    recordingId,
  });
  const hasReport =
    typeof response === "object" &&
    response !== null &&
    !Array.isArray(response) &&
    "report" in response &&
    response.report !== undefined &&
    response.report !== null;
  return { payload: response, job, hasReport };
}

class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/v1/conversation${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    ...init,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new ApiError(
      response.status,
      typeof data.detail === "string"
        ? data.detail
        : "The request could not be completed. Please try again.",
    );
  return data as T;
}

async function readProcessingPlan(
  recordingId: string,
  signal?: AbortSignal,
): Promise<ProcessingPlan | null> {
  const safeRecordingId = encodeConversationId(recordingId, "recording_id");
  try {
    const response = await api<unknown>(`/recordings/${safeRecordingId}/plan`, {
      signal,
    });
    return parseProcessingPlan(response, recordingId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export type CallStudioVariant = "standalone" | "embedded";

export type CallStudioProps = {
  homeHref?: string;
  /** Existing LMS callers identify their embedded mount with the /home return path. */
  variant?: CallStudioVariant;
};

export function CallStudio({ homeHref = "/", variant }: CallStudioProps) {
  const resolvedVariant =
    variant ?? (homeHref === "/" ? "standalone" : "embedded");
  const embedded = resolvedVariant === "embedded";
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [duration, setDuration] = useState(0);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [plan, setPlan] = useState<ProcessingPlan | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [sourceSha256, setSourceSha256] = useState<string | null>(null);
  const [activeRecording, setActiveRecording] = useState<SavedRecording | null>(
    null,
  );
  const [activeTranscript, setActiveTranscript] = useState<Transcript | null>(
    null,
  );
  const [recordingDurations, setRecordingDurations] = useState<
    Record<string, number>
  >({});
  const [recordings, setRecordings] = useState<SavedRecording[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const [historyAttempt, setHistoryAttempt] = useState(0);
  const [reportBlocked, setReportBlocked] = useState(false);
  const [consent, setConsent] = useState(false);
  const [planConsent, setPlanConsent] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [selectedMomentKey, setSelectedMomentKey] = useState<string | null>(
    null,
  );
  const [momentStatus, setMomentStatus] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const attempt = useRef(0);
  const requestKey = useRef("");
  const planRequestKey = useRef("");
  const copy = DISPLAY_COPY;
  const sections = REPORT_SECTION_COPY.en;
  const navigation = REPORT_NAVIGATION_COPY.en;
  const Main: "div" | "main" = embedded ? "div" : "main";

  useEffect(() => {
    const controller = new AbortController();
    api<Workspace>("/workspace", { signal: controller.signal })
      .then(setWorkspace)
      .catch(() => {
        if (!controller.signal.aborted)
          setWorkspace({
            intake_enabled: false,
            authenticated: false,
            sign_in_url: null,
            message:
              "The analysis service is being connected. You can select and play your call below; it has not been uploaded.",
          });
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!workspace?.authenticated) return;
    const controller = new AbortController();
    api<unknown>("/recordings", { signal: controller.signal })
      .then((response) => {
        const parsed = parseSavedRecordings(response);
        if (!controller.signal.aborted) setRecordings(parsed.recordings);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setHistoryError("Saved calls could not be loaded. Try again.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setHistoryLoading(false);
      });
    return () => controller.abort();
  }, [historyAttempt, workspace?.authenticated]);
  function refreshHistory() {
    setHistoryLoading(true);
    setHistoryError("");
    setHistoryAttempt((value) => value + 1);
  }
  useEffect(
    () => () => {
      if (audioUrl?.startsWith("blob:")) URL.revokeObjectURL(audioUrl);
    },
    [audioUrl],
  );
  const activeRecordingId =
    activeRecording?.id ?? plan?.recording_id ?? quote?.recording_id ?? null;
  const activeJobId = job?.id ?? null;
  const shouldPollJob = Boolean(
    job &&
      !job.report &&
      !reportBlocked &&
      !["failed", "cancelled", "completed"].includes(job.state),
  );
  useEffect(() => {
    if (!shouldPollJob || !activeRecordingId || !sourceSha256 || !activeJobId)
      return;
    const controller = new AbortController();
    const current = attempt.current;
    const maxTransientRetries = 5;
    const maxDelayMs = 15_000;
    let delayMs = 2_500;
    let transientRetries = 0;
    let timer: number | undefined;
    const poll = () => {
      timer = window.setTimeout(async () => {
        if (controller.signal.aborted || current !== attempt.current) return;
        try {
          const status = await readReportStatus(
            activeRecordingId,
            activeJobId,
            controller.signal,
          );
          if (controller.signal.aborted || current !== attempt.current) return;
          if (status.hasReport) {
            const transcript = await readTranscript(
              activeRecordingId,
              sourceSha256,
              controller.signal,
            );
            if (controller.signal.aborted || current !== attempt.current)
              return;
            const verified = parseJobResponse(status.payload, {
              sourceSha256,
              durationMs: transcript.duration_ms,
              transcript,
            });
            setActiveTranscript(transcript);
            setRecordingDurations((previous) => ({
              ...previous,
              [activeRecordingId]: transcript.duration_ms,
            }));
            setJob(verified);
            setError("");
            return;
          }
          setJob(status.job);
          if (status.job.state === "completed") {
            setError("");
            if (activeRecordingId && !plan)
              void requestProcessingPlan(activeRecordingId, current);
            return;
          }
          if (["failed", "cancelled"].includes(status.job.state)) {
            setError(
              status.job.message || "The report could not be completed.",
            );
            return;
          }
          transientRetries = 0;
          delayMs = Math.min(delayMs * 2, maxDelayMs);
          setError("");
          poll();
        } catch (e) {
          if (controller.signal.aborted || current !== attempt.current) return;
          if (e instanceof ReportContractError) {
            setReportBlocked(true);
            setError(
              "The report could not be verified against the recording, so it was not shown.",
            );
            return;
          }
          transientRetries += 1;
          setError(
            e instanceof Error ? e.message : "Could not refresh the report.",
          );
          if (transientRetries > maxTransientRetries) return;
          delayMs = Math.min(delayMs * 2, maxDelayMs);
          poll();
        }
      }, delayMs);
    };
    poll();
    return () => {
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [activeJobId, activeRecordingId, plan, shouldPollJob, sourceSha256]);

  const shouldPollPlan = Boolean(
    plan &&
      plan.accepted &&
      !reportBlocked &&
      ((plan.state === "active" && !plan.report_ready) ||
        (plan.report_ready && plan.report_run_id && !job?.report)),
  );
  const planId = plan?.id ?? null;
  useEffect(() => {
    if (!shouldPollPlan || !activeRecordingId || !planId) return;
    const controller = new AbortController();
    const current = attempt.current;
    let timer: number | undefined;
    const poll = () => {
      timer = window.setTimeout(async () => {
        if (controller.signal.aborted || current !== attempt.current) return;
        try {
          const next = await readProcessingPlan(
            activeRecordingId,
            controller.signal,
          );
          if (!next)
            throw new Error("The approved processing plan is unavailable.");
          if (controller.signal.aborted || current !== attempt.current) return;
          if (next.report_ready && next.report_run_id) {
            const status = await readReportStatus(
              next.recording_id,
              next.report_run_id,
              controller.signal,
            );
            if (controller.signal.aborted || current !== attempt.current)
              return;
            if (status.hasReport) {
              const transcript = await readTranscript(
                next.recording_id,
                sourceSha256 ?? "",
                controller.signal,
              );
              if (controller.signal.aborted || current !== attempt.current)
                return;
              const verified = parseJobResponse(status.payload, {
                sourceSha256: sourceSha256 ?? "",
                durationMs: transcript.duration_ms,
                transcript,
              });
              setActiveTranscript(transcript);
              setRecordingDurations((previous) => ({
                ...previous,
                [next.recording_id]: transcript.duration_ms,
              }));
              setDuration(transcript.duration_ms);
              setPlan(next);
              setJob(verified);
              setError("");
              return;
            }
            setError("The report is ready but has not become readable yet.");
            setPlan(next);
            return;
          }
          if (next.state === "held" || next.state === "cancelled") {
            setPlan(next);
            setError(processingPlanMessage(next));
            return;
          }
          if (next.state === "completed") {
            setPlan(next);
            setError(processingPlanMessage(next));
            return;
          }
          setPlan(next);
          setError("");
          poll();
        } catch (e) {
          if (controller.signal.aborted || current !== attempt.current) return;
          if (e instanceof ReportContractError) {
            setReportBlocked(true);
            setError(
              "The approved processing plan could not be verified, so no report is shown.",
            );
            return;
          }
          setError(
            e instanceof Error
              ? e.message
              : "Could not refresh the approved processing plan.",
          );
        }
      }, 2_500);
    };
    poll();
    return () => {
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [
    activeRecordingId,
    job?.report,
    planId,
    plan?.accepted,
    plan?.state,
    plan?.report_ready,
    plan?.report_run_id,
    reportBlocked,
    shouldPollPlan,
    sourceSha256,
  ]);

  function clearAudioPlayback() {
    try {
      audio.current?.pause();
    } catch {
      // A media element can be unavailable while React replaces the preview.
    }
    setAudioUrl(null);
  }

  function selectFile(next?: File) {
    if (!next) return;
    if (
      next.size === 0 ||
      next.size > 32 * 1024 * 1024 ||
      !/\.(mp3|mpeg|wav|m4a|ogg|flac)$/i.test(next.name)
    ) {
      setError(
        "Choose an MP3, MPEG, WAV, M4A, OGG or FLAC recording up to 32 MB.",
      );
      return;
    }
    ++attempt.current;
    clearAudioPlayback();
    setBusy("");
    setFile(next);
    setActiveRecording(null);
    setActiveTranscript(null);
    setAudioUrl(URL.createObjectURL(next));
    setDuration(0);
    setQuote(null);
    setPlan(null);
    setJob(null);
    setSourceSha256(null);
    setReportBlocked(false);
    setConsent(false);
    setPlanConsent(false);
    setSelectedMomentKey(null);
    setMomentStatus("");
    setError("");
    requestKey.current = crypto.randomUUID();
    planRequestKey.current = "";
    if (input.current) input.current.value = "";
  }

  async function requestProcessingPlan(
    recordingId: string,
    current: number,
    fresh = false,
  ) {
    if (current !== attempt.current) return;
    const key = fresh
      ? `${requestKey.current}:plan:${crypto.randomUUID()}`
      : planRequestKey.current || `${requestKey.current}:plan`;
    planRequestKey.current = key;
    setBusy("Preparing your approved report plan…");
    setError("");
    try {
      const safeRecordingId = encodeConversationId(recordingId, "recording_id");
      const response = await api<unknown>(
        `/recordings/${safeRecordingId}/plan/quote`,
        {
          method: "POST",
          headers: { "Idempotency-Key": key },
        },
      );
      const next = parseProcessingPlan(response, recordingId);
      if (current !== attempt.current) return;
      setPlan(next);
      setPlanConsent(false);
      setJob(null);
    } catch (e) {
      if (current === attempt.current)
        setError(
          e instanceof Error
            ? e.message
            : "We could not prepare the approved report plan.",
        );
    } finally {
      if (current === attempt.current) setBusy("");
    }
  }

  async function acceptProcessingPlan() {
    if (!plan || !planConsent || busy) return;
    const current = attempt.current;
    setBusy("Starting your approved report…");
    setError("");
    try {
      const safeRecordingId = encodeConversationId(
        plan.recording_id,
        "recording_id",
      );
      const planKey = planRequestKey.current || `${requestKey.current}:plan`;
      planRequestKey.current = planKey;
      const response = await api<unknown>(
        `/recordings/${safeRecordingId}/plan`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": `${planKey}:accept`,
          },
          body: JSON.stringify({
            plan_id: plan.id,
            plan_fingerprint: plan.plan_fingerprint,
            privacy_revision: plan.privacy_revision,
            accepted: true,
          }),
        },
      );
      const next = parseProcessingPlan(response, plan.recording_id);
      if (current !== attempt.current) return;
      // Keep the server's state and current stage; acceptance is never inferred
      // from the click alone.
      setPlan(next);
      setPlanConsent(false);
      setHistoryAttempt((value) => value + 1);
    } catch (e) {
      if (current === attempt.current)
        setError(
          e instanceof Error
            ? e.message
            : "The approved report could not be started.",
        );
    } finally {
      if (current === attempt.current) setBusy("");
    }
  }

  async function requestFreshProcessingPlan() {
    if (!plan || busy) return;
    const current = ++attempt.current;
    setPlan(null);
    setJob(null);
    setPlanConsent(false);
    await requestProcessingPlan(plan.recording_id, current, true);
  }

  async function openSavedRecording(recording: SavedRecording) {
    if (busy) return;
    const current = ++attempt.current;
    clearAudioPlayback();
    setBusy("Opening saved call…");
    setError("");
    setReportBlocked(false);
    setFile(null);
    setQuote(null);
    setPlan(null);
    setJob(null);
    setConsent(false);
    setActiveRecording(recording);
    setActiveTranscript(null);
    setSourceSha256(recording.source_sha256);
    setDuration(0);
    setPlanConsent(false);
    setSelectedMomentKey(null);
    setMomentStatus("");
    requestKey.current = crypto.randomUUID();
    planRequestKey.current = "";
    try {
      const safeRecordingId = encodeConversationId(
        recording.id,
        "recording_id",
      );
      if (current !== attempt.current) return;
      setAudioUrl(`/v1/conversation/recordings/${safeRecordingId}/source`);
      const run = recording.latest_run;
      if (!run) {
        setError("This saved call has no analysis run yet.");
        return;
      }
      const savedPlan = await readProcessingPlan(recording.id);
      if (current !== attempt.current) return;
      if (savedPlan) {
        setPlan(savedPlan);
        setJob(null);
        return;
      }
      const hasSavedReport = recording.has_report || run.has_report;
      setJob({
        id: run.id,
        state: run.state,
        message: hasSavedReport
          ? "Opening the saved report…"
          : "This saved call has an analysis run, but its report is not ready yet.",
      });
      if (!hasSavedReport) {
        if (
          LOCAL_MEASUREMENT_RECIPES.has(run.recipe_revision) &&
          run.state === "completed"
        ) {
          await requestProcessingPlan(recording.id, current);
        }
        return;
      }
      const status = await readReportStatus(recording.id, run.id);
      if (current !== attempt.current) return;
      if (!status.hasReport) {
        setJob(status.job);
        return;
      }
      const transcript = await readTranscript(
        recording.id,
        recording.source_sha256,
      );
      if (current !== attempt.current) return;
      const parsed = parseJobResponse(status.payload, {
        sourceSha256: recording.source_sha256,
        durationMs: transcript.duration_ms,
        transcript,
      });
      setActiveTranscript(transcript);
      setRecordingDurations((previous) => ({
        ...previous,
        [recording.id]: transcript.duration_ms,
      }));
      setDuration(transcript.duration_ms);
      setJob(parsed);
    } catch (error) {
      if (current !== attempt.current) return;
      if (error instanceof ReportContractError) {
        setReportBlocked(true);
        setError(
          "The saved call could not be verified against its transcript, so its report was not shown.",
        );
      } else {
        setError(
          error instanceof Error
            ? error.message
            : "The saved call could not be opened.",
        );
      }
    } finally {
      if (current === attempt.current) setBusy("");
    }
  }
  async function prepare() {
    if (!file || busy) return;
    const current = attempt.current;
    setBusy("Preparing your call…");
    setError("");
    try {
      const digest = await crypto.subtle.digest(
        "SHA-256",
        await file.arrayBuffer(),
      );
      const sha = Array.from(new Uint8Array(digest), (v) =>
        v.toString(16).padStart(2, "0"),
      ).join("");
      const prepared = await api<Quote>("/intake/quote", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": requestKey.current,
        },
        body: JSON.stringify({
          source_sha256: sha,
          source_bytes: file.size,
          content_type:
            (
              {
                wav: "audio/wav",
                m4a: "audio/mp4",
                ogg: "audio/ogg",
                flac: "audio/flac",
              } as Record<string, string>
            )[file.name.split(".").pop()?.toLowerCase() ?? ""] ?? "audio/mpeg",
          duration_ms: Math.ceil(duration),
          purpose: "internal_analysis",
        }),
      });
      if (current === attempt.current) {
        setSourceSha256(sha);
        setQuote(prepared);
        setActiveRecording(null);
        setActiveTranscript(null);
      }
    } catch (e) {
      if (current === attempt.current)
        setError(
          e instanceof Error ? e.message : "We could not prepare this call.",
        );
    } finally {
      if (current === attempt.current) setBusy("");
    }
  }
  async function analyze() {
    if (!file || !quote || !consent || busy) return;
    const current = attempt.current;
    setBusy("Uploading your call…");
    setError("");
    try {
      const safeQuoteId = encodeConversationId(quote.id, "quote_id");
      const safeRecordingId = encodeConversationId(
        quote.recording_id,
        "recording_id",
      );
      await api(`/quotes/${safeQuoteId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          quote_fingerprint: quote.quote_fingerprint,
          privacy_revision: quote.privacy_revision,
          accepted: true,
        }),
      });
      if (current !== attempt.current) return;
      await api(`/recordings/${safeRecordingId}/source`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/octet-stream",
          "X-Analysis-Quote": quote.id,
        },
        body: file,
      });
      if (current !== attempt.current) return;
      setBusy("Starting your report…");
      const next = await api<unknown>("/runs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": `${requestKey.current}:run`,
        },
        body: JSON.stringify({
          recording_id: quote.recording_id,
          source_revision: quote.source_revision,
          quote_id: quote.id,
          recipe_revision: quote.recipe_revision,
        }),
      });
      if (current === attempt.current) {
        setJob(
          parseJobResponse(next, {
            sourceSha256: sourceSha256 ?? "",
            durationMs: Math.ceil(duration),
          }),
        );
        setHistoryAttempt((value) => value + 1);
      }
    } catch (e) {
      if (current === attempt.current)
        setError(
          e instanceof Error ? e.message : "The call could not be analyzed.",
        );
    } finally {
      if (current === attempt.current) setBusy("");
    }
  }
  const report = job?.report;
  const reportMoments = evidenceMoments(report);
  const durationLabel = activeTranscript
    ? time(activeTranscript.duration_ms)
    : duration
      ? time(duration)
      : "Not available";
  function seekToMoment(moment: EvidenceMoment) {
    setSelectedMomentKey(moment.key);
    const player = audio.current;
    if (!player || !player.isConnected) {
      setMomentStatus(copy.playbackUnavailable);
      return;
    }
    try {
      player.currentTime = moment.start_ms / 1000;
      const playback = player.play();
      if (!playback || typeof playback.then !== "function") {
        setMomentStatus(copy.playbackBlocked);
        return;
      }
      void playback
        .then(() =>
          setMomentStatus(`${copy.playingMoment} · ${time(moment.start_ms)}.`),
        )
        .catch(() => setMomentStatus(copy.playbackBlocked));
    } catch {
      setMomentStatus(copy.playbackUnavailable);
    }
  }
  function restart() {
    ++attempt.current;
    clearAudioPlayback();
    setFile(null);
    setActiveRecording(null);
    setActiveTranscript(null);
    setQuote(null);
    setPlan(null);
    setJob(null);
    setSourceSha256(null);
    setReportBlocked(false);
    setDuration(0);
    setError("");
    setBusy("");
    setConsent(false);
    setPlanConsent(false);
    setSelectedMomentKey(null);
    setMomentStatus("");
    planRequestKey.current = "";
  }

  function renderFindings(title: string, rows: Finding[]) {
    return (
      <section key={title}>
        <h2 lang="en">{title}</h2>
        {rows.length ? (
          rows.map((finding, i) => (
            <article key={i}>
              <h3>{finding.title}</h3>
              <p>{finding.explanation}</p>
              <FindingEvidence count={finding.evidence.length}>
                {finding.evidence.map((e, j) => (
                  <blockquote key={j}>
                    <button
                      className={`text-button evidence-time-button${selectedMomentKey === `${e.segment_id}:${e.start_ms}:${e.end_ms}` ? " selected" : ""}`}
                      type="button"
                      aria-label={`${copy.playMoment}, ${time(e.start_ms)} to ${time(e.end_ms)}: ${e.quote}`}
                      onClick={() =>
                        seekToMoment({
                          ...e,
                          findingTitle: finding.title,
                          key: `${e.segment_id}:${e.start_ms}:${e.end_ms}`,
                        })
                      }
                    >
                      <Play size={12} aria-hidden="true" />
                      {evidenceTime(e.start_ms, e.end_ms)}
                    </button>{" "}
                    “{e.quote}”
                  </blockquote>
                ))}
              </FindingEvidence>
            </article>
          ))
        ) : (
          <p lang="en">{sections.empty}</p>
        )}
      </section>
    );
  }
  return (
    <div
      className={`xray-app simple-app${embedded ? " embedded-studio" : ""}`}
      data-theme="light"
      data-variant={resolvedVariant}
    >
      {!embedded && (
        <header className="studio-header">
          <Link href={homeHref} aria-label="Sales Xray home">
            <span className="studio-mark">
              <BrandMark />
            </span>
            <span>
              Dipak’s <strong>Sales Xray</strong>
              <small>AUTHORITY CLOSERS</small>
            </span>
          </Link>
          <AccountNavigation />
        </header>
      )}
      <Main id="main" className="studio-main">
        <nav className="studio-steps" aria-label="Analysis steps" lang="en">
          {[copy.uploadStep, copy.analyzeStep, copy.reportStep].map(
            (label, i) => (
              <span
                key={label}
                aria-current={
                  (job?.report ? 2 : job || quote ? 1 : 0) === i
                    ? "step"
                    : undefined
                }
              >
                <b>{i + 1}</b>
                {label}
                {i < 2 && <ChevronDown size={15} />}
              </span>
            ),
          )}
        </nav>
        {!job?.report && (
          <div className="studio-intro">
            <p className="eyebrow">YOUR NEXT CALL CAN BE BETTER</p>
            <h1>
              Turn a sales call into
              <br />a clear improvement plan.
            </h1>
            <p>
              Upload a recording. See what worked, where the conversation
              slipped, and what to do differently—using Dipak’s sales
              principles, with the moments from your call.
            </p>
          </div>
        )}
        <div className={`studio-body${job?.report ? " report-active" : ""}`}>
          <section className="panel studio-upload" aria-label="Your call">
            {!file && !activeRecording ? (
              <>
                <span className="studio-upload-icon">
                  <Upload size={30} />
                </span>
                <h2>Start with your sales call</h2>
                <p>
                  Choose a recording from your phone, meeting app or computer.
                </p>
                <label
                  className="primary-button upload-label"
                  htmlFor="call-file"
                >
                  <Upload size={18} /> Choose audio file
                </label>
                <p className="muted">
                  MP3, MPEG, WAV, M4A, OGG or FLAC · up to 32 MB
                </p>
              </>
            ) : file ? (
              <>
                <div className="studio-file">
                  <span className="studio-upload-icon">
                    <AudioLines size={25} />
                  </span>
                  <div>
                    <h2>{file.name}</h2>
                    <p>
                      {duration ? time(duration) : "Reading duration…"} ·{" "}
                      {(file.size / 1048576).toFixed(1)} MB
                    </p>
                  </div>
                  {!busy && !job && (
                    <button
                      className="icon-button"
                      aria-label="Remove selected call"
                      onClick={restart}
                    >
                      <X size={18} />
                    </button>
                  )}
                </div>
                <audio
                  ref={audio}
                  src={audioUrl ?? undefined}
                  controls
                  preload="metadata"
                  onLoadedMetadata={() => {
                    const value = audio.current?.duration;
                    if (value && Number.isFinite(value))
                      setDuration(value * 1000);
                  }}
                  onError={() => setMomentStatus(copy.playbackUnavailable)}
                />
                <p className="small-text">
                  Listen here to check you chose the right recording. Selecting
                  a file does not upload it.
                </p>
              </>
            ) : activeRecording ? (
              <>
                <div className="studio-file saved-recording-file">
                  <span className="studio-upload-icon">
                    <AudioLines size={25} />
                  </span>
                  <div>
                    <h2>{recordingTitle(activeRecording)}</h2>
                    <p>
                      {recordingStatus(activeRecording)} ·{" "}
                      {duration
                        ? time(duration)
                        : "Duration will load with the report"}
                    </p>
                  </div>
                  {!busy && (
                    <button
                      className="icon-button"
                      aria-label="Close saved call"
                      onClick={restart}
                    >
                      <X size={18} />
                    </button>
                  )}
                </div>
                <audio
                  ref={audio}
                  src={audioUrl ?? undefined}
                  controls
                  preload="metadata"
                  onLoadedMetadata={() => {
                    const value = audio.current?.duration;
                    if (value && Number.isFinite(value))
                      setDuration(value * 1000);
                  }}
                  onError={() => setMomentStatus(copy.playbackUnavailable)}
                />
                <p className="small-text">
                  Select a timestamp in the report to replay that part of your
                  call.
                </p>
                <p className="small-text">Speaker labels remain unverified.</p>
              </>
            ) : null}
            <input
              ref={input}
              id="call-file"
              className="visually-hidden"
              type="file"
              accept=".mp3,.mpeg,.wav,.m4a,.ogg,.flac"
              aria-label="Choose sales call audio"
              onChange={(e) => selectFile(e.target.files?.[0])}
            />
            {file && !quote && !job && (
              <button
                className="primary-button studio-wide"
                disabled={!!busy || !duration || !workspace?.intake_enabled}
                onClick={() => void prepare()}
              >
                {busy ? (
                  <LoaderCircle className="spin" size={17} />
                ) : (
                  <ArrowRight size={17} />
                )}
                {busy || "Continue to analysis"}
              </button>
            )}
            {quote && !job && !plan && (
              <div className="studio-consent">
                <h3>Ready to upload privately</h3>
                <div className="studio-cost">
                  <span>Private intake</span>
                  <strong>{quote.cost_label}</strong>
                </div>
                <p>{quote.privacy_summary}</p>
                <label>
                  <input
                    type="checkbox"
                    checked={consent}
                    onChange={(e) => setConsent(e.target.checked)}
                  />
                  I agree to store this recording in AC’s private workspace and
                  run the local measurement step.
                </label>
                <button
                  className="primary-button studio-wide"
                  disabled={!consent || !!busy}
                  onClick={() => void analyze()}
                >
                  {busy ? (
                    <LoaderCircle className="spin" size={17} />
                  ) : (
                    <AudioLines size={17} />
                  )}
                  {busy || "Upload and measure privately"}
                </button>
              </div>
            )}
            {plan && !job?.report && !plan.accepted && (
              <div className="studio-consent">
                <h3>Your approved report plan</h3>
                <div className="studio-cost">
                  <span>Processing cost</span>
                  <strong>{plan.cost_label}</strong>
                </div>
                <p>
                  This one approval covers the bounded report run. AC will
                  continue through the listed stages automatically after you
                  accept this exact plan.
                </p>
                <p className="small-text">
                  {plan.max_entitlement_seconds === 0
                    ? "Your audio minutes are already counted. This report uses no additional audio minutes."
                    : `Up to ${time(plan.max_entitlement_seconds * 1000)} of additional audio minutes.`}{" "}
                  Plan expires{" "}
                  {new Date(plan.expires_at_epoch * 1000).toLocaleString()}.
                </p>
                <ul>
                  {plan.stages.map((stage) => (
                    <li key={stage.stage}>
                      <strong>{stage.stage}</strong>: {stage.provider} ·{" "}
                      {stage.model}
                      <br />
                      <span className="small-text">{stage.privacy_notice}</span>
                    </li>
                  ))}
                </ul>
                <label>
                  <input
                    type="checkbox"
                    checked={planConsent}
                    onChange={(e) => setPlanConsent(e.target.checked)}
                  />
                  {plan.max_cost_paise === 0
                    ? "I approve this exact zero-cost processing plan and its privacy terms."
                    : `I approve this processing plan up to ₹${Math.floor(plan.max_cost_paise / 100)}.${String(plan.max_cost_paise % 100).padStart(2, "0")} and its privacy terms.`}
                </label>
                <button
                  className="primary-button studio-wide"
                  disabled={!planConsent || !!busy}
                  onClick={() => void acceptProcessingPlan()}
                >
                  {busy ? (
                    <LoaderCircle className="spin" size={17} />
                  ) : (
                    <AudioLines size={17} />
                  )}
                  {busy || "Start approved report"}
                </button>
              </div>
            )}
            {job && !job.report && !plan && (
              <div className="studio-progress" role="status">
                {reportBlocked ? (
                  <X size={24} />
                ) : job.state === "completed" ? (
                  <Check size={24} />
                ) : (
                  <LoaderCircle
                    className={
                      ["failed", "cancelled"].includes(job.state) ? "" : "spin"
                    }
                    size={24}
                  />
                )}
                <h3>
                  {reportBlocked
                    ? "The report could not be verified"
                    : job.state === "completed"
                      ? "Local audio analysis is ready"
                      : job.state === "failed"
                        ? "The report needs attention"
                        : "Your call is being processed"}
                </h3>
                <p>
                  {reportBlocked
                    ? "No report is shown until it matches this recording."
                    : job.message ||
                      "The server has accepted your call. This page will show the report when it is ready."}
                </p>
                <p className="small-text">
                  {reportBlocked
                    ? "You can retry with a fresh analysis after checking the selected file."
                    : "We keep completed work so a retry does not need to transcribe your call again."}
                </p>
                {(reportBlocked ||
                  ["failed", "cancelled", "completed"].includes(job.state)) && (
                  <button
                    className="secondary-button studio-recovery-button"
                    type="button"
                    onClick={restart}
                  >
                    Choose a call to retry
                    <ArrowRight size={16} />
                  </button>
                )}
              </div>
            )}
            {plan && !job?.report && plan.accepted && (
              <div className="studio-progress" role="status">
                {reportBlocked ||
                plan.state === "held" ||
                plan.state === "cancelled" ? (
                  <X size={24} />
                ) : plan.report_ready ? (
                  <Check size={24} />
                ) : plan.state === "completed" ? (
                  <X size={24} />
                ) : (
                  <LoaderCircle className="spin" size={24} />
                )}
                <h3>
                  {reportBlocked
                    ? "The approved plan could not be verified"
                    : plan.state === "held" || plan.state === "cancelled"
                      ? "The report needs a fresh plan"
                      : plan.report_ready
                        ? "Your report is being loaded"
                        : plan.state === "completed"
                          ? "The report was not saved"
                          : processingStageLabel(plan.current_stage)}
                </h3>
                <p>
                  {reportBlocked
                    ? "No report is shown until it matches this recording."
                    : processingPlanMessage(plan)}
                </p>
                {(reportBlocked || plan.state === "completed") && (
                  <button
                    className="secondary-button studio-recovery-button"
                    type="button"
                    onClick={restart}
                  >
                    Choose a call to retry
                    <ArrowRight size={16} />
                  </button>
                )}
                <div
                  className="studio-stage-rail"
                  aria-label="Approved analysis stages"
                >
                  {plan.stages.map((stage, index) => {
                    const complete = plan.report_ready;
                    const current =
                      !complete &&
                      plan.state === "active" &&
                      plan.current_stage === stage.stage;
                    return (
                      <div
                        className={`studio-stage${complete ? " complete" : current ? " current" : ""}`}
                        key={stage.stage}
                      >
                        <span aria-hidden="true">
                          {complete ? <Check size={13} /> : index + 1}
                        </span>
                        <strong>
                          {stage.stage} · {processingStageLabel(stage.stage)}
                        </strong>
                        <small>
                          {complete
                            ? "Complete"
                            : current
                              ? "In progress"
                              : plan.state === "held" ||
                                  plan.state === "cancelled" ||
                                  plan.state === "completed"
                                ? "Not confirmed"
                                : "Queued"}
                        </small>
                      </div>
                    );
                  })}
                </div>
                <p className="studio-stage-note">
                  The plan reports its current stage and approved stages.
                  Per-stage completion receipts are not included in this
                  response.
                </p>
                {(plan.state === "held" || plan.state === "cancelled") && (
                  <button
                    className="secondary-button"
                    disabled={!!busy}
                    onClick={() => void requestFreshProcessingPlan()}
                  >
                    Request a fresh plan
                  </button>
                )}
              </div>
            )}
            {error && (
              <div className="notice error" role="alert">
                {error}
              </div>
            )}
            {!workspace?.intake_enabled && !job && !activeRecording && (
              <div className="studio-availability" role="status">
                <strong>
                  {workspace
                    ? "Analysis setup is in progress"
                    : "Connecting to your workspace…"}
                </strong>
                {workspace && <p>{workspace.message}</p>}
                {workspace?.sign_in_url && (
                  <a className="secondary-button" href={workspace.sign_in_url}>
                    Sign in with AC <ArrowRight size={16} />
                  </a>
                )}
              </div>
            )}
          </section>
          {!job?.report && (
            <aside className="studio-explainer">
              <p className="eyebrow">WHAT YOU GET</p>
              <h2>A report you can act on.</h2>
              {[
                [
                  "The call in plain language",
                  "What the prospect needed and where the decision landed.",
                ],
                [
                  "Good moments & missed opportunities",
                  "Specific feedback tied to what was actually said.",
                ],
                [
                  "Your three most useful improvements",
                  "What to change, why it matters, and how to practise it.",
                ],
              ].map(([title, detail]) => (
                <div className="studio-benefit" key={title}>
                  <Check size={19} />
                  <div>
                    <h3>{title}</h3>
                    <p>{detail}</p>
                  </div>
                </div>
              ))}
              <div className="studio-method">
                <FileText size={20} />
                <div>
                  <strong>Based on Dipak’s source material</strong>
                  <p>
                    Sales Constitution · Communication DNA · Sales Framework ·
                    Objection & Decision Intelligence · Evaluation Engine
                  </p>
                  <small>
                    Source-linked feedback stays tied to this call and its
                    authorized workspace.
                  </small>
                </div>
              </div>
            </aside>
          )}
        </div>
        <details className="recording-history panel" open={!job?.report}>
          <summary className={job?.report ? "" : "visually-hidden"}>
            Saved calls{recordings.length ? ` (${recordings.length})` : ""}
          </summary>
          <div className="history-heading">
            <div>
              <p className="eyebrow">YOUR WORKSPACE</p>
              <h2 id="saved-calls-title">Saved calls</h2>
              <p>
                Open a saved recording and return to its report without
                uploading it again.
              </p>
            </div>
            {workspace?.authenticated && (
              <button
                className="secondary-button"
                type="button"
                onClick={refreshHistory}
                disabled={historyLoading || !!busy}
              >
                {historyLoading ? "Loading…" : "Refresh"}
              </button>
            )}
          </div>
          {workspace === null ? (
            <p className="small-text" role="status">
              Checking workspace access…
            </p>
          ) : !workspace.authenticated ? (
            <p className="small-text">
              Sign in with AC to see saved calls. You can still choose a call
              below to listen locally.
            </p>
          ) : historyError ? (
            <div className="notice error" role="status">
              {historyError}
            </div>
          ) : historyLoading ? (
            <p className="small-text" role="status">
              Checking your saved calls…
            </p>
          ) : recordings.length ? (
            <div className="recording-history-list">
              {recordings.map((recording) => (
                <button
                  className={`recording-history-item${activeRecording?.id === recording.id ? " selected" : ""}`}
                  key={recording.id}
                  type="button"
                  onClick={() => void openSavedRecording(recording)}
                  disabled={!!busy}
                  aria-pressed={activeRecording?.id === recording.id}
                >
                  <span className="recording-history-icon" aria-hidden="true">
                    <AudioLines size={18} />
                  </span>
                  <span className="recording-history-copy">
                    <strong>{recordingTitle(recording)}</strong>
                    <small>
                      {recordingDurations[recording.id]
                        ? time(recordingDurations[recording.id])
                        : "Duration loads when opened"}
                    </small>
                  </span>
                  <span className="recording-history-state">
                    {recordingStatus(recording)}
                  </span>
                  {recording.has_report || recording.latest_run?.has_report ? (
                    <span className="recording-history-open">Open report</span>
                  ) : null}
                </button>
              ))}
            </div>
          ) : (
            <p className="small-text">
              No saved calls are available in this workspace yet.
            </p>
          )}
        </details>
        {job?.report && (
          <section
            className="studio-report panel"
            aria-label="Sales call report"
          >
            <p className="eyebrow" lang="en">
              {sections.heading}
            </p>
            <h1 lang="en">{sections.title}</h1>
            <p className="studio-report-summary">{job.report.summary}</p>
            <div className="studio-report-actions">
              <button
                className="secondary-button"
                type="button"
                onClick={() => window.print()}
              >
                <Printer size={16} aria-hidden="true" />
                {copy.printReport}
              </button>
            </div>
            <ReportExplorer
              key={job.id}
              label={navigation.label}
              panels={[
                {
                  id: "overview",
                  label: navigation.overview,
                  content: (
                    <DipakOverview
                      report={job.report}
                      onSelectEvidence={(item, title) =>
                        seekToMoment({
                          ...item,
                          findingTitle: title,
                          key: `${item.segment_id}:${item.start_ms}:${item.end_ms}`,
                        })
                      }
                    />
                  ),
                },
                {
                  id: "factors",
                  label: navigation.factors,
                  content: (
                    <ReportFactors
                      dimensions={job.report.dimensions}
                      language="en"
                    />
                  ),
                },
                {
                  id: "moments",
                  label: navigation.moments,
                  content: (
                    <section
                      className="studio-moment-browser"
                      aria-labelledby="source-moments-title"
                      lang="en"
                    >
                      <div className="studio-moment-browser-heading">
                        <div>
                          <p className="eyebrow">SOURCE-BOUND AUDIO</p>
                          <h2 id="source-moments-title">
                            {copy.sourceMomentsHeading}
                          </h2>
                          <p>{copy.sourceMomentsIntro}</p>
                        </div>
                        <span className="pill subtle">
                          {durationLabel} ·{" "}
                          {activeTranscript?.segments.length ?? 0} transcript
                          segments
                        </span>
                      </div>
                      {reportMoments.length ? (
                        <div className="studio-moment-list">
                          {reportMoments.map((moment) => (
                            <button
                              className={`studio-moment${selectedMomentKey === moment.key ? " selected" : ""}`}
                              key={moment.key}
                              type="button"
                              aria-pressed={selectedMomentKey === moment.key}
                              aria-label={`${copy.playMoment}, ${time(moment.start_ms)} to ${time(moment.end_ms)}: ${moment.quote}`}
                              onClick={() => seekToMoment(moment)}
                            >
                              <span className="studio-moment-time">
                                <Play size={12} aria-hidden="true" />
                                {evidenceTime(moment.start_ms, moment.end_ms)}
                              </span>
                              <span className="studio-moment-copy">
                                <strong>{moment.findingTitle}</strong>
                                <span>“{moment.quote}”</span>
                              </span>
                            </button>
                          ))}
                        </div>
                      ) : (
                        <p className="small-text">
                          No source-linked moments were produced for this draft.
                        </p>
                      )}
                      {momentStatus && (
                        <p className="studio-playback-status" role="status">
                          {momentStatus}
                        </p>
                      )}
                    </section>
                  ),
                },
                ...(activeTranscript
                  ? [
                      {
                        id: "transcript",
                        label: navigation.transcript,
                        content: (
                          <>
                            {activeTranscript && (
                              <ReportTranscript
                                key={`${activeTranscript.source_sha256}:${activeTranscript.revision}`}
                                transcript={activeTranscript}
                                language="en"
                                onSelect={(segment) =>
                                  seekToMoment({
                                    segment_id: segment.id,
                                    quote: segment.text,
                                    start_ms: segment.start_ms,
                                    end_ms: segment.end_ms,
                                    findingTitle: "Transcript",
                                    key: `${segment.id}:${segment.start_ms}:${segment.end_ms}`,
                                  })
                                }
                              />
                            )}
                          </>
                        ),
                      },
                    ]
                  : []),
                ...(activeRecordingId
                  ? [
                      {
                        id: "sound",
                        label: navigation.sound,
                        content: (
                          <>
                            {activeRecordingId && (
                              <RecordingMeasurements
                                key={`${activeRecordingId}:${job.report.source_sha256}`}
                                recordingId={activeRecordingId}
                                sourceSha256={job.report.source_sha256}
                                language="en"
                              />
                            )}
                          </>
                        ),
                      },
                    ]
                  : []),
                {
                  id: "next",
                  label: navigation.next,
                  content: (
                    <>
                      {renderFindings(
                        sections.improvements,
                        job.report.improvements,
                      )}
                      {renderFindings(
                        sections.objections,
                        job.report.objection_analysis,
                      )}
                      {renderFindings(
                        sections.closing,
                        job.report.closing_analysis,
                      )}
                    </>
                  ),
                },
              ]}
            />
            <details className="studio-report-details">
              <summary lang="en">{sections.details}</summary>
              <p lang="en">
                {sections.detailNote}
                {` Source: ${job.report.source_label}.`}
                {job.report.review_status === "draft_not_dipak_adjudicated"
                  ? " Review status: draft; Dipak has not adjudicated this report."
                  : " Review status is recorded in the report."}
                {activeTranscript
                  ? ` Duration: ${time(activeTranscript.duration_ms)}.`
                  : ""}
              </p>
            </details>
            <button className="primary-button" onClick={restart}>
              {sections.another} <ArrowRight size={17} />
            </button>
          </section>
        )}
        <details className="studio-help">
          <summary>How the call analysis works</summary>
          <p>
            Your recording stays in this workspace while the approved analysis
            runs. The report uses transcript moments from this call to explain
            what worked and what to try next.
          </p>
        </details>
        {!embedded && (
          <footer className="studio-footer">
            <span>Dipak’s Sales Xray · Authority Closers</span>
          </footer>
        )}
      </Main>
    </div>
  );
}
