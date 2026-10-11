"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  CheckCircle2,
  CircleAlert,
  FileCheck2,
  Plus,
  RefreshCw,
  XCircle,
} from "lucide-react";

import { AdminShell } from "../../components/admin-shell";
import {
  Badge,
  Button,
  Empty,
  Field,
  List,
  Panel,
  Row,
  Skeleton,
  kitStyles,
  type Tone,
} from "../../ui/kit";
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
import styles from "./reviewers.module.css";
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

const stateTone: Record<ReviewAssignment["state"], Tone> = {
  assigned: "accent",
  in_progress: "warn",
  submitted: "good",
  revoked: "neutral",
  expired: "neutral",
};

const closed = (state: ReviewAssignment["state"]) =>
  state === "revoked" || state === "expired";

function AssignmentState({ state }: { state: ReviewAssignment["state"] }) {
  return <Badge tone={stateTone[state]}>{stateLabels[state]}</Badge>;
}

/** One assignment, in full, with its lineage and actions. */
function AssignmentDetail({
  assignment,
  onRevoke,
  revoking,
}: {
  assignment: ReviewAssignment;
  onRevoke: (assignment: ReviewAssignment) => void;
  revoking: boolean;
}) {
  return (
    <Panel
      title="Review access"
      sub={shortId(assignment.id)}
      tools={<AssignmentState state={assignment.state} />}
    >
      <div className={styles.body}>
        <dl className={styles.facts}>
          <div>
            <dt>Analysis (run)</dt>
            <dd title={assignment.run_id}>{shortId(assignment.run_id)}</dd>
          </div>
          <div>
            <dt>Reviewer person</dt>
            <dd title={assignment.reviewer_person_id}>
              {shortId(assignment.reviewer_person_id)}
            </dd>
          </div>
          <div>
            <dt>Expires</dt>
            <dd>{formatEpoch(assignment.expires_at_epoch)}</dd>
          </div>
          <div>
            <dt>Perspectives</dt>
            <dd>
              {assignment.allowed_lenses
                .map((lens) => lensLabels[lens].label)
                .join(" · ")}
            </dd>
          </div>
        </dl>
        <details className={styles.tech}>
          <summary>Technical details</summary>
          <span>
            Tenant <code>{assignment.tenant_id}</code>
          </span>
          <span>
            Source <code>{assignment.source.recording_id}</code>
          </span>
          <span>
            Checkpoint <code>{assignment.checkpoint.id}</code> ·{" "}
            {assignment.checkpoint.stage}
          </span>
        </details>
        <span className={styles.actions}>
          <Link
            className={kitStyles.button}
            data-variant="secondary"
            href={`/reviewer/review/${encodeURIComponent(assignment.id)}`}
          >
            Open reviewer workspace
          </Link>
          {!closed(assignment.state) ? (
            <Button
              className={styles.danger}
              onClick={() => onRevoke(assignment)}
              disabled={revoking}
            >
              <XCircle size={14} aria-hidden="true" />
              {revoking ? "Revoking…" : "Revoke assignment"}
            </Button>
          ) : null}
        </span>
      </div>
    </Panel>
  );
}

