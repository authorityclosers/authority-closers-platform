"use client";

import {
  useState,
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { ClipboardPenLine, KeyRound, LockKeyhole, SearchX } from "lucide-react";

import {
  appendCorrection,
  grantEnrollment,
  newIdempotencyKey,
  publishProgramVersion,
  reconcileRecovery,
  retryJob,
  type AdminPermission,
} from "../lib/admin-api";
import { canUseAdminPermission, useAdminSession } from "../lib/admin-session";

type GuardableEvent = {
  preventDefault: () => void;
  stopPropagation: () => void;
};
type GuardableKeyEvent = GuardableEvent & { key: string };

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

export function guardPreviewSubmit(event: GuardableEvent) {
  event.preventDefault();
  event.stopPropagation();
}

export function guardPreviewEnter(event: GuardableKeyEvent) {
  if (event.key !== "Enter") return;
  event.preventDefault();
  event.stopPropagation();
}

type CommandState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "success"; message: string }
  | { status: "error"; message: string };

function safeErrorMessage(error: unknown) {
  return error instanceof Error
    ? error.message
    : "The admin command was rejected. No action was confirmed.";
}

function CommandForm({
  actionLabel,
  children,
  icon,
  id,
  label,
  legend,
  lockNote,
  onExecute,
  permission,
  targetResolved,
}: {
  actionLabel: string;
  children: ReactNode;
  icon: ReactNode;
  id: string;
  label: string;
  legend: string;
  lockNote: string;
  onExecute?: () => Promise<string>;
  permission: AdminPermission;
  targetResolved: boolean;
}) {
  const session = useAdminSession();
  const authorized = canUseAdminPermission(session, permission);
  const enabled = authorized && targetResolved && onExecute !== undefined;
  const [commandState, setCommandState] = useState<CommandState>({
    status: "idle",
  });
  const statusId = `${id}-command-status`;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!enabled || !onExecute) return;
    setCommandState({ status: "submitting" });
    try {
      setCommandState({ status: "success", message: await onExecute() });
    } catch (error) {
      setCommandState({ status: "error", message: safeErrorMessage(error) });
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLFormElement>) {
    if (!enabled) guardPreviewEnter(event);
  }

  const readiness = !authorized
    ? "Requires a verified product admin session"
    : !targetResolved
      ? lockNote
      : !onExecute
        ? "Complete the required command fields"
        : commandState.status === "submitting"
          ? "Command in progress"
          : "Ready for operator review";

  return (
    <form
      className="admin-form"
      aria-label={label}
      aria-describedby={`${id}-readiness ${statusId}`}
      data-admin-command="true"
      data-preview-inert={!enabled ? "true" : "false"}
      noValidate
      onKeyDownCapture={handleKeyDown}
      onSubmit={handleSubmit}
    >
      <p className="form-inert-note" id={`${id}-readiness`}>
        <SearchX size={14} aria-hidden="true" /> {readiness}. raw identifiers
        are never accepted. The server remains the authority for actor, tenant,
        permission, resource ownership, and command validity.
      </p>
      <fieldset disabled={!enabled || commandState.status === "submitting"}>
        <legend>{legend}</legend>
        <div className="field-grid">{children}</div>
        <div className="form-footer">
          <span className="form-lock-note">
            <LockKeyhole size={14} aria-hidden="true" /> {lockNote}
          </span>
          <button
            className={enabled ? "button" : "button button-locked"}
            type="submit"
            disabled={!enabled || commandState.status === "submitting"}
          >
            {icon}
            {commandState.status === "submitting" ? "Working…" : actionLabel}
          </button>
        </div>
      </fieldset>
      <p
        className="form-command-status"
        id={statusId}
        role="status"
        aria-live="polite"
      >
        {commandState.status === "success" || commandState.status === "error"
          ? commandState.message
          : ""}
      </p>
    </form>
  );
}

function ResolutionSeam({
  body,
  id,
  label,
  resolved,
  summary = "No target resolved",
}: {
  body: string;
  id: string;
  label: string;
  resolved: boolean;
  summary?: string;
}) {
  const labelId = `${id}-label`;
  const helpId = `${id}-help`;
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
        <span className="resolution-state">
          {resolved ? "RESOLVED" : "LOOKUP UNAVAILABLE"}
        </span>
      </div>
      <strong>{resolved ? "Server-resolved target" : summary}</strong>
      <p id={helpId}>{body}</p>
      <ol className="resolution-steps" aria-label={`${label} review path`}>
        <li>Authorized lookup</li>
        <li>Resolved summary</li>
        <li>Operator review</li>
      </ol>
      {!resolved && (
        <button className="button lookup-button" type="button" disabled>
          <SearchX size={15} aria-hidden="true" /> Open authorized lookup
          (unavailable)
        </button>
      )}
    </section>
  );
}

