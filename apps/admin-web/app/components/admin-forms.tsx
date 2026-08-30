"use client";

import { useState, type ChangeEvent, type ReactNode } from "react";
import { ClipboardPenLine, KeyRound, LockKeyhole, SearchX } from "lucide-react";

type GuardableEvent = {
  preventDefault: () => void;
  stopPropagation: () => void;
};

type GuardableKeyEvent = GuardableEvent & { key: string };

/**
 * Purpose is deliberately a closed set. The API must independently authorize
 * the same value; this UI value is only a constrained review seam.
 */
export const DIAGNOSIS_PURPOSES = [
  { value: "learner_support", label: "Learner support" },
  { value: "safeguarding_review", label: "Safeguarding review" },
  { value: "accessibility_review", label: "Accessibility review" },
] as const;

export type DiagnosisPurpose = (typeof DIAGNOSIS_PURPOSES)[number]["value"];

export function isDiagnosisPurpose(value: string): value is DiagnosisPurpose {
  return DIAGNOSIS_PURPOSES.some((purpose) => purpose.value === value);
}

export function isDiagnosisReviewReady({
  purpose,
  reviewConfirmed,
  targetResolved,
  serverContextVerified,
}: {
  purpose: string;
  reviewConfirmed: boolean;
  targetResolved: boolean;
  serverContextVerified: boolean;
}) {
  return (
    serverContextVerified &&
    targetResolved &&
    isDiagnosisPurpose(purpose) &&
    reviewConfirmed
  );
}

/**
 * Preview forms deliberately have no successful controls, action, or submitter.
 * These guards are a second line of defense after hydration; API wiring must
 * replace the whole inert seam rather than merely enabling a button.
 */
export function guardPreviewSubmit(event: GuardableEvent) {
  event.preventDefault();
  event.stopPropagation();
}

export function guardPreviewEnter(event: GuardableKeyEvent) {
  if (event.key !== "Enter") return;
  event.preventDefault();
  event.stopPropagation();
}

function PreviewForm({
  actionLabel,
  children,
  enabled = false,
  footerAction,
  id,
  label,
  legend,
  lockNote,
  icon,
}: {
  actionLabel: string;
  children: ReactNode;
  enabled?: boolean;
  footerAction?: ReactNode;
  id: string;
  label: string;
  legend: string;
  lockNote: string;
  icon: ReactNode;
}) {
  const inertNoteId = id + "-inert-note";

  return (
    <form
      className="admin-form"
      aria-label={label}
      aria-describedby={inertNoteId}
      data-preview-inert="true"
      noValidate
      onKeyDownCapture={guardPreviewEnter}
      onSubmit={guardPreviewSubmit}
    >
      <p className="form-inert-note" id={inertNoteId}>
        <SearchX size={14} aria-hidden="true" /> Inert preview: raw identifiers
        are not accepted. An authenticated server lookup must resolve a target
        before review can begin.
      </p>
      <fieldset disabled={!enabled} aria-describedby={inertNoteId}>
        <legend>{legend}</legend>
        <div className="field-grid">{children}</div>
        <div className="form-footer">
          <span className="form-lock-note">
            <LockKeyhole size={14} aria-hidden="true" /> {lockNote}
          </span>
          {footerAction ?? (
            <button className="button button-locked" type="button" disabled>
              {icon}
              {actionLabel}
            </button>
          )}
        </div>
      </fieldset>
    </form>
  );
}

function ResolutionSeam({
  body,
  id,
  label,
  summary = "No target resolved",
}: {
  body: string;
  id: string;
  label: string;
  summary?: string;
}) {
  const labelId = id + "-label";
  const helpId = id + "-help";

  return (
    <section
      className="resolution-seam field-wide"
      aria-labelledby={labelId}
      aria-describedby={helpId}
    >
      <div className="resolution-topline">
        <span className="field-label" id={labelId}>
          {label}
        </span>
        <span className="resolution-state">LOOKUP UNAVAILABLE</span>
      </div>
      <strong>{summary}</strong>
      <p id={helpId}>{body}</p>
      <ol className="resolution-steps" aria-label={label + " review path"}>
        <li>Authorized lookup</li>
        <li>Resolved summary</li>
        <li>Operator review</li>
      </ol>
      <button className="button lookup-button" type="button" disabled>
        <SearchX size={15} aria-hidden="true" /> Open authorized lookup
        (unavailable)
      </button>
    </section>
  );
}

