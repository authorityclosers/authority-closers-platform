"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  CheckCircle2,
  CircleAlert,
  Clock3,
  FileCheck2,
  LoaderCircle,
  Plus,
  RefreshCw,
  ShieldCheck,
  UserRound,
  XCircle,
} from "lucide-react";

import { AdminShell } from "../../components/admin-shell";
import { SectionHeading } from "../../components/ops-primitives";
import {
  createReviewAssignment,
  loadReviewAssignments,
  newReviewIdempotencyKey,
  reviewError,
  reviewLenses,
  revokeReviewAssignment,
  type ReviewAssignment,
  type ReviewMode,
  type ReviewQueueState,
} from "./review-api";
import styles from "./review-workspace.module.css";
import { AdminReviewDetails } from "./admin-review-details";
import { RecordingsInventory } from "./recordings-inventory";
import {
  ReviewInvitationPanel,
  REVIEWER_INVITATIONS_AVAILABLE,
} from "./review-invitation-panel";
import { localReviewDate, reviewDateEpoch } from "./review-date";

const lensLabels: Record<ReviewMode, { label: string; detail: string }> = {
  sales: { label: "Sales expert", detail: "Coaching and call quality" },
  technical: { label: "Developer", detail: "Transcript and analysis accuracy" },
  ux: { label: "Experience reviewer", detail: "Clarity and ease of use" },
};

const stateLabels: Record<ReviewAssignment["state"], string> = {
  assigned: "Assigned",
  in_progress: "In progress",
  submitted: "Submitted",
  revoked: "Revoked",
  expired: "Expired",
};

type CreateMutation =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "success"; assignment: ReviewAssignment }
  | { status: "error"; message: string; retryable: boolean };

type RevokeMutation =
  | { status: "idle" }
  | { status: "submitting"; assignmentId: string }
  | { status: "success"; assignment: ReviewAssignment }
  | {
      status: "error";
      assignmentId: string;
      message: string;
      retryable: boolean;
    };

type CreateIntent = Readonly<{
  runId: string;
  reviewerPersonId: string;
  allowedLenses: readonly ReviewMode[];
  expiresAtEpoch: number;
}>;

type FormErrors = Partial<
  Record<
    "runId" | "reviewerPersonId" | "allowedLenses" | "expiresAtEpoch",
    string
  >
>;

function formatEpoch(epoch: number): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(epoch * 1000));
}

