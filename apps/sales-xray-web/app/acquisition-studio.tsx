"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { BrandMark } from "@ac/ui";
import {
  AudioLines,
  ArrowRight,
  Check,
  ChevronDown,
  FileText,
  LoaderCircle,
  Printer,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";
import {
  CallStudio,
  parseProcessingPlan,
  type ProcessingPlan,
} from "./call-studio";
import { StandaloneStudio } from "./standalone-studio";
import { DipakOverview } from "./dipak-overview";
import { ReportExplorer } from "./report-explorer";
import { ReportFactors } from "./report-factors";
import {
  ReportTranscript,
  formatTranscriptTime as time,
} from "./report-transcript";
import {
  parseAcquisitionReport,
  parseTranscript,
  type ReportEvidence,
  type SalesReport,
  type Transcript,
} from "./report-contract";
import {
  ACQUISITION,
  AcquisitionError,
  acquisition,
  parseAllowance,
  parseEntry,
  parsePolicy,
  parseProgress,
  parseSubmission,
  record,
  rememberSubmission,
  savedSubmissionId,
  submissionPath,
  type Allowance,
  type Entry,
  type Progress,
  type Submission,
  type UploadPolicy,
} from "./acquisition-client";
import { UploadCheck } from "./upload-check";
import styles from "./acquisition-studio.module.css";

type Result = { report: SalesReport; transcript: Transcript; claimed: boolean };
const stageNames: Record<string, string> = {
  C2: "Transcribing your call",
  C4: "Checking the conversation",
  C5: "Writing your coaching report",
};
const message = (error: unknown) =>
  error instanceof AcquisitionError
    ? error.message
    : "This result could not be verified. Try again; your completed work stays saved.";

export function AcquisitionStudio() {
  const [entry, setEntry] = useState<Entry | null>(null);
  const [policy, setPolicy] = useState<UploadPolicy | null>(null);
  const [allowance, setAllowance] = useState<Allowance | null>(null);
  const [session, setSession] = useState(false);
  const [claimAvailable, setClaimAvailable] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [audioUrl, setAudioUrl] = useState("");
  const [consent, setConsent] = useState(false);
  const [token, setToken] = useState("");
  const [checkKey, setCheckKey] = useState(0);
  const [submission, setSubmission] = useState<Submission | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [plan, setPlan] = useState<ProcessingPlan | null>(null);
  const [planConsent, setPlanConsent] = useState(false);
  const [planExpired, setPlanExpired] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [pollAttempt, setPollAttempt] = useState(0);
  const [moment, setMoment] = useState<ReportEvidence | null>(null);
  const [playbackMessage, setPlaybackMessage] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const controller = useRef<AbortController | null>(null);
  const active = useRef(true);
  const inFlight = useRef(false);
  const chosenId = useRef("");
  const quoteKey = useRef("");
  const requestedPlan = useRef("");
  const previewUrl = useRef("");
  const onToken = useCallback((value: string) => setToken(value), []);

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      controller.current?.abort();
      if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
    };
  }, []);

  useEffect(() => {
    const abort = new AbortController();
    const signal = abort.signal;
    void (async () => {
      try {
        const config = parseEntry(await acquisition("/entry", { signal }));
        if (signal.aborted) return;
        setEntry(config);
        if (!config.enabled) return;
        const terms = parsePolicy(
          await acquisition("/upload-policy", { signal }),
        );
        let current: Record<string, unknown> | null = null;
        try {
          current = record(await acquisition("/session", { signal }));
        } catch (error) {
          if (!(error instanceof AcquisitionError && error.status === 401))
            throw error;
        }
        if (signal.aborted) return;
        setPolicy(terms);
        setSession(current !== null);
        if (current) {
          setAllowance(parseAllowance(current.allowance));
          setClaimAvailable(
            current.claim_available === true ||
              current.state === "claim_required",
          );
          if (
            current.claim_available === true ||
            current.state === "claim_required"
          )
            return;
        }
        const saved = savedSubmissionId();
        if (saved) {
          const loaded = await acquisition(submissionPath(saved), { signal });
          if (signal.aborted) return;
          const bound = parseSubmission(loaded);
          if (bound.id !== saved) throw new Error("submission_mismatch");
          setSubmission(bound);
          setProgress(parseProgress(loaded, bound));
        }
      } catch (error) {
        if (!signal.aborted) setError(message(error));
      }
    })();
    return () => abort.abort();
  }, [attempt]);

  useEffect(() => {
    const sync = setTimeout(
      () =>
        setPlanExpired(!!plan && plan.expires_at_epoch * 1000 <= Date.now()),
      0,
    );
    const expiry = plan
      ? setTimeout(
          () => setPlanExpired(true),
          Math.max(
            0,
            Math.min(2147483647, plan.expires_at_epoch * 1000 - Date.now()),
          ),
        )
      : undefined;
    return () => {
      clearTimeout(sync);
      if (expiry) clearTimeout(expiry);
    };
  }, [plan]);

  async function getPlan(bound: Submission, signal: AbortSignal) {
    if (!quoteKey.current) quoteKey.current = `report-plan:${bound.id}`;
    return parseProcessingPlan(
      await acquisition(`${submissionPath(bound.id)}/plan/quote`, {
        method: "POST",
        signal,
        headers: { "Idempotency-Key": quoteKey.current },
      }),
      bound.recordingId,
    );
  }

  useEffect(() => {
    if (!submission || result) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    const bound = submission;
    async function poll() {
      try {
        const next = parseProgress(
          await acquisition(submissionPath(bound.id), { signal: abort.signal }),
          bound,
        );
        if (abort.signal.aborted) return;
        setProgress(next);
        if (next.has_report) {
          const transcript = parseTranscript(
            await acquisition(`${submissionPath(bound.id)}/transcript`, {
              signal: abort.signal,
            }),
            bound.sha,
          );
          const verified = parseAcquisitionReport(
            await acquisition(`${submissionPath(bound.id)}/report`, {
              signal: abort.signal,
            }),
            { submissionId: bound.id, recordingId: bound.recordingId },
            transcript,
          );
          if (!abort.signal.aborted) {
            setResult({ ...verified, transcript });
            setError("");
          }
          return;
        }
        if (
          next.local_state === "failed" ||
          next.local_state === "cancelled" ||
          ["held", "cancelled", "completed"].includes(next.state)
        ) {
          setError(
            "This analysis needs attention. Your call is saved; request a fresh plan to continue from completed work.",
          );
          return;
        }
        if (
          next.local_state === "completed" &&
          !next.automatic_progression &&
          requestedPlan.current !== bound.id
        ) {
          requestedPlan.current = bound.id;
          const approved = await getPlan(bound, abort.signal);
          if (!abort.signal.aborted) {
            setPlan(approved);
            setPlanConsent(false);
          }
        }
        failures = 0;
      } catch (error) {
        if (abort.signal.aborted) return;
        failures += 1;
        setError(message(error));
        if (
          failures >= 3 ||
          (error instanceof AcquisitionError &&
            [401, 403, 404, 409].includes(error.status))
        )
          return;
      }
      if (!abort.signal.aborted)
        timer = setTimeout(() => void poll(), failures ? 6000 : 3000);
    }
    void poll();
    return () => {
      abort.abort();
      if (timer) clearTimeout(timer);
    };
  }, [submission, result, pollAttempt]);

  function choose(next: File | undefined) {
    if (!next || inFlight.current || submission) return;
    setError("");
    setDeleted(false);
    setConsent(false);
    setPlanConsent(false);
    if (
      !policy ||
      !/\.(mp3|mpeg|wav|m4a|ogg|flac)$/i.test(next.name) ||
      !next.size ||
      next.size > policy.maximum_file_bytes
    ) {
      setError(
        "Choose an MP3, MPEG, WAV, M4A, OGG or FLAC within the displayed size limit.",
      );
      return;
    }
    chosenId.current = crypto.randomUUID();
    if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
    previewUrl.current = URL.createObjectURL(next);
    setAudioUrl(previewUrl.current);
    setFile(next);
  }

  async function operation(
    label: string,
    task: (signal: AbortSignal) => Promise<void>,
  ) {
    if (inFlight.current) return;
    inFlight.current = true;
    controller.current = new AbortController();
    setBusy(label);
    setError("");
    try {
      await task(controller.current.signal);
    } catch (error) {
      if (active.current && !controller.current.signal.aborted)
        setError(message(error));
    } finally {
      inFlight.current = false;
      if (active.current) setBusy("");
    }
  }

  async function upload() {
    if (!file || !policy || !consent || (!session && !token)) return;
    const selected = file;
    await operation("Uploading and checking your call…", async (signal) => {
      if (!session) {
        try {
          const issued = record(
            await acquisition("/session", {
              method: "POST",
              signal,
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ challenge_token: token }),
            }),
          );
          if (signal.aborted) return;
          setSession(true);
          setAllowance(parseAllowance(issued.allowance));
        } finally {
          if (!signal.aborted) {
            setToken("");
            setCheckKey((key) => key + 1);
          }
        }
      }
      const digest = await crypto.subtle.digest(
        "SHA-256",
        await selected.arrayBuffer(),
      );
      if (signal.aborted) return;
      const sha = Array.from(new Uint8Array(digest), (n) =>
        n.toString(16).padStart(2, "0"),
      ).join("");
      const id = chosenId.current;
      // Only an opaque selector is remembered. Cookies stay HttpOnly; no report,
      // transcript, filename, audio or credential is copied to browser storage.
      rememberSubmission(id);
      const raw = record(
        await acquisition(`${submissionPath(id)}/source`, {
          method: "PUT",
          signal,
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Source-SHA256": sha,
            "X-Upload-Policy": policy.policy_sha256,
            "X-Upload-Consent": "accepted",
          },
          body: selected,
        }),
      );
      const bound = parseSubmission(raw);
      if (bound.id !== id || bound.sha !== sha)
        throw new Error("uploaded_source_mismatch");
      if (signal.aborted) return;
      setAllowance(parseAllowance(raw.allowance));
      setSubmission(bound);
      setConsent(false);
    });
  }

  async function approvePlan() {
    if (
      !submission ||
      !plan ||
      !planConsent ||
      plan.expires_at_epoch * 1000 <= Date.now()
    )
      return;
    const bound = submission,
      shown = plan;
    await operation("Starting your report…", async (signal) => {
      const accepted = parseProcessingPlan(
        await acquisition(`${submissionPath(bound.id)}/plan`, {
          method: "POST",
          signal,
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": `accept-plan:${shown.id}`,
          },
          body: JSON.stringify({
            plan_id: shown.id,
            plan_fingerprint: shown.plan_fingerprint,
            privacy_revision: shown.privacy_revision,
            accepted: true,
          }),
        }),
        bound.recordingId,
      );
      if (!signal.aborted) {
        setPlan(accepted);
        setPlanConsent(false);
        setPollAttempt((n) => n + 1);
      }
    });
  }

  async function freshPlan() {
    if (!submission) return;
    const bound = submission;
    await operation("Checking available analysis…", async (signal) => {
      quoteKey.current = `report-plan:${crypto.randomUUID()}`;
      const next = await getPlan(bound, signal);
      if (!signal.aborted) {
        setPlan(next);
        setPlanConsent(false);
        setPollAttempt((n) => n + 1);
      }
    });
  }

  function reset() {
    if (inFlight.current) return;
    audio.current?.pause();
    if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
    previewUrl.current = "";
    setFile(null);
    setAudioUrl("");
    setSubmission(null);
    setProgress(null);
    setPlan(null);
    setResult(null);
    setConsent(false);
    setPlanConsent(false);
    setMoment(null);
    setPlaybackMessage("");
    setError("");
    setDeleteConfirm(false);
    chosenId.current = "";
    requestedPlan.current = "";
    quoteKey.current = "";
    rememberSubmission(null);
    if (input.current) input.current.value = "";
  }

  async function claim() {
    await operation("Saving with your account…", async (signal) => {
      const claimed = record(
        await acquisition("/claim", { method: "POST", signal }),
      );
      if (claimed.state !== "claimed") throw new Error("claim_unconfirmed");
      if (!signal.aborted) {
        setAllowance(parseAllowance(claimed.allowance));
        setClaimAvailable(false);
        setSession(true);
        setResult(null);
        setAttempt((n) => n + 1);
      }
    });
  }

  async function erase() {
    if (!submission || !deleteConfirm) return;
    await operation("Deleting this call…", async (signal) => {
      const deleted = record(
        await acquisition(submissionPath(submission.id), {
          method: "DELETE",
          signal,
          headers: { "Idempotency-Key": `delete:${submission.id}` },
        }),
      );
      if (
        deleted.id !== submission.recordingId ||
        !["deleting", "deleted"].includes(String(deleted.state))
      )
        throw new Error("delete_unconfirmed");
      if (!signal.aborted) {
        inFlight.current = false;
        reset();
        setDeleted(true);
      }
    });
  }

  function seek(evidence: ReportEvidence) {
    if (!audio.current || !result) return;
    setMoment(evidence);
    setPlaybackMessage(
      `Selected ${time(evidence.start_ms)}–${time(evidence.end_ms)}`,
    );
    audio.current.currentTime = evidence.start_ms / 1000;
    void audio.current
      .play()
      .catch(() =>
        setPlaybackMessage(
          "Press play in the audio controls to hear this moment.",
        ),
      );
  }

  if (entry && !entry.enabled)
    return (
      <StandaloneStudio>
        <CallStudio />
      </StandaloneStudio>
    );
  const blocked =
    progress &&
    (["failed", "cancelled"].includes(progress.local_state || "") ||
      ["held", "cancelled", "completed"].includes(progress.state));
  const report = result?.report;
  const currentStage = progress?.stages.findLast(
    (stage) => stage.state !== "completed",
  );
  const count = allowance
    ? Math.floor(allowance.available_seconds / 60)
    : entry?.allowance_seconds
      ? Math.floor(entry.allowance_seconds / 60)
      : null;
  const source = submission
    ? `${ACQUISITION}${submissionPath(submission.id)}/source`
    : audioUrl;

  return (
    <div className={`xray-app simple-app ${styles.app}`} data-theme="light">
      <header className={`studio-header ${styles.header}`}>
        <Link href="/" aria-label="Sales Xray home">
          <span className="studio-mark">
            <BrandMark />
          </span>
          <span>
            Dipak’s <strong>Sales Xray</strong>
            <small>AUTHORITY CLOSERS</small>
          </span>
        </Link>
        <Link href="/login" className="text-button">
          My AC account <ArrowRight size={15} />
        </Link>
      </header>
      <main id="main" className="studio-main">
        <nav className="studio-steps" aria-label="Analysis steps">
          {["Your call", "Your analysis", "Your next step"].map(
            (label, index) => (
              <span
                key={label}
                aria-current={
                  (report ? 2 : submission ? 1 : 0) === index
                    ? "step"
                    : undefined
                }
              >
                <b>{index + 1}</b>
                {label}
                {index < 2 && <ChevronDown size={15} />}
              </span>
            ),
          )}
        </nav>
        {!report && (
          <div className="studio-intro">
            <p className="eyebrow">YOUR NEXT CALL CAN BE BETTER</p>
            <h1>
              One call. Clear feedback.
              <br />A better next conversation.
            </h1>
            <p>
              See what worked, find the moments you missed, and leave with a
              focused practice plan based on Dipak’s sales principles.
            </p>
          </div>
        )}
        {!entry && !error && (
          <p role="status" className={styles.loading}>
            <LoaderCircle className="spin" size={18} /> Preparing your private
            upload…
          </p>
        )}
        {deleted && (
          <p role="status" className="notice">
            Deletion requested. This call is no longer available here; private
            storage removal is queued.
          </p>
        )}
        {claimAvailable && (
          <aside className={`panel ${styles.claim}`}>
            <ShieldCheck size={22} />
            <div>
              <h2>Keep this call with your AC account</h2>
              <p>
                Save the recording and its report to the account you just signed
                in to.
              </p>
            </div>
            <button
              type="button"
              className="primary-button"
              disabled={!!busy}
              onClick={() => void claim()}
            >
              Save to my account
            </button>
          </aside>
        )}
        <div className={`${styles.layout} ${report ? styles.withReport : ""}`}>
          <section
            className={`panel studio-upload ${styles.upload}`}
            aria-label="Your call"
          >
            {!file && !submission ? (
              <>
                <span className="studio-upload-icon">
                  <Upload size={30} />
                </span>
                <h2>Start with your sales call</h2>
                <p>
                  Choose a recording from your phone, meeting app or computer.
                </p>
                <label
                  className={`primary-button upload-label ${!policy ? styles.disabled : ""}`}
                  htmlFor="acquisition-file"
                >
                  <Upload size={18} /> Choose audio file
                </label>
                <p className="muted">
                  MP3, MPEG, WAV, M4A, OGG or FLAC
                  <br />
                  {policy
                    ? `Up to ${Math.floor(policy.maximum_file_bytes / 1048576)} MB · ${Math.floor(policy.maximum_call_seconds / 60)} minutes per call`
                    : "Checking file limits…"}
                </p>
              </>
            ) : (
              <>
                <div className="studio-file">
                  <span className="studio-upload-icon">
                    <AudioLines size={25} />
                  </span>
                  <div>
                    <h2>{file?.name || "Your saved sales call"}</h2>
                    <p>
                      {result
                        ? time(result.transcript.duration_ms)
                        : file
                          ? `${(file.size / 1048576).toFixed(1)} MB`
                          : "Private original recording"}
                    </p>
                  </div>
                  {!submission && (
                    <button
                      type="button"
                      className="icon-button"
                      aria-label="Remove selected call"
                      disabled={!!busy}
                      onClick={reset}
                    >
                      <X size={18} />
                    </button>
                  )}
                </div>
                <audio
                  ref={audio}
                  src={source || undefined}
                  controls
                  preload="metadata"
                  onError={() =>
                    setPlaybackMessage(
                      "Audio playback is unavailable. Your report remains below.",
                    )
                  }
                  onTimeUpdate={() => {
                    if (
                      moment &&
                      audio.current &&
                      audio.current.currentTime >= moment.end_ms / 1000
                    )
                      audio.current.pause();
                  }}
                />
                <p className="small-text">
                  {submission
                    ? "Select any timestamp to listen to that moment."
                    : "Listen to check this is the right call. Selecting a file does not upload it."}
                </p>
                {playbackMessage && (
                  <p role="status" className="small-text">
                    {playbackMessage}
                  </p>
                )}
              </>
            )}
            <input
              ref={input}
              className="visually-hidden"
              id="acquisition-file"
              type="file"
              accept=".mp3,.mpeg,.wav,.m4a,.ogg,.flac"
              aria-label="Choose sales call audio"
              disabled={!policy || !!busy || !!submission}
              onChange={(event) => choose(event.target.files?.[0])}
            />
            {!submission && policy && (
              <div className={styles.allowance}>
                <ShieldCheck size={16} />
                <span>
                  {count === null
                    ? "Private call analysis"
                    : `${count} free audio minutes ${allowance ? "remaining" : "to get started"}`}
                </span>
              </div>
            )}
            {file && policy && !submission && (
              <div className="studio-consent">
                <h3>Upload privately · ₹0</h3>
                <p>{policy.description}</p>
                <label>
                  <input
                    type="checkbox"
                    checked={consent}
                    disabled={!!busy}
                    onChange={(event) => setConsent(event.target.checked)}
                  />
                  I have permission to analyse this call and accept these upload
                  terms.
                </label>
                {!session && entry?.site_key && entry.challenge_action && (
                  <UploadCheck
                    key={checkKey}
                    siteKey={entry.site_key}
                    action={entry.challenge_action}
                    onToken={onToken}
                  />
                )}
                <button
                  type="button"
                  className="primary-button studio-wide"
                  disabled={
                    !consent ||
                    (!session && !token) ||
                    !!busy ||
                    allowance?.available_seconds === 0
                  }
                  onClick={() => void upload()}
                >
                  {busy ? (
                    <LoaderCircle className="spin" size={17} />
                  ) : (
                    <Upload size={17} />
                  )}
                  {busy || "Upload my call"}
                </button>
              </div>
            )}
            {submission && !report && plan && !plan.accepted && (
              <div className="studio-consent">
                <h3>Ready to analyse your call</h3>
                <div className="studio-cost">
                  <span>Maximum processing cost</span>
                  <strong>{plan.cost_label}</strong>
                </div>
                <p>
                  Your audio minutes are already reserved. Review where your
                  call will be processed, then start your report.
                </p>
                <ul className={styles.providers}>
                  {plan.stages.map((stage) => (
                    <li key={stage.stage}>
                      <strong>{stageNames[stage.stage]}</strong>
                      <span>
                        {stage.provider} · {stage.model}
                      </span>
                      <p>{stage.privacy_notice}</p>
                    </li>
                  ))}
                </ul>
                <p className="small-text">
                  This plan expires{" "}
                  {new Date(plan.expires_at_epoch * 1000).toLocaleString()}.
                </p>
                <label>
                  <input
                    type="checkbox"
                    checked={planConsent}
                    onChange={(event) => setPlanConsent(event.target.checked)}
                    disabled={!!busy}
                  />
                  I approve this exact provider plan, its privacy terms and the
                  displayed cost limit.
                </label>
                <button
                  type="button"
                  className="primary-button studio-wide"
                  disabled={!planConsent || !!busy || planExpired}
                  onClick={() => void approvePlan()}
                >
                  {busy ? (
                    <LoaderCircle className="spin" size={17} />
                  ) : (
                    <AudioLines size={17} />
                  )}
                  {busy || "Analyse my call"}
                </button>
                {planExpired && (
                  <button
                    className="text-button"
                    type="button"
                    disabled={!!busy}
                    onClick={() => void freshPlan()}
                  >
                    Refresh expired plan
                  </button>
                )}
              </div>
            )}
            {submission && !report && (!plan || plan.accepted) && (
              <div className="studio-progress" role="status">
                {blocked || error ? (
                  <FileText size={26} />
                ) : (
                  <LoaderCircle size={26} className="spin" />
                )}
                <h3>
                  {blocked
                    ? "Your call needs attention"
                    : progress?.local_state !== "completed"
                      ? "Checking your recording"
                      : currentStage
                        ? stageNames[currentStage.stage]
                        : "Preparing your analysis"}
                </h3>
                <p>
                  {blocked
                    ? "Completed work remains saved."
                    : "Your call is saved privately. You can leave this page and return in this browser while it is retained."}
                </p>
                <div className={styles.progressRail}>
                  {["C2", "C4", "C5"].map((stage, index) => {
                    const status = progress?.stages
                      .filter((row) => row.stage === stage)
                      .at(-1)?.state;
                    return (
                      <div key={stage} data-complete={status === "completed"}>
                        <span>
                          {status === "completed" ? (
                            <Check size={13} />
                          ) : (
                            index + 1
                          )}
                        </span>
                        <p>
                          {stageNames[stage]}
                          <small>
                            {status === "completed"
                              ? "Complete"
                              : status === "running"
                                ? "In progress"
                                : "Waiting"}
                          </small>
                        </p>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            {submission && (
              <div className={styles.callActions}>
                {!deleteConfirm ? (
                  <button
                    className="text-button"
                    type="button"
                    disabled={!!busy}
                    onClick={() => setDeleteConfirm(true)}
                  >
                    Delete this call
                  </button>
                ) : (
                  <div>
                    <p>
                      Remove this recording and its report? This cannot be
                      undone.
                    </p>
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={!!busy}
                      onClick={() => void erase()}
                    >
                      Delete recording and report
                    </button>
                    <button
                      type="button"
                      className="text-button"
                      disabled={!!busy}
                      onClick={() => setDeleteConfirm(false)}
                    >
                      Keep call
                    </button>
                  </div>
                )}
              </div>
            )}
          </section>
          {!report && (
            <aside className={`panel ${styles.expect}`}>
              <p className="eyebrow">WHAT YOU’LL GET</p>
              <h2>
                The moments that matter.
                <br />
                The next step to practise.
              </h2>
              <ol>
                <li>
                  <b>01</b>
                  <div>
                    <h3>A clear call overview</h3>
                    <p>
                      Understand the outcome, your strengths and the most useful
                      improvements.
                    </p>
                  </div>
                </li>
                <li>
                  <b>02</b>
                  <div>
                    <h3>Feedback you can hear</h3>
                    <p>
                      Jump from a finding to the exact moment in your recording.
                    </p>
                  </div>
                </li>
                <li>
                  <b>03</b>
                  <div>
                    <h3>Your next-call focus</h3>
                    <p>Turn the feedback into one practical rehearsal.</p>
                  </div>
                </li>
              </ol>
              <p className={styles.draftNote}>
                AI-generated coaching based on Dipak’s principles. Each report
                remains a draft until reviewed.
              </p>
            </aside>
          )}
        </div>
        {error && (
          <div className={`notice error ${styles.error}`} role="alert">
            <p>{error}</p>
            <div className={styles.errorActions}>
              <button
                className="secondary-button"
                type="button"
                disabled={!!busy}
                onClick={() => {
                  setError("");
                  if (submission) setPollAttempt((n) => n + 1);
                  else setAttempt((n) => n + 1);
                }}
              >
                Check again
              </button>
              {submission && progress?.local_state === "completed" && (
                <button
                  type="button"
                  className="secondary-button"
                  disabled={!!busy}
                  onClick={() => void freshPlan()}
                >
                  Request a fresh plan
                </button>
              )}
              <Link className="text-button" href="/login">
                Sign in
              </Link>
            </div>
          </div>
        )}
        {result && report && (
          <section
            className={`studio-report panel ${styles.report}`}
            aria-label="Sales call report"
          >
            <p className="eyebrow">YOUR SALES CALL REPORT</p>
            <h1>What to keep. What to change.</h1>
            <p className="studio-report-summary">{report.summary}</p>
            <span className="pill">AI draft · not yet reviewed by Dipak</span>
            <div className="studio-report-actions">
              <button
                type="button"
                className="secondary-button"
                onClick={() => window.print()}
              >
                <Printer size={16} /> Print / save PDF
              </button>
              <button
                type="button"
                className="secondary-button"
                disabled={!!busy}
                onClick={reset}
              >
                Analyse another call <ArrowRight size={16} />
              </button>
            </div>
            <div
              className="studio-report-metrics"
              role="list"
              aria-label="Report measurements"
            >
              <div className="studio-report-metric" role="listitem">
                <span>Call length</span>
                <strong>{time(result.transcript.duration_ms)}</strong>
                <small>Source recording clock</small>
              </div>
              <div className="studio-report-metric" role="listitem">
                <span>Transcript segments</span>
                <strong>{result.transcript.segments.length}</strong>
                <small>Original words and script</small>
              </div>
              <div className="studio-report-metric" role="listitem">
                <span>Next improvements</span>
                <strong>{report.improvements.length}</strong>
                <small>A focused practice plan</small>
              </div>
            </div>
            <ReportExplorer
              label="Explore your sales report"
              panels={[
                {
                  id: "overview",
                  label: "Overview",
                  content: (
                    <DipakOverview report={report} onSelectEvidence={seek} />
                  ),
                },
                {
                  id: "factors",
                  label: "Sales factors",
                  content: (
                    <ReportFactors
                      dimensions={report.dimensions}
                      language="en"
                    />
                  ),
                },
                {
                  id: "transcript",
                  label: "Transcript & moments",
                  content: (
                    <ReportTranscript
                      transcript={result.transcript}
                      language="en"
                      onSelect={(segment) =>
                        seek({
                          segment_id: segment.id,
                          quote: segment.text,
                          start_ms: segment.start_ms,
                          end_ms: segment.end_ms,
                        })
                      }
                    />
                  ),
                },
              ]}
            />
            {!result.claimed && (
              <aside className={styles.claim}>
                <ShieldCheck size={22} />
                <div>
                  <h2>Keep your report with your AC account</h2>
                  <p>
                    Your overview is free. Sign in to keep your calls together.
                  </p>
                </div>
                <Link href="/login" className="primary-button">
                  Sign in to save this call <ArrowRight size={16} />
                </Link>
              </aside>
            )}
          </section>
        )}
      </main>
    </div>
  );
}