export function ReviewWorkspace({
  assignmentId,
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
      title={assignmentId ? "Review assignment" : "Reviewers"}
      description="Invite outside reviewers to one saved analysis, choose what they review, and manage their access. Invitations open the reviewer's own mailbox sign-in; Admin never enters the reviewer workspace on their behalf."
    >
      <div className={styles.workspace}>
        {assignmentId ? (
          <Link className={styles.back} href="/reviewers">
            <ArrowLeft size={14} aria-hidden="true" /> Back to assignments
          </Link>
        ) : null}

        {assignmentId && selectedAssignment ? (
          <AssignmentDetail
            assignment={selectedAssignment}
            onRevoke={startRevoke}
            revoking={isRevoking && revokeTarget?.id === selectedAssignment.id}
          />
        ) : null}

        {assignmentId ? (
          <AdminReviewDetails assignmentId={assignmentId} />
        ) : null}

        {revokeTarget ? (
          <section className={styles.confirm} aria-labelledby="revoke-title">
            <h2 id="revoke-title">
              Revoke assignment {shortId(revokeTarget.id)}?
            </h2>
            <p>
              The server records a revocation; the reviewer&rsquo;s link stops
              working once it confirms. Their submitted feedback stays.
            </p>
            <span className={styles.actions}>
              <Button
                onClick={() => setRevokeTarget(null)}
                disabled={isRevoking}
              >
                Keep assignment
              </Button>
              <Button
                variant="primary"
                onClick={confirmRevoke}
                disabled={isRevoking}
              >
                <XCircle size={14} aria-hidden="true" />
                {isRevoking ? "Revoking…" : "Confirm revoke"}
              </Button>
            </span>
            {revokeMutation.status === "error" &&
            revokeMutation.assignmentId === revokeTarget.id ? (
              <p className={styles.note} data-tone="warn" role="alert">
                <CircleAlert size={14} aria-hidden="true" />
                <span>{revokeMutation.message}</span>
                {revokeMutation.retryable ? (
                  <Button onClick={confirmRevoke}>Retry same request</Button>
                ) : null}
              </p>
            ) : null}
          </section>
        ) : null}
        {revokeMutation.status === "success" ? (
          <p
            className={styles.note}
            data-tone="good"
            role="status"
            aria-live="polite"
          >
            <CheckCircle2 size={14} aria-hidden="true" />
            <span>
              <strong>Revocation confirmed by the server.</strong>{" "}
              {shortId(revokeMutation.assignment.id)} is now &ldquo;
              {stateLabels[revokeMutation.assignment.state]}&rdquo;.
            </span>
          </p>
        ) : null}

        <div className={styles.columns}>
          <Panel
            title="Your review assignments"
            sub="Up to 50 most recent"
            tools={
              <Button
                variant="icon"
                aria-label="Refresh review assignment queue"
                onClick={requestQueueRefresh}
                disabled={queue.status === "loading"}
              >
                <RefreshCw
                  size={14}
                  className={
                    queue.status === "loading" ? styles.spin : undefined
                  }
                  aria-hidden="true"
                />
              </Button>
            }
          >
            {queue.status === "loading" && queue.items.length === 0 ? (
              <div className={styles.skeleton} role="status" aria-live="polite">
                <span className={kitStyles.srOnly}>
                  Checking the review assignment queue
                </span>
                {[0, 1, 2].map((row) => (
                  <Skeleton key={row} height={36} />
                ))}
              </div>
            ) : null}
            {queue.status === "error" ? (
              <div className={styles.body}>
                <p className={styles.note} role="alert">
                  <CircleAlert size={14} aria-hidden="true" />
                  <span>
                    {queue.message}
                    {queue.items.length === 0
                      ? " Retry before creating a new handoff."
                      : ""}
                  </span>
                  {queue.retryable ? (
                    <Button onClick={requestQueueRefresh}>
                      <RefreshCw size={14} aria-hidden="true" /> Retry
                    </Button>
                  ) : null}
                </p>
              </div>
            ) : null}
            {queue.status === "ready" && queue.items.length === 0 ? (
              <Empty
                icon={FileCheck2}
                title="No review assignments yet"
                text="Invite a reviewer to a saved analysis to start one."
              />
            ) : null}
            {queue.items.length > 0 ? (
              <List label="Review assignments">
                {queue.items.map((assignment) => (
                  <Row
                    key={assignment.id}
                    href={`/sales-xray/review/${encodeURIComponent(assignment.id)}`}
                    title={
                      <span
                        aria-current={
                          assignment.id === assignmentId ? "page" : undefined
                        }
                        title={assignment.run_id}
                      >
                        Analysis {shortId(assignment.run_id)}
                      </span>
                    }
                    meta={[
                      `Reviewer ${shortId(assignment.reviewer_person_id)}`,
                      assignment.allowed_lenses
                        .map((lens) => lensLabels[lens].label)
                        .join(", "),
                      closed(assignment.state)
                        ? null
                        : `Until ${formatEpoch(assignment.expires_at_epoch)}`,
                    ]}
                    end={
                      <>
                        <AssignmentState state={assignment.state} />
                        <Button
                          variant="ghost"
                          onClick={() => startRevoke(assignment)}
                          disabled={closed(assignment.state) || isRevoking}
                        >
                          Revoke
                        </Button>
                      </>
                    }
                  />
                ))}
              </List>
            ) : null}
          </Panel>

          <div className={styles.side} id="invite">
            <ReviewInvitationPanel
              key={`${assignmentId ?? "queue"}:${inventoryRunId ?? ""}`}
              initialRunId={inventoryRunId ?? selectedAssignment?.run_id}
              runs={queue.items}
            />

            <Panel title="Assign an existing reviewer">
              <details className={styles.advanced}>
                <summary>By person ID (advanced)</summary>
                <form
                  className={styles.body}
                  data-form="assign"
                  aria-labelledby="create-title"
                  onSubmit={(event) => {
                    event.preventDefault();
                    submitCreate();
                  }}
                >
                  <p id="create-title" className={kitStyles.muted}>
                    {assignmentsAvailable
                      ? "Assign someone who already has reviewer access. The server checks their membership."
                      : "Assignment creation is unavailable until the reviewer service is ready."}
                  </p>
                  <Field
                    label="Run ID"
                    hint="Canonical UUID of a saved analysis"
                    error={formErrors.runId}
                  >
                    <input
                      id="review-run-id"
                      value={runId}
                      onChange={(event) => setRunId(event.target.value)}
                      placeholder="01234567-89ab-4cde-8123-456789abcdef"
                      aria-invalid={Boolean(formErrors.runId)}
                      disabled={isCreating}
                    />
                  </Field>
                  <Field
                    label="Reviewer person ID"
                    hint="Canonical UUID"
                    error={formErrors.reviewerPersonId}
                  >
                    <input
                      id="reviewer-person-id"
                      value={reviewerPersonId}
                      onChange={(event) =>
                        setReviewerPersonId(event.target.value)
                      }
                      placeholder="01234567-89ab-4cde-8123-456789abcdef"
                      aria-invalid={Boolean(formErrors.reviewerPersonId)}
                      disabled={isCreating}
                    />
                  </Field>
                  <fieldset className={styles.lenses}>
                    <legend>Perspectives</legend>
                    {reviewLenses.map((lens) => (
                      <label key={lens} title={lensLabels[lens].detail}>
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
                        {lensLabels[lens].label}
                      </label>
                    ))}
                  </fieldset>
                  {formErrors.allowedLenses ? (
                    <small className={kitStyles.fieldError} role="alert">
                      {formErrors.allowedLenses}
                    </small>
                  ) : null}
                  <Field
                    label="Expiry"
                    hint="Your local time · within 30 days"
                    error={formErrors.expiresAtEpoch}
                  >
                    <input
                      id="review-expiry"
                      type="datetime-local"
                      value={expiry}
                      onChange={(event) => setExpiry(event.target.value)}
                      aria-invalid={Boolean(formErrors.expiresAtEpoch)}
                      disabled={isCreating}
                    />
                  </Field>
                  <span className={styles.actions}>
                    <Button
                      type="submit"
                      variant="primary"
                      disabled={isCreating || !assignmentsAvailable}
                    >
                      <Plus size={14} aria-hidden="true" />
                      {!assignmentsAvailable
                        ? "Assignment creation unavailable"
                        : isCreating
                          ? "Creating assignment…"
                          : "Create assignment"}
                    </Button>
                  </span>
                  {createMutation.status === "success" ? (
                    <p
                      className={styles.note}
                      data-tone="good"
                      role="status"
                      aria-live="polite"
                    >
                      <CheckCircle2 size={14} aria-hidden="true" />
                      <span>
                        <strong>Assignment created and confirmed.</strong>{" "}
                        {shortId(createMutation.assignment.id)} is in the list.
                      </span>
                    </p>
                  ) : null}
                  {createMutation.status === "error" ? (
                    <p className={styles.note} data-tone="warn" role="alert">
                      <CircleAlert size={14} aria-hidden="true" />
                      <span>
                        <strong>Assignment was not confirmed.</strong>{" "}
                        {createMutation.message}
                      </span>
                      {createMutation.retryable ? (
                        <Button onClick={retryCreate}>
                          Retry same request
                        </Button>
                      ) : null}
                    </p>
                  ) : null}
                </form>
              </details>
            </Panel>
          </div>
        </div>

        <RecordingsInventory
          onSelectRun={(selectedRunId) => {
            setInventoryRunId(selectedRunId);
            setRunId(selectedRunId);
            document
              .getElementById("invite")
              ?.scrollIntoView?.({ block: "start", behavior: "smooth" });
          }}
        />
      </div>
    </AdminShell>
  );
}