function shortId(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-4)}`;
}

function mergeAssignment(
  items: readonly ReviewAssignment[],
  next: ReviewAssignment,
): ReviewAssignment[] {
  const existing = items.findIndex((item) => item.id === next.id);
  if (existing === -1) return [next, ...items];
  return items.map((item) => (item.id === next.id ? next : item));
}

function validateCreateIntent(
  runId: string,
  reviewerPersonId: string,
  allowedLenses: readonly ReviewMode[],
  expiry: string,
): { intent?: CreateIntent; errors: FormErrors } {
  const errors: FormErrors = {};
  const uuidPattern =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  const runValue = runId.trim();
  const reviewerValue = reviewerPersonId.trim();
  if (!uuidPattern.test(runValue)) errors.runId = "Enter a canonical UUID.";
  if (!uuidPattern.test(reviewerValue)) {
    errors.reviewerPersonId = "Enter a canonical UUID.";
  }
  if (allowedLenses.length === 0) {
    errors.allowedLenses = "Choose at least one review lens.";
  }
  const expiresAtEpoch = reviewDateEpoch(expiry.trim());
  if (!Number.isInteger(expiresAtEpoch) || expiresAtEpoch <= 0) {
    errors.expiresAtEpoch = "Choose a valid date and time.";
  } else if (expiresAtEpoch <= Math.floor(Date.now() / 1000)) {
    errors.expiresAtEpoch = "Expiry must be in the future.";
  }
  if (Object.keys(errors).length > 0) return { errors };
  return {
    errors,
    intent: {
      runId: runValue,
      reviewerPersonId: reviewerValue,
      allowedLenses: [...allowedLenses],
      expiresAtEpoch,
    },
  };
}

function StatePanel({
  state,
  onRetry,
}: {
  state: ReviewQueueState;
  onRetry: () => void;
}) {
  if (state.status === "loading" && state.items.length === 0) {
    return (
      <div className={styles.queueState} role="status" aria-live="polite">
        <LoaderCircle size={26} className="spin" aria-hidden="true" />
        <strong>Checking the review assignment queue</strong>
        <p>Loading the latest assignments for this admin session.</p>
      </div>
    );
  }
  if (state.status === "error" && state.items.length === 0) {
    return (
      <div className={styles.queueState} role="alert">
        <CircleAlert size={28} aria-hidden="true" />
        <strong>{state.message}</strong>
        <p>Retry the queue before creating a new handoff.</p>
        {state.retryable ? (
          <button
            className="button button-secondary"
            type="button"
            onClick={onRetry}
          >
            <RefreshCw size={15} aria-hidden="true" /> Retry queue
          </button>
        ) : null}
      </div>
    );
  }
  return null;
}

function AssignmentStatePill({ state }: { state: ReviewAssignment["state"] }) {
  const className =
    state === "revoked" || state === "expired"
      ? styles.pillMuted
      : state === "submitted"
        ? styles.pillSuccess
        : styles.pillPending;
  return (
    <span className={`${styles.pill} ${className}`}>
      {state === "revoked" || state === "expired" ? (
        <XCircle size={12} aria-hidden="true" />
      ) : state === "submitted" ? (
        <CheckCircle2 size={12} aria-hidden="true" />
      ) : (
        <Clock3 size={12} aria-hidden="true" />
      )}
      {stateLabels[state]}
    </span>
  );
}

function AssignmentSummary({
  assignment,
  detail,
  onRevoke,
  revoking,
}: {
  assignment: ReviewAssignment;
  academyOrigin?: string | null;
  detail?: boolean;
  onRevoke: (assignment: ReviewAssignment) => void;
  revoking: boolean;
}) {
  return (
    <article
      className={`${styles.assignmentCard} ${detail ? styles.assignmentCardDetail : ""}`}
    >
      <div className={styles.assignmentCardHeader}>
        <div>
          <span className={styles.eyebrow}>Assignment</span>
          <h3 title={assignment.id}>{shortId(assignment.id)}</h3>
        </div>
        <AssignmentStatePill state={assignment.state} />
      </div>
      <dl className={styles.assignmentFacts}>
        <div>
          <dt>Run ID</dt>
          <dd title={assignment.run_id}>{shortId(assignment.run_id)}</dd>
        </div>
        <div>
          <dt>Reviewer person</dt>
          <dd title={assignment.reviewer_person_id}>
            <UserRound size={13} aria-hidden="true" />{" "}
            {shortId(assignment.reviewer_person_id)}
          </dd>
        </div>
        <div>
          <dt>Expires</dt>
          <dd>{formatEpoch(assignment.expires_at_epoch)}</dd>
        </div>
        <div>
          <dt>Lenses</dt>
          <dd>{assignment.allowed_lenses.join(" · ")}</dd>
        </div>
      </dl>
      {detail ? (
        <details className={styles.lineage}>
          <summary>Technical details</summary>
          <span>
            <strong>Tenant</strong> <code>{assignment.tenant_id}</code>
          </span>
          <span>
            <strong>Source</strong>{" "}
            <code>{assignment.source.recording_id}</code>
          </span>
          <span>
            <strong>Checkpoint</strong> <code>{assignment.checkpoint.id}</code>{" "}
            · {assignment.checkpoint.stage}
          </span>
        </details>
      ) : null}
      <div className={styles.assignmentActions}>
        <Link
          className="button button-secondary"
          href={`/reviewer/review/${encodeURIComponent(assignment.id)}`}
        >
          Open reviewer workspace
        </Link>
        {assignment.state !== "revoked" && assignment.state !== "expired" ? (
          <button
            className={`button ${styles.buttonDanger}`}
            type="button"
            onClick={() => onRevoke(assignment)}
            disabled={revoking}
          >
            {revoking ? (
              <LoaderCircle size={15} className="spin" aria-hidden="true" />
            ) : (
              <XCircle size={15} aria-hidden="true" />
            )}
            {revoking ? "Revoking…" : "Revoke assignment"}
          </button>
        ) : null}
      </div>
    </article>
  );
}

export function ReviewWorkspace({
  assignmentId,
  academyOrigin,
  assignmentsAvailable = REVIEWER_INVITATIONS_AVAILABLE,
}: {
  assignmentId?: string;
  academyOrigin?: string | null;
  assignmentsAvailable?: boolean;
}) {
  const [queue, setQueue] = useState<ReviewQueueState>({
    status: "loading",
    items: [],
  });
  const [runId, setRunId] = useState("");
  const [inventoryRunId, setInventoryRunId] = useState<string | null>(null);
  const [reviewerPersonId, setReviewerPersonId] = useState("");
  const [allowedLenses, setAllowedLenses] = useState<ReviewMode[]>([
    ...reviewLenses,
  ]);
  const [expiry, setExpiry] = useState(() =>
    localReviewDate(Math.floor(Date.now() / 1000) + 7 * 24 * 60 * 60),
  );
  const [formErrors, setFormErrors] = useState<FormErrors>({});
  const [createMutation, setCreateMutation] = useState<CreateMutation>({
    status: "idle",
  });
  const [revokeMutation, setRevokeMutation] = useState<RevokeMutation>({
    status: "idle",
  });
  const [revokeTarget, setRevokeTarget] = useState<ReviewAssignment | null>(
    null,
  );
  const createIntent = useRef<CreateIntent | null>(null);
  const createKey = useRef<string | null>(null);
  const revokeKeys = useRef(new Map<string, string>());
  const queueRequest = useRef(0);
  const createRequest = useRef(0);
  const revokeRequest = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      queueRequest.current += 1;
      createRequest.current += 1;
      revokeRequest.current += 1;
    };
  }, []);

  const refreshQueue = useCallback(() => {
    const request = ++queueRequest.current;
    const controller = new AbortController();
    void loadReviewAssignments(fetch, controller.signal).then(
      (payload) => {
        if (!mounted.current || request !== queueRequest.current) return;
        setQueue({ status: "ready", items: payload.items });
      },
      (error: unknown) => {
        if (!mounted.current || request !== queueRequest.current) return;
        const parsed = reviewError(error);
        setQueue((current) => ({
          status: "error",
          items: current.items,
          message: parsed.message,
          retryable: parsed.retryable,
        }));
      },
    );
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const cancel = refreshQueue();
    return cancel;
  }, [refreshQueue]);

  function requestQueueRefresh() {
    setQueue((current) => ({ status: "loading", items: current.items }));
    refreshQueue();
  }

  const selectedAssignment = useMemo(
    () =>
      assignmentId
        ? queue.items.find((assignment) => assignment.id === assignmentId)
        : undefined,
    [assignmentId, queue.items],
  );

  const beginCreate = useCallback(
    (intent: CreateIntent, idempotencyKey: string) => {
      const request = ++createRequest.current;
      createIntent.current = intent;
      createKey.current = idempotencyKey;
      setCreateMutation({ status: "submitting" });
      void createReviewAssignment({
        ...intent,
        idempotencyKey,
      }).then(
        (assignment) => {
          if (!mounted.current || request !== createRequest.current) return;
          setCreateMutation({ status: "success", assignment });
          createIntent.current = null;
          createKey.current = null;
          queueRequest.current += 1;
          setQueue((current) => {
            const items = mergeAssignment(current.items, assignment);
            return current.status === "error"
              ? { ...current, items }
              : { status: "ready", items };
          });
        },
        (error: unknown) => {
          if (!mounted.current || request !== createRequest.current) return;
          const parsed = reviewError(error);
          setCreateMutation({
            status: "error",
            message: parsed.message,
            retryable: parsed.retryable,
          });
        },
      );
    },
    [],
  );

  function submitCreate() {
    if (!assignmentsAvailable) return;
    const validated = validateCreateIntent(
      runId,
      reviewerPersonId,
      allowedLenses,
      expiry,
    );
    setFormErrors(validated.errors);
    if (!validated.intent) return;
    let key: string;
    try {
      key = newReviewIdempotencyKey();
    } catch (error) {
      const parsed = reviewError(error);
      setCreateMutation({ status: "error", ...parsed });
      return;
    }
    beginCreate(validated.intent, key);
  }

  function retryCreate() {
    if (!assignmentsAvailable) return;
    if (!createIntent.current || !createKey.current) return;
    beginCreate(createIntent.current, createKey.current);
  }

  function startRevoke(assignment: ReviewAssignment) {
    setRevokeTarget(assignment);
    setRevokeMutation({ status: "idle" });
  }

  function confirmRevoke() {
    if (!revokeTarget) return;
    const assignment = revokeTarget;
    const request = ++revokeRequest.current;
    let key = revokeKeys.current.get(assignment.id);
    try {
      if (!key) {
        key = newReviewIdempotencyKey();
        revokeKeys.current.set(assignment.id, key);
      }
    } catch (error) {
      const parsed = reviewError(error);
      setRevokeMutation({
        status: "error",
        assignmentId: assignment.id,
        ...parsed,
      });
      return;
    }
    setRevokeMutation({ status: "submitting", assignmentId: assignment.id });
    void revokeReviewAssignment({
      assignmentId: assignment.id,
      idempotencyKey: key,
    }).then(
      (revoked) => {
        if (!mounted.current || request !== revokeRequest.current) return;
        revokeKeys.current.delete(assignment.id);
        setRevokeMutation({ status: "success", assignment: revoked });
        setRevokeTarget(null);
        queueRequest.current += 1;
        setQueue((current) => {
          const items = mergeAssignment(current.items, revoked);
          return current.status === "error"
            ? { ...current, items }
            : { status: "ready", items };
        });
      },
      (error: unknown) => {
        if (!mounted.current || request !== revokeRequest.current) return;
        const parsed = reviewError(error);
        setRevokeMutation({
          status: "error",
          assignmentId: assignment.id,
          ...parsed,
        });
      },
    );
  }

  const isCreating = createMutation.status === "submitting";
  const isRevoking = revokeMutation.status === "submitting";

  return (
    <AdminShell
      active="sales-xray"
      surface="operations"
      eyebrow="Sales Xray / Review team"
      title={
        assignmentId
          ? "Review assignment"
          : "Better analysis starts with your team."
      }
      description="Invite reviewers, choose their perspective, and manage access to each conversation."
      footerText="Review assignments · Saved changes confirmed by the service"
    >
      <div className={styles.workspace}>
        {assignmentId ? (
          <div className={styles.breadcrumbRow}>
            <Link className="back-link" href="/sales-xray/review">
              <ArrowLeft size={15} aria-hidden="true" /> Back to assignments
            </Link>
            <span className={styles.routeCode}>
              ASSIGNMENT · {shortId(assignmentId)}
            </span>
          </div>
        ) : null}

        <div className={styles.notice} role="note">
          <div className={styles.noticeIcon} aria-hidden="true">
            <ShieldCheck size={20} />
          </div>
          <div>
            <h2>Review feedback and manage existing access.</h2>
            <p>
              Inspect saved feedback and revoke existing access. Invitations
              open a dedicated reviewer mailbox session; Admin never enters the
              reviewer workspace on someone else&apos;s behalf.
            </p>
          </div>
          <span className={styles.noticeCode}>Private review access</span>
        </div>

        {assignmentId && selectedAssignment ? (
          <section
            className={styles.panel}
            aria-labelledby="assignment-detail-title"
          >
            <SectionHeading
              eyebrow="Selected review"
              id="assignment-detail-title"
              title="Review access"
              body="Check review status and manage this assignment."
            />
            <AssignmentSummary
              assignment={selectedAssignment}
              academyOrigin={academyOrigin}
              detail
              onRevoke={startRevoke}
              revoking={
                isRevoking && revokeTarget?.id === selectedAssignment.id
              }
            />
          </section>
        ) : null}

        {assignmentId ? (
          <AdminReviewDetails assignmentId={assignmentId} />
        ) : null}

        <RecordingsInventory
          onSelectRun={(selectedRunId) => {
            setInventoryRunId(selectedRunId);
            setRunId(selectedRunId);
          }}
        />

        <ReviewInvitationPanel
          key={`${assignmentId ?? "queue"}:${inventoryRunId ?? ""}`}
          initialRunId={inventoryRunId ?? selectedAssignment?.run_id}
          runs={queue.items}
        />
        <div className={styles.layout}>
          <section className={styles.panel} aria-labelledby="queue-title">
            <div className={styles.panelHeader}>
              <div>
                <span className={styles.eyebrow}>Review activity</span>
                <h2 id="queue-title">Your review assignments</h2>
              </div>
              <button
                className="icon-button"
                type="button"
                aria-label="Refresh review assignment queue"
                onClick={requestQueueRefresh}
                disabled={queue.status === "loading"}
              >
                <RefreshCw
                  size={17}
                  className={queue.status === "loading" ? "spin" : undefined}
                  aria-hidden="true"
                />
              </button>
            </div>
            <p className={styles.panelIntro}>
              Track submitted feedback and manage active review access. Showing
              up to 50 recent assignments.
            </p>
            <StatePanel state={queue} onRetry={requestQueueRefresh} />
            {queue.status === "error" && queue.items.length > 0 ? (
              <div className={styles.inlineError} role="alert">
                <CircleAlert size={16} aria-hidden="true" />
                <span>{queue.message}</span>
                {queue.retryable ? (
                  <button
                    className="button button-secondary"
                    type="button"
                    onClick={requestQueueRefresh}
                  >
                    Retry
                  </button>
                ) : null}
              </div>
            ) : null}
            {queue.status !== "loading" && queue.items.length === 0 ? (
              <div className={styles.emptyState} role="status">
                <FileCheck2 size={25} aria-hidden="true" />
                <strong>No review assignments yet</strong>
                <p>
                  Create one after a saved report and verified reviewer
                  membership are available.
                </p>
              </div>
            ) : null}
            {queue.items.length > 0 ? (
              <div className={styles.queueList}>
                {queue.items.map((assignment) => (
                  <div className={styles.queueRow} key={assignment.id}>
                    <Link
                      className={`${styles.queueItem} ${assignment.id === assignmentId ? styles.queueItemActive : ""}`}
                      href={`/sales-xray/review/${encodeURIComponent(assignment.id)}`}
                    >
                      <span className={styles.queueItemMeta}>
                        <span>{shortId(assignment.id)}</span>
                        <AssignmentStatePill state={assignment.state} />
                      </span>
                      <strong>{shortId(assignment.run_id)}</strong>
                      <span>
                        Reviewer {shortId(assignment.reviewer_person_id)}
                      </span>
                    </Link>
                    <button
                      className={styles.rowRevoke}
                      type="button"
                      onClick={() => startRevoke(assignment)}
                      disabled={
                        assignment.state === "revoked" ||
                        assignment.state === "expired" ||
                        isRevoking
                      }
                    >
                      Revoke
                    </button>
                  </div>
                ))}
              </div>
            ) : null}
          </section>

          <details className={styles.panel}>
            <summary className={styles.advancedTitle}>
              Advanced: assign an existing reviewer by ID
            </summary>
            <section aria-labelledby="create-title">
              <SectionHeading
                eyebrow="Existing account"
                id="create-title"
                title="Create a reviewer assignment"
                body={
                  assignmentsAvailable
                    ? "Assign an existing authorized reviewer."
                    : "Assignment creation is unavailable until the reviewer service is ready."
                }
              />
              <form
                className={styles.formStack}
                onSubmit={(event) => {
                  event.preventDefault();
                  submitCreate();
                }}
              >
                <label className={styles.field} htmlFor="review-run-id">
                  <span>
                    Run ID <small>canonical UUID</small>
                  </span>
                  <input
                    id="review-run-id"
                    value={runId}
                    onChange={(event) => setRunId(event.target.value)}
                    placeholder="e.g. 01234567-89ab-4cde-8123-456789abcdef"
                    aria-invalid={Boolean(formErrors.runId)}
                    aria-describedby={
                      formErrors.runId ? "review-run-id-error" : undefined
                    }
                    disabled={isCreating}
                  />
                  {formErrors.runId ? (
                    <span
                      className={styles.fieldError}
                      id="review-run-id-error"
                    >
                      {formErrors.runId}
                    </span>
                  ) : null}
                </label>
                <label className={styles.field} htmlFor="reviewer-person-id">
                  <span>
                    Reviewer person ID{" "}
                    <small>canonical UUID · server checks membership</small>
                  </span>
                  <input
                    id="reviewer-person-id"
                    value={reviewerPersonId}
                    onChange={(event) =>
                      setReviewerPersonId(event.target.value)
                    }
                    placeholder="e.g. 01234567-89ab-4cde-8123-456789abcdef"
                    aria-invalid={Boolean(formErrors.reviewerPersonId)}
                    aria-describedby={
                      formErrors.reviewerPersonId
                        ? "reviewer-person-id-error"
                        : undefined
                    }
                    disabled={isCreating}
                  />
                  {formErrors.reviewerPersonId ? (
                    <span
                      className={styles.fieldError}
                      id="reviewer-person-id-error"
                    >
                      {formErrors.reviewerPersonId}
                    </span>
                  ) : null}
                </label>
                <fieldset className={styles.lensFieldset}>
                  <legend>Allowed review lenses</legend>
                  <p>Choose the review lanes for this handoff.</p>
                  <div className={styles.lensGrid}>
                    {reviewLenses.map((lens) => (
                      <label className={styles.lensOption} key={lens}>
                        <input
                          type="checkbox"
                          checked={allowedLenses.includes(lens)}
                          onChange={(event) => {
                            setAllowedLenses((current) =>
                              event.target.checked
                                ? [...current, lens]
                                : current.filter((item) => item !== lens),
                            );
                          }}
                          disabled={isCreating}
                        />
                        <span>
                          <strong>{lensLabels[lens].label}</strong>
                          <small>{lensLabels[lens].detail}</small>
                        </span>
                      </label>
                    ))}
                  </div>
                  {formErrors.allowedLenses ? (
                    <span className={styles.fieldError}>
                      {formErrors.allowedLenses}
                    </span>
                  ) : null}
                </fieldset>
                <label className={styles.field} htmlFor="review-expiry">
                  <span>
                    Expiry <small>Your local time · within 30 days</small>
                  </span>
                  <input
                    id="review-expiry"
                    type="datetime-local"
                    value={expiry}
                    onChange={(event) => setExpiry(event.target.value)}
                    aria-invalid={Boolean(formErrors.expiresAtEpoch)}
                    aria-describedby={
                      formErrors.expiresAtEpoch
                        ? "review-expiry-error"
                        : undefined
                    }
                    disabled={isCreating}
                  />
                  {formErrors.expiresAtEpoch ? (
                    <span
                      className={styles.fieldError}
                      id="review-expiry-error"
                    >
                      {formErrors.expiresAtEpoch}
                    </span>
                  ) : null}
                </label>
                <button
                  className="button button-primary"
                  type="submit"
                  disabled={isCreating || !assignmentsAvailable}
                >
                  {isCreating ? (
                    <LoaderCircle
                      size={15}
                      className="spin"
                      aria-hidden="true"
                    />
                  ) : (
                    <Plus size={15} aria-hidden="true" />
                  )}
                  {!assignmentsAvailable
                    ? "Assignment creation unavailable"
                    : isCreating
                      ? "Creating assignment…"
                      : "Create assignment"}
                </button>
              </form>
              {createMutation.status === "success" ? (
                <div
                  className={styles.successNotice}
                  role="status"
                  aria-live="polite"
                >
                  <CheckCircle2 size={18} aria-hidden="true" />
                  <div>
                    <strong>Assignment created and confirmed.</strong>
                    <span>
                      {shortId(createMutation.assignment.id)} is now in the
                      server response.
                    </span>
                  </div>
                </div>
              ) : null}
              {createMutation.status === "error" ? (
                <div className={styles.mutationError} role="alert">
                  <CircleAlert size={18} aria-hidden="true" />
                  <div>
                    <strong>Assignment was not confirmed.</strong>
                    <span>{createMutation.message}</span>
                  </div>
                  {createMutation.retryable ? (
                    <button
                      className="button button-secondary"
                      type="button"
                      onClick={retryCreate}
                    >
                      Retry same request
                    </button>
                  ) : null}
                </div>
              ) : null}
            </section>
          </details>
        </div>

        {revokeTarget ? (
          <section
            className={styles.confirmPanel}
            aria-labelledby="revoke-title"
          >
            <div>
              <span className={styles.eyebrow}>Destructive admin command</span>
              <h2 id="revoke-title">
                Revoke assignment {shortId(revokeTarget.id)}?
              </h2>
              <p>
                The server will append a revocation. The reviewer link will stop
                working after the authorized response.
              </p>
            </div>
            <div className={styles.confirmActions}>
              <button
                className="button button-secondary"
                type="button"
                onClick={() => setRevokeTarget(null)}
                disabled={isRevoking}
              >
                Keep assignment
              </button>
              <button
                className={`button ${styles.buttonDanger}`}
                type="button"
                onClick={confirmRevoke}
                disabled={isRevoking}
              >
                {isRevoking ? (
                  <LoaderCircle size={15} className="spin" aria-hidden="true" />
                ) : (
                  <XCircle size={15} aria-hidden="true" />
                )}
                {isRevoking ? "Revoking…" : "Confirm revoke"}
              </button>
            </div>
            {revokeMutation.status === "error" &&
            revokeMutation.assignmentId === revokeTarget.id ? (
              <div className={styles.mutationError} role="alert">
                <CircleAlert size={17} aria-hidden="true" />
                <span>{revokeMutation.message}</span>
                {revokeMutation.retryable ? (
                  <button
                    className="button button-secondary"
                    type="button"
                    onClick={confirmRevoke}
                  >
                    Retry same request
                  </button>
                ) : null}
              </div>
            ) : null}
          </section>
        ) : null}
        {revokeMutation.status === "success" ? (
          <div
            className={styles.successNotice}
            role="status"
            aria-live="polite"
          >
            <CheckCircle2 size={18} aria-hidden="true" />
            <div>
              <strong>Revocation confirmed by the server.</strong>
              <span>
                {shortId(revokeMutation.assignment.id)} now has state “
                {stateLabels[revokeMutation.assignment.state]}”.
              </span>
            </div>
          </div>
        ) : null}
      </div>
    </AdminShell>
  );
}
