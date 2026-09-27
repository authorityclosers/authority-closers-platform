"use client";

import { useRef, useState } from "react";

import {
  AcquisitionError,
  parseProgress,
  parseSubmission,
  submissionPath,
  UUID,
  acquisition,
  type Progress,
  type Submission,
} from "../acquisition-client";
import styles from "./provider-review.module.css";

const SHA = /^[a-f0-9]{64}$/;
const MAX_C5_COST_PAISE = 2_200;
const MAX_PROJECT_BUDGET_PAISE = 250_000;
const PURPOSE = "acquisition_c5_benchmark";
const MODEL = "gpt-6-luna";

export type BenchmarkQuote = {
  id: string;
  recording_id: string;
  stage: "C5";
  provider: "openai";
  model: typeof MODEL;
  quote_fingerprint: string;
  privacy_revision: string;
  privacy_notice: string;
  cost_label: string;
  max_cost_paise: number;
  budget_cap_paise: number;
  entitlement_seconds: number;
  input_sha256: string;
  expires_at_epoch: number;
  accepted: boolean;
  purpose: typeof PURPOSE;
  benchmark_approval_id: string;
};

export type BenchmarkQuoteErrorCode =
  | "malformed"
  | "source_mismatch"
  | "scope"
  | "expired";

export class BenchmarkQuoteError extends Error {
  constructor(readonly code: BenchmarkQuoteErrorCode) {
    super("The benchmark quote did not match the verified owner scope.");
    this.name = "BenchmarkQuoteError";
  }
}