export function LearnerLookupForm({
  serverContextVerified = false,
  targetResolved = false,
}: {
  /**
   * Only a trusted server adapter may ever set this. The current proxy passes
   * no server context, so the default keeps this shell fail-closed.
   */
  serverContextVerified?: boolean;
  /** A trusted server lookup must provide a redacted, tenant-scoped summary. */
  targetResolved?: boolean;
}) {
  const [purpose, setPurpose] = useState<DiagnosisPurpose | "">("");
  const [reviewConfirmed, setReviewConfirmed] = useState(false);
  const reviewReady = isDiagnosisReviewReady({
    purpose,
    reviewConfirmed,
    targetResolved,
    serverContextVerified,
  });

  function handlePurposeChange(event: ChangeEvent<HTMLSelectElement>) {
    const nextPurpose = event.currentTarget.value;
    setPurpose(isDiagnosisPurpose(nextPurpose) ? nextPurpose : "");
    setReviewConfirmed(false);
  }

  return (
    <PreviewForm
      id="learner-lookup"
      label="Learner diagnosis lookup"
      legend="Diagnosis request"
      lockNote="Requires learner_diagnose"
      actionLabel={
        reviewReady
          ? "Review diagnosis request"
          : "Review diagnosis request (locked)"
      }
      enabled={serverContextVerified}
      footerAction={
        <button
          className="button button-locked"
          type="button"
          disabled={!reviewReady}
          onClick={guardPreviewSubmit}
        >
          <KeyRound size={15} aria-hidden="true" />
          {reviewReady
            ? "Review diagnosis request"
            : "Review diagnosis request (locked)"}
        </button>
      }
      icon={<KeyRound size={15} aria-hidden="true" />}
    >
      <ResolutionSeam
        id="learner-target"
        label="Learner target"
        body="The browser cannot accept an email, UUID, or tenant hint. A trusted server lookup must return a redacted learner summary in the active tenant."
      />
      <label className="field field-wide" htmlFor="diagnosis-purpose">
        <span>Diagnosis purpose</span>
        <select
          id="diagnosis-purpose"
          value={purpose}
          aria-describedby="diagnosis-purpose-help"
          onChange={handlePurposeChange}
          required
        >
          <option value="" disabled>
            Select an explicit purpose
          </option>
          {DIAGNOSIS_PURPOSES.map(({ label, value }) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <small id="diagnosis-purpose-help">
          Choose one bounded purpose. There is no default purpose and free-text
          values are rejected.
        </small>
      </label>
      <label
        className="field field-wide review-confirmation"
        htmlFor="diagnosis-review-confirmed"
      >
        <input
          id="diagnosis-review-confirmed"
          type="checkbox"
          checked={reviewConfirmed}
          aria-describedby="diagnosis-review-help"
          disabled={!serverContextVerified || !isDiagnosisPurpose(purpose)}
          onChange={(event) => setReviewConfirmed(event.currentTarget.checked)}
        />
        <span>I confirm this authorized review has the required boundary.</span>
        <small id="diagnosis-review-help">
          Confirm permission, active tenant, the selected purpose, redaction,
          and append-only audit before any diagnosis request is allowed.
        </small>
      </label>
    </PreviewForm>
  );
}

export function CorrectionForm() {
  return (
    <PreviewForm
      id="correction"
      label="Append-only learning correction"
      legend="Correction request"
      lockNote="Preview only · no event appended"
      actionLabel="Append correction (locked)"
      icon={<ClipboardPenLine size={15} aria-hidden="true" />}
    >
      <ResolutionSeam
        id="correction-target"
        label="Source and supersession target"
        body="A trusted lookup must resolve the tenant-owned learner or activity and an eligible event. Pasted record or event IDs are not accepted by this preview."
      />
      <label className="field field-wide" htmlFor="correction-kind">
        <span>Correction kind</span>
        <select
          id="correction-kind"
          defaultValue=""
          aria-describedby="correction-kind-help"
          required
        >
          <option value="" disabled>
            Available after target resolution
          </option>
        </select>
        <small id="correction-kind-help">
          The API must return correction kinds valid for the resolved target.
        </small>
      </label>
      <label className="field field-wide" htmlFor="correction-reason">
        <span>Reason</span>
        <textarea
          id="correction-reason"
          rows={4}
          placeholder="Available after an authorized target is resolved"
          aria-describedby="correction-reason-help"
          required
        />
        <small id="correction-reason-help">
          A verified, non-blank reason is required for review.
        </small>
      </label>
      <label className="field field-wide" htmlFor="correction-provenance">
        <span>Provenance / case reference</span>
        <textarea
          id="correction-provenance"
          rows={3}
          placeholder="Available after an authorized target is resolved"
          aria-describedby="correction-provenance-help"
          required
        />
        <small id="correction-provenance-help">
          Provenance belongs to a new append event; the original remains
          immutable.
        </small>
      </label>
    </PreviewForm>
  );
}

export function ManualGrantForm() {
  return (
    <PreviewForm
      id="manual-grant"
      label="Manual enrollment grant"
      legend="Grant request"
      lockNote="Preview only · no entitlement created"
      actionLabel="Create grant (locked)"
      icon={<KeyRound size={15} aria-hidden="true" />}
    >
      <ResolutionSeam
        id="grant-target"
        label="Learner and program target"
        body="A trusted lookup must resolve a tenant-owned learner and an eligible published version. Raw learner or catalog IDs cannot enter this form."
      />
      <label className="field field-wide" htmlFor="grant-reason">
        <span>Reason</span>
        <textarea
          id="grant-reason"
          rows={4}
          placeholder="Available after an authorized target is resolved"
          aria-describedby="grant-reason-help"
          required
        />
        <small id="grant-reason-help">
          Reason is required audit provenance for a reviewed grant.
        </small>
      </label>
      <label className="field field-wide" htmlFor="grant-provenance">
        <span>Provenance</span>
        <textarea
          id="grant-provenance"
          rows={3}
          placeholder="Available after an authorized target is resolved"
          aria-describedby="grant-provenance-help"
          required
        />
        <small id="grant-provenance-help">
          Analytics, ERP, and provider callbacks cannot grant access.
        </small>
      </label>
    </PreviewForm>
  );
}

export function HeldJobRetryForm() {
  return (
    <PreviewForm
      id="held-job-retry"
      label="Held job retry"
      legend="Retry request"
      lockNote="Requires job_retry"
      actionLabel="Retry held job (locked)"
      icon={<KeyRound size={15} aria-hidden="true" />}
    >
      <ResolutionSeam
        id="retry-job-target"
        label="Job target"
        body="Only a trusted queue lookup may return a tenant-owned job with a valid retryable state. This preview accepts no pasted job identifier."
        summary="No queue target resolved"
      />
      <label className="field field-wide" htmlFor="held-job-reason">
        <span>Retry reason</span>
        <textarea
          id="held-job-reason"
          rows={3}
          placeholder="Available after an authorized job is resolved"
          aria-describedby="held-job-reason-help"
          required
        />
        <small id="held-job-reason-help">
          Retry intent must be attributable, idempotent, and reviewed.
        </small>
      </label>
    </PreviewForm>
  );
}

export function ReconciliationForm() {
  return (
    <PreviewForm
      id="restore-reconciliation"
      label="Restore reconciliation"
      legend="Reconciliation request"
      lockNote="Requires recovery_reconcile"
      actionLabel="Reconcile release set (locked)"
      icon={<KeyRound size={15} aria-hidden="true" />}
    >
      <ResolutionSeam
        id="reconciliation-target"
        label="Explicit release set"
        body="A trusted operations lookup must resolve and summarize each eligible held job. Pasted lists and raw job IDs are not accepted."
        summary="No release set resolved"
      />
      <label className="field field-wide" htmlFor="reconciliation-reason">
        <span>Reconciliation reason</span>
        <textarea
          id="reconciliation-reason"
          rows={3}
          placeholder="Available after an authorized release set is resolved"
          aria-describedby="reconciliation-reason-help"
          required
        />
        <small id="reconciliation-reason-help">
          A named reason and restore evidence are required before review.
        </small>
      </label>
    </PreviewForm>
  );
}
