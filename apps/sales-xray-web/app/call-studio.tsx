"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  AudioLines,
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  FileText,
  LoaderCircle,
  Upload,
  X,
} from "lucide-react";
import { BrandMark } from "@ac/ui";
import { Workbench, time } from "./workbench";
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
type Workspace = {
  intake_enabled: boolean;
  authenticated: boolean;
  sign_in_url: string | null;
  message: string;
};

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

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/v1/conversation${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    ...init,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "The request could not be completed. Please try again.",
    );
  return data as T;
}

export function CallStudio({ homeHref = "/" }: { homeHref?: string }) {
  const [advanced, setAdvanced] = useState(false);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [duration, setDuration] = useState(0);
  const [quote, setQuote] = useState<Quote | null>(null);
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
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const attempt = useRef(0);
  const requestKey = useRef("");

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
  const activeRecordingId = activeRecording?.id ?? quote?.recording_id ?? null;
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
  }, [activeJobId, activeRecordingId, shouldPollJob, sourceSha256]);

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
      next.size > 128 * 1024 * 1024 ||
      !/\.(mp3|mpeg|wav|m4a|ogg|flac)$/i.test(next.name)
    ) {
      setError(
        "Choose an MP3, MPEG, WAV, M4A, OGG or FLAC recording up to 128 MB.",
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
    setJob(null);
    setSourceSha256(null);
    setReportBlocked(false);
    setConsent(false);
    setError("");
    requestKey.current = crypto.randomUUID();
    if (input.current) input.current.value = "";
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
    setJob(null);
    setConsent(false);
    setActiveRecording(recording);
    setActiveTranscript(null);
    setSourceSha256(recording.source_sha256);
    setDuration(0);
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
      setJob({
        id: run.id,
        state: run.state,
        message:
          recording.has_report || run.has_report
            ? "Opening the saved report…"
            : "This saved call has an analysis run, but its report is not ready yet.",
      });
      if (!recording.has_report && !run.has_report) return;
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
  function restart() {
    ++attempt.current;
    clearAudioPlayback();
    setFile(null);
    setActiveRecording(null);
    setActiveTranscript(null);
    setQuote(null);
    setJob(null);
    setSourceSha256(null);
    setReportBlocked(false);
    setDuration(0);
    setError("");
    setBusy("");
    setConsent(false);
  }
  if (advanced)
    return (
      <>
        <div className="advanced-return">
          <button onClick={() => setAdvanced(false)}>
            <ArrowLeft size={17} /> Back to upload & reports
          </button>
        </div>
        <Workbench />
      </>
    );
  return (
    <div className="xray-app simple-app" data-theme="light">
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
        <span className="studio-preview">Internal testing</span>
      </header>
      <main id="main" className="studio-main">
        <nav className="studio-steps" aria-label="Analysis steps">
          {["Upload your call", "Analyze", "Read your report"].map(
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
        <div className="studio-body">
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
                  MP3, MPEG, WAV, M4A, OGG or FLAC · up to 128 MB
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
                />
                <p className="small-text">
                  Playback uses the authorized recording in this workspace. No
                  external audio URL is used.
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
            {quote && !job && (
              <div className="studio-consent">
                <h3>Ready to analyze</h3>
                <div className="studio-cost">
                  <span>Estimated cost</span>
                  <strong>{quote.cost_label}</strong>
                </div>
                <p>{quote.privacy_summary}</p>
                <label>
                  <input
                    type="checkbox"
                    checked={consent}
                    onChange={(e) => setConsent(e.target.checked)}
                  />
                  I have permission to analyze this recording with{" "}
                  {quote.providers.join(" and ")} under these conditions.
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
                  {busy || "Analyze my call"}
                </button>
              </div>
            )}
            {job && !job.report && (
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
                    AI feedback is a draft. Dipak has not reviewed this report.
                  </small>
                </div>
              </div>
            </aside>
          )}
        </div>
        <section
          className="recording-history panel"
          aria-labelledby="saved-calls-title"
        >
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
        </section>
        {job?.report && (
          <section
            className="studio-report panel"
            aria-label="Sales call report"
          >
            <p className="eyebrow">YOUR SALES CALL REPORT</p>
            <h1>What to take into your next call.</h1>
            <p className="studio-report-summary">{job.report.summary}</p>
            <span className="pill">AI draft · Dipak has not reviewed this</span>
            {(
              [
                ["What went well", job.report.strengths],
                ["What to improve", job.report.missed_opportunities],
                ["What to say next", job.report.improvements],
                ["Questions and concerns", job.report.objection_analysis],
                ["Next step", job.report.closing_analysis],
              ] as [string, Finding[]][]
            ).map(([title, rows]) => (
              <section key={title as string}>
                <h2>{title as string}</h2>
                {rows.length ? (
                  rows.map((finding, i) => (
                    <article key={i}>
                      <h3>{finding.title}</h3>
                      <p>{finding.explanation}</p>
                      {finding.evidence.map((e, j) => (
                        <blockquote key={j}>
                          <button
                            className="text-button"
                            onClick={() => {
                              if (audio.current)
                                audio.current.currentTime = e.start_ms / 1000;
                            }}
                          >
                            {time(e.start_ms)}–{time(e.end_ms)}
                          </button>{" "}
                          <small>{e.segment_id}</small> “{e.quote}”
                        </blockquote>
                      ))}
                    </article>
                  ))
                ) : (
                  <p>No supported finding was produced for this section.</p>
                )}
              </section>
            ))}
            <section>
              <h2>Final takeaway</h2>
              <p>{job.report.verdict}</p>
            </section>
            <details>
              <summary>Report details</summary>
              <p>Source SHA-256: {job.report.source_sha256}</p>
              <p>Transcript revision: {job.report.transcript_revision}</p>
              <p>
                Numeric scoring is awaiting approval: the supplied category
                weights total 95 while the source declares 100.
              </p>
              <p>
                Speaker labels remain unverified; transcript revision was
                checked against the selected recording.
                {activeTranscript
                  ? ` Duration: ${time(activeTranscript.duration_ms)}.`
                  : ""}
              </p>
            </details>
            <button className="primary-button" onClick={restart}>
              Analyze another call <ArrowRight size={17} />
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
          <button className="text-button" onClick={() => setAdvanced(true)}>
            Open technical results viewer <ArrowRight size={16} />
          </button>
        </details>
        <footer className="studio-footer">
          <span>Dipak’s Sales Xray · Authority Closers</span>
          <button className="text-button" onClick={() => setAdvanced(true)}>
            Advanced: checkpoints & review tools
          </button>
        </footer>
      </main>
    </div>
  );
}