export function LearnerLookupForm({
  serverContextVerified = false,
  targetResolved = false,
}: {
  serverContextVerified?: boolean;
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
    <CommandForm
      id="learner-lookup"
      label="Learner diagnosis lookup"
      legend="Diagnosis request"
      permission="learner_diagnose"
      targetResolved={reviewReady}
      lockNote="The diagnosis read endpoint is not installed; no lookup is requested"
      actionLabel="Run diagnosis"
      icon={<KeyRound size={15} aria-hidden="true" />}
    >
      <ResolutionSeam
        id="learner-target"
        label="Learner target"
        resolved={targetResolved}
        body="No admin diagnosis read endpoint currently exists. A future server adapter must return a redacted, tenant-scoped learner summary before this command can be enabled."
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
    </CommandForm>
  );
}

export type CorrectionTarget = Readonly<{
  submissionId: string;
  ifMatch: string;
}>;

export function CorrectionForm({ target }: { target?: CorrectionTarget } = {}) {
  const [decision, setDecision] = useState<
    "approved" | "rejected" | "needs_revision"
  >("approved");
  const [reason, setReason] = useState("");
  return (
    <CommandForm
      id="correction"
      label="Append-only learning correction"
      legend="Correction request"
      permission="learning_correct"
      targetResolved={target !== undefined}
      lockNote="Requires a server-resolved submission revision and If-Match"
      actionLabel="Append correction"
      icon={<ClipboardPenLine size={15} aria-hidden="true" />}
      onExecute={
        target && reason.trim()
          ? async () => {
              await appendCorrection({
                submissionId: target.submissionId,
                decision,
                reason: reason.trim(),
                ifMatch: target.ifMatch,
                idempotencyKey: newIdempotencyKey(),
              });
              return "Correction accepted by the canonical API.";
            }
          : undefined
      }
    >
      <ResolutionSeam
        id="correction-target"
        label="Source and supersession target"
        resolved={target !== undefined}
        body="The correction endpoint accepts only a server-resolved submission, its canonical revision ETag, a bounded decision, and a reason. The original evidence remains immutable."
      />
      <label className="field field-wide" htmlFor="correction-kind">
        <span>Correction decision</span>
        <select
          id="correction-kind"
          value={decision}
          aria-describedby="correction-kind-help"
          onChange={(event) =>
            setDecision(event.currentTarget.value as typeof decision)
          }
          required
        >
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="needs_revision">Needs revision</option>
        </select>
        <small id="correction-kind-help">
          The API validates the decision again against the resolved submission.
        </small>
      </label>
      <label className="field field-wide" htmlFor="correction-reason">
        <span>Reason</span>
        <textarea
          id="correction-reason"
          rows={4}
          value={reason}
          aria-describedby="correction-reason-help"
          onChange={(event) => setReason(event.currentTarget.value)}
          placeholder="Explain the reviewed correction"
          required
        />
        <small id="correction-reason-help">
          A verified, non-blank reason is sent as the canonical audit reason.
        </small>
      </label>
      <p className="field-note field-wide">
        Provenance, actor, tenant, audit sequence, and idempotency scope are
        server-owned by the existing API contract.
      </p>
    </CommandForm>
  );
}

export type EnrollmentGrantTarget = Readonly<{
  personId: string;
  programVersionId: string;
}>;

export function ManualGrantForm({
  target,
}: { target?: EnrollmentGrantTarget } = {}) {
  const [reason, setReason] = useState("");
  return (
    <CommandForm
      id="manual-grant"
      label="Manual enrollment grant"
      legend="Grant request"
      permission="enrollment_grant"
      targetResolved={target !== undefined}
      lockNote="Requires a server-resolved learner and published version"
      actionLabel="Create grant"
      icon={<KeyRound size={15} aria-hidden="true" />}
      onExecute={
        target && reason.trim()
          ? async () => {
              await grantEnrollment({
                ...target,
                reason: reason.trim(),
                idempotencyKey: newIdempotencyKey(),
              });
              return "Enrollment grant accepted by the canonical API.";
            }
          : undefined
      }
    >
      <ResolutionSeam
        id="grant-target"
        label="Learner and program target"
        resolved={target !== undefined}
        body="No admin target lookup is currently installed. A future adapter must resolve the learner, tenant, and eligible published version; raw IDs cannot be entered here."
      />
      <label className="field field-wide" htmlFor="grant-reason">
        <span>Reason</span>
        <textarea
          id="grant-reason"
          rows={4}
          value={reason}
          aria-describedby="grant-reason-help"
          onChange={(event) => setReason(event.currentTarget.value)}
          placeholder="Explain the reviewed grant"
          required
        />
        <small id="grant-reason-help">
          Reason is required audit provenance for a reviewed grant.
        </small>
      </label>
      <p className="field-note field-wide">
        The API derives tenant, policy eligibility, provenance, entitlement, and
        outbox behavior from canonical state.
      </p>
    </CommandForm>
  );
}