function object(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function boundedText(value: unknown, maximum: number): value is string {
  return (
    typeof value === "string" && value.length > 0 && value.length <= maximum
  );
}

function boundedInteger(value: unknown, maximum: number): value is number {
  return (
    Number.isSafeInteger(value) &&
    (value as number) >= 0 &&
    (value as number) <= maximum
  );
}

export function parseSavedBenchmarkSource(
  value: unknown,
  expectedSubmissionId: string,
): Submission {
  try {
    const submission = parseSubmission(value);
    const progress: Progress = parseProgress(value, submission);
    const completed = new Set(
      progress.stages
        .filter((stage) => stage.state === "completed")
        .map((stage) => stage.stage),
    );
    if (
      submission.id !== expectedSubmissionId ||
      !progress.has_report ||
      !completed.has("C2") ||
      !completed.has("C4")
    )
      throw new BenchmarkQuoteError("source_mismatch");
    return submission;
  } catch (error) {
    if (error instanceof BenchmarkQuoteError) throw error;
    throw new BenchmarkQuoteError("malformed");
  }
}

export function parseBenchmarkQuote(
  value: unknown,
  expectedRecordingId: string,
  nowEpoch = Math.floor(Date.now() / 1000),
): BenchmarkQuote {
  const quote = object(value);
  if (
    !quote ||
    typeof quote.id !== "string" ||
    !UUID.test(quote.id) ||
    typeof quote.recording_id !== "string" ||
    !UUID.test(quote.recording_id) ||
    quote.stage !== "C5" ||
    quote.provider !== "openai" ||
    quote.model !== MODEL ||
    typeof quote.quote_fingerprint !== "string" ||
    !SHA.test(quote.quote_fingerprint) ||
    !boundedText(quote.privacy_revision, 128) ||
    !boundedText(quote.privacy_notice, 4000) ||
    !boundedText(quote.cost_label, 300) ||
    !boundedInteger(quote.max_cost_paise, MAX_PROJECT_BUDGET_PAISE) ||
    !boundedInteger(quote.budget_cap_paise, MAX_PROJECT_BUDGET_PAISE) ||
    quote.max_cost_paise === 0 ||
    quote.max_cost_paise > quote.budget_cap_paise ||
    quote.entitlement_seconds !== 0 ||
    typeof quote.input_sha256 !== "string" ||
    !SHA.test(quote.input_sha256) ||
    !boundedInteger(quote.expires_at_epoch, Number.MAX_SAFE_INTEGER) ||
    typeof quote.accepted !== "boolean" ||
    quote.purpose !== PURPOSE ||
    typeof quote.benchmark_approval_id !== "string" ||
    !UUID.test(quote.benchmark_approval_id)
  )
    throw new BenchmarkQuoteError("malformed");

  if (quote.recording_id !== expectedRecordingId)
    throw new BenchmarkQuoteError("source_mismatch");
  if (
    quote.max_cost_paise > MAX_C5_COST_PAISE ||
    quote.budget_cap_paise > MAX_PROJECT_BUDGET_PAISE
  )
    throw new BenchmarkQuoteError("scope");
  if (quote.expires_at_epoch <= nowEpoch)
    throw new BenchmarkQuoteError("expired");

  return quote as BenchmarkQuote;
}

type AcceptedRun = { id: string; state: "queued" | "running" | "completed" };

function parseAcceptedRun(value: unknown, quote: BenchmarkQuote): AcceptedRun {
  const result = object(value);
  if (
    !result ||
    typeof result.id !== "string" ||
    !UUID.test(result.id) ||
    result.recording_id !== quote.recording_id ||
    result.purpose !== PURPOSE ||
    result.benchmark_approval_id !== quote.benchmark_approval_id ||
    !["queued", "running", "completed"].includes(result.state as string)
  )
    throw new Error("acceptance_unconfirmed");
  return { id: result.id, state: result.state as AcceptedRun["state"] };
}

type Phase =
  | "ready"
  | "preparing"
  | "quoted"
  | "already_accepted"
  | "accepting"
  | "queued"
  | "stopped"
  | "uncertain";

function idempotencyKey(kind: "quote" | "accept"): string {
  const id = globalThis.crypto?.randomUUID?.();
  if (!id) throw new Error("secure_random_unavailable");
  return `acquisition-c5-benchmark:${kind}:${id}`;
}

function safeReference(
  error: unknown,
  quote: BenchmarkQuote | null,
): string | null {
  if (error instanceof AcquisitionError && error.requestId)
    return error.requestId;
  return quote?.id ?? null;
}

export function ProviderReview({ submissionId }: { submissionId: string }) {
  const [phase, setPhase] = useState<Phase>("ready");
  const [source, setSource] = useState<Submission | null>(null);
  const [quote, setQuote] = useState<BenchmarkQuote | null>(null);
  const [run, setRun] = useState<AcceptedRun | null>(null);
  const [errorReference, setErrorReference] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [privacyAccepted, setPrivacyAccepted] = useState(false);
  const quoteStarted = useRef(false);
  const acceptStarted = useRef(false);
  const quoteKey = useRef<string | null>(null);
  const acceptKey = useRef<string | null>(null);

  const prepareQuote = async () => {
    if (quoteStarted.current) return;
    quoteStarted.current = true;
    setPhase("preparing");
    setMessage(null);
    setErrorReference(null);
    let candidateReference: string | null = null;
    try {
      const verifiedSource = parseSavedBenchmarkSource(
        await acquisition(submissionPath(submissionId)),
        submissionId,
      );
      setSource(verifiedSource);
      quoteKey.current ??= idempotencyKey("quote");
      const rawQuote = await acquisition(
        `${submissionPath(submissionId)}/c5-benchmark/quote`,
        {
          method: "POST",
          headers: { "Idempotency-Key": quoteKey.current },
        },
      );
      const rawReference = object(rawQuote)?.id;
      if (typeof rawReference === "string" && UUID.test(rawReference))
        candidateReference = rawReference;
      const verifiedQuote = parseBenchmarkQuote(
        rawQuote,
        verifiedSource.recordingId,
      );
      setQuote(verifiedQuote);
      setPhase(verifiedQuote.accepted ? "already_accepted" : "quoted");
    } catch (error) {
      setErrorReference(
        safeReference(error, quote) ?? candidateReference ?? submissionId,
      );
      setMessage(
        error instanceof BenchmarkQuoteError &&
          error.code === "source_mismatch" &&
          !quoteKey.current
          ? "This saved call does not match the required owner-approved C2 and C4 source. No benchmark quote was requested."
          : "The saved call or exact benchmark quote could not be verified. This page stopped without accepting or retrying it.",
      );
      setPhase("stopped");
    }
  };

  const acceptQuote = async () => {
    if (!quote || !privacyAccepted || acceptStarted.current) return;
    acceptStarted.current = true;
    setPhase("accepting");
    setMessage(null);
    try {
      acceptKey.current ??= idempotencyKey("accept");
      const rawRun = await acquisition(
        `${submissionPath(submissionId)}/c5-benchmark`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": acceptKey.current,
          },
          body: JSON.stringify({
            quote_id: quote.id,
            quote_fingerprint: quote.quote_fingerprint,
            privacy_revision: quote.privacy_revision,
            accepted: true,
          }),
        },
      );
      const acceptedRun = parseAcceptedRun(rawRun, quote);
      setRun(acceptedRun);
      setErrorReference(quote.id);
      setPhase("queued");
    } catch (error) {
      setErrorReference(safeReference(error, quote));
      setMessage(
        "We could not confirm whether this acceptance was recorded. Do not retry it. Keep the quote reference and contact the AC team if you need the result checked.",
      );
      setPhase("uncertain");
    }
  };

  const busy = phase === "preparing" || phase === "accepting";
  return (
    <main className={styles.page} aria-labelledby="provider-review-title">
      <p className={styles.eyebrow}>Saved call · owner action</p>
      <h1 id="provider-review-title">OpenAI comparison</h1>
      <p className={styles.intro}>
        Prepare one exact C5 quote for this saved call. The server verifies the
        signed owner approval and reuses its completed C2 and C4 work. Nothing
        is accepted until you review the quote and confirm the privacy terms.
      </p>

      {phase === "ready" && (
        <button className={styles.primary} onClick={prepareQuote}>
          Prepare exact quote
        </button>
      )}
      {phase === "preparing" && (
        <p role="status">Checking this saved call and preparing its quote…</p>
      )}

      {source && (
        <section
          className={styles.details}
          aria-label="Verified saved call source"
        >
          <h2>Verified saved call</h2>
          <dl>
            <div>
              <dt>Recording</dt>
              <dd>{source.recordingId}</dd>
            </div>
            <div>
              <dt>Source SHA-256</dt>
              <dd className={styles.digest}>{source.sha}</dd>
            </div>
          </dl>
        </section>
      )}

      {quote && (
        <section className={styles.details} aria-label="Exact benchmark quote">
          <h2>Exact quote</h2>
          <dl>
            <div>
              <dt>Provider</dt>
              <dd>{quote.provider}</dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd>{quote.model}</dd>
            </div>
            <div>
              <dt>Stage</dt>
              <dd>{quote.stage}</dd>
            </div>
            <div>
              <dt>Provider input SHA-256</dt>
              <dd className={styles.digest}>{quote.input_sha256}</dd>
            </div>
            <div>
              <dt>Maximum cost</dt>
              <dd>
                {quote.cost_label} ({quote.max_cost_paise} paise)
              </dd>
            </div>
            <div>
              <dt>Approved project cap</dt>
              <dd>{quote.budget_cap_paise} paise</dd>
            </div>
            <div>
              <dt>Additional entitlement</dt>
              <dd>{quote.entitlement_seconds} seconds</dd>
            </div>
            <div>
              <dt>Privacy revision</dt>
              <dd>{quote.privacy_revision}</dd>
            </div>
            <div>
              <dt>Quote expires</dt>
              <dd>{new Date(quote.expires_at_epoch * 1000).toISOString()}</dd>
            </div>
            <div>
              <dt>Approval reference</dt>
              <dd>{quote.benchmark_approval_id}</dd>
            </div>
          </dl>
          <p className={styles.privacy}>{quote.privacy_notice}</p>
          <p className={styles.tokenNote}>
            The quote response does not disclose a token count. The server-held
            benchmark approval enforces the C5 output limit; this page does not
            infer or change it.
          </p>
        </section>
      )}

      {phase === "quoted" && quote && (
        <section className={styles.confirm} aria-label="Owner confirmation">
          <label className={styles.consent}>
            <input
              type="checkbox"
              checked={privacyAccepted}
              onChange={(event) =>
                setPrivacyAccepted(event.currentTarget.checked)
              }
            />
            <span>
              I approve one OpenAI C5 comparison for this saved call under this
              exact quote and privacy notice.
            </span>
          </label>
          <button
            className={styles.primary}
            onClick={acceptQuote}
            disabled={!privacyAccepted || busy}
          >
            Accept quote and queue one comparison
          </button>
        </section>
      )}

      {phase === "already_accepted" && (
        <p className={styles.notice} role="status">
          This exact quote is already accepted. No second request was sent.
        </p>
      )}
      {phase === "queued" && run && (
        <p className={styles.notice} role="status">
          One comparison was accepted. Current state: {run.state}. Run
          reference: {run.id}.
        </p>
      )}
      {phase === "stopped" && message && (
        <p className={styles.error} role="alert">
          {message}
        </p>
      )}
      {phase === "uncertain" && message && (
        <p className={styles.error} role="alert">
          {message}
        </p>
      )}
      {busy && phase === "accepting" && (
        <p role="status">Recording your explicit approval…</p>
      )}
      {errorReference && (
        <p className={styles.reference}>Reference: {errorReference}</p>
      )}
    </main>
  );
}