export type RetryJobTarget = Readonly<{ jobId: string }>;

export function HeldJobRetryForm({ target }: { target?: RetryJobTarget } = {}) {
  const [reason, setReason] = useState("");
  return (
    <CommandForm
      id="held-job-retry"
      label="Held job retry"
      legend="Retry request"
      permission="job_retry"
      targetResolved={target !== undefined}
      lockNote="Requires a server-resolved retryable job"
      actionLabel="Retry held job"
      icon={<KeyRound size={15} aria-hidden="true" />}
      onExecute={
        target && reason.trim()
          ? async () => {
              await retryJob({
                ...target,
                reason: reason.trim(),
                idempotencyKey: newIdempotencyKey(),
              });
              return "Retry intent accepted by the canonical API.";
            }
          : undefined
      }
    >
      <ResolutionSeam
        id="retry-job-target"
        label="Job target"
        resolved={target !== undefined}
        body="No operations read endpoint currently supplies a job target. Only a trusted tenant-scoped lookup may resolve a retryable held job."
        summary="No queue target resolved"
      />
      <label className="field field-wide" htmlFor="held-job-reason">
        <span>Retry reason</span>
        <textarea
          id="held-job-reason"
          rows={3}
          value={reason}
          aria-describedby="held-job-reason-help"
          onChange={(event) => setReason(event.currentTarget.value)}
          placeholder="Explain the retry"
          required
        />
        <small id="held-job-reason-help">
          Retry intent must be attributable and idempotent.
        </small>
      </label>
    </CommandForm>
  );
}

export type ReconciliationTarget = Readonly<{
  jobIds: readonly string[];
  outboxEventIds: readonly string[];
}>;

export function ReconciliationForm({
  target,
}: { target?: ReconciliationTarget } = {}) {
  const [reason, setReason] = useState("");
  return (
    <CommandForm
      id="restore-reconciliation"
      label="Restore reconciliation"
      legend="Reconciliation request"
      permission="recovery_reconcile"
      targetResolved={target !== undefined}
      lockNote="Requires a server-resolved explicit release set"
      actionLabel="Reconcile release set"
      icon={<KeyRound size={15} aria-hidden="true" />}
      onExecute={
        target && reason.trim()
          ? async () => {
              await reconcileRecovery({
                ...target,
                reason: reason.trim(),
                idempotencyKey: newIdempotencyKey(),
              });
              return "Recovery reconciliation accepted by the canonical API.";
            }
          : undefined
      }
    >
      <ResolutionSeam
        id="reconciliation-target"
        label="Explicit release set"
        resolved={target !== undefined}
        body="No operations read endpoint currently supplies a release set. Pasted lists and raw IDs are not accepted."
        summary="No release set resolved"
      />
      <label className="field field-wide" htmlFor="reconciliation-reason">
        <span>Reconciliation reason</span>
        <textarea
          id="reconciliation-reason"
          rows={3}
          value={reason}
          aria-describedby="reconciliation-reason-help"
          onChange={(event) => setReason(event.currentTarget.value)}
          placeholder="Explain the reviewed release set"
          required
        />
        <small id="reconciliation-reason-help">
          A named reason and restore evidence are required before review.
        </small>
      </label>
    </CommandForm>
  );
}

export type PublishVersionTarget = Readonly<{ programVersionId: string }>;

export function PublishVersionForm({
  target,
}: { target?: PublishVersionTarget } = {}) {
  const [reason, setReason] = useState("");
  return (
    <CommandForm
      id="publish-version"
      label="Publish program version"
      legend="Publish request"
      permission="catalog_publish"
      targetResolved={target !== undefined}
      lockNote="Requires a server-resolved draft version"
      actionLabel="Publish version"
      icon={<KeyRound size={15} aria-hidden="true" />}
      onExecute={
        target && reason.trim()
          ? async () => {
              await publishProgramVersion({ ...target, reason: reason.trim() });
              return "Program version accepted by the canonical API.";
            }
          : undefined
      }
    >
      <ResolutionSeam
        id="publish-version-target"
        label="Program version target"
        resolved={target !== undefined}
        body="No admin catalog read endpoint currently supplies a draft version. Publishing remains disabled until a trusted server response identifies the exact version."
        summary="No version selected"
      />
      <label className="field field-wide" htmlFor="publish-version-reason">
        <span>Publication reason</span>
        <textarea
          id="publish-version-reason"
          rows={3}
          value={reason}
          aria-describedby="publish-version-reason-help"
          onChange={(event) => setReason(event.currentTarget.value)}
          placeholder="Explain the publication review"
          required
        />
        <small id="publish-version-reason-help">
          The existing publish contract accepts a bounded reason; version
          ownership and topology remain server-validated.
        </small>
      </label>
    </CommandForm>
  );
}
