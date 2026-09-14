import { useRef, useState } from "react";
import { CheckCircle2, CircleAlert, Mail, XCircle } from "lucide-react";

import {
  newReviewIdempotencyKey,
  reviewLenses,
  type ReviewMode,
  type ReviewAssignment,
} from "./review-api";
import { localReviewDate, reviewDateEpoch } from "./review-date";
import {
  type ReviewInvitation,
  createReviewInvitation as sendReviewInvitation,
  revokeReviewInvitation as revokeInvitation,
} from "./review-invitation-api";
import styles from "./review-invitation-panel.module.css";

const lensLabels: Record<ReviewMode, string> = {
  sales: "Sales expert",
  technical: "Developer",
  ux: "Experience reviewer",
};

// Invitations use the dedicated reviewer mailbox/session flow. The server
// still derives the reviewer assignment, source and tenant from the selected
// run and invitation; this flag only enables the Admin authoring control.
export const REVIEWER_INVITATIONS_AVAILABLE = true;

type Mutation =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "success"; invitation: ReviewInvitation }
  | { status: "error"; message: string; retryable: boolean };

function stateLabel(state: ReviewInvitation["state"]): string {
  return state === "pending"
    ? "Queued"
    : state[0]!.toUpperCase() + state.slice(1);
}

function validUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
    value,
  );
}

export function ReviewInvitationPanel({
  initialRunId = "",
  runs = [],
  invitationsAvailable = REVIEWER_INVITATIONS_AVAILABLE,
}: {
  initialRunId?: string;
  runs?: readonly ReviewAssignment[];
  invitationsAvailable?: boolean;
}) {
  const [runInput, setRunId] = useState<string | null>(null);
  const runId = runInput ?? initialRunId;
  const [email, setEmail] = useState("");
  const [lenses, setLenses] = useState<ReviewMode[]>([...reviewLenses]);
  const [expiry, setExpiry] = useState(() =>
    localReviewDate(Math.floor(Date.now() / 1000) + 7 * 24 * 60 * 60),
  );
  const [knownId, setKnownId] = useState("");
  const [items, setItems] = useState<ReviewInvitation[]>([]);
  const [mutation, setMutation] = useState<Mutation>({ status: "idle" });
  const [revokeMutation, setRevokeMutation] = useState<Mutation>({
    status: "idle",
  });
  const createAttempt = useRef<{ fingerprint: string; key: string } | null>(
    null,
  );
  const creating = useRef(false);
  const revokeKeys = useRef(new Map<string, string>());

  function validate(): string | null {
    if (!validUuid(runId.trim()))
      return "Select a saved analysis or enter its run ID.";
    if (!email.trim() || !email.includes("@") || email.trim().length > 320)
      return "Enter the invited email address.";
    if (lenses.length === 0) return "Choose at least one review lens.";
    const timestamp = reviewDateEpoch(expiry);
    const nowEpoch = Math.floor(Date.now() / 1000);
    if (
      !Number.isInteger(timestamp) ||
      timestamp <= nowEpoch ||
      timestamp > nowEpoch + 30 * 86400
    )
      return "Choose an expiry in the future, within 30 days.";
    return null;
  }

  async function submit() {
    if (!invitationsAvailable) return;
    if (creating.current) return;
    const error = validate();
    if (error) {
      setMutation({ status: "error", message: error, retryable: false });
      return;
    }
    const intent = {
      runId: runId.trim(),
      invitedEmail: email.trim(),
      allowedLenses: lenses,
      expiresAtEpoch: reviewDateEpoch(expiry),
    };
    const fingerprint = JSON.stringify(intent);
    if (createAttempt.current?.fingerprint !== fingerprint)
      createAttempt.current = { fingerprint, key: newReviewIdempotencyKey() };
    const key = createAttempt.current.key;
    creating.current = true;
    setMutation({ status: "submitting" });
    try {
      const invitation = await sendReviewInvitation({
        ...intent,
        idempotencyKey: key,
      });
      createAttempt.current = null;
      setItems((current) => [
        invitation,
        ...current.filter((item) => item.id !== invitation.id),
      ]);
      setMutation({ status: "success", invitation });
    } catch (reason: unknown) {
      const retryable = Boolean(
        reason &&
          typeof reason === "object" &&
          "retryable" in reason &&
          (reason as { retryable?: boolean }).retryable,
      );
      setMutation({
        status: "error",
        message:
          reason instanceof Error && reason.name === "ZodError"
            ? "Check the invited email address and invitation details."
            : reason instanceof Error
              ? reason.message
              : "The invitation was not queued.",
        retryable,
      });
    } finally {
      creating.current = false;
    }
  }

  function revoke(invitationId: string) {
    const key =
      revokeKeys.current.get(invitationId) ?? newReviewIdempotencyKey();
    revokeKeys.current.set(invitationId, key);
    setRevokeMutation({ status: "submitting" });
    void revokeInvitation({ invitationId, idempotencyKey: key }).then(
      (invitation) => {
        setItems((current) =>
          current.map((item) =>
            item.id === invitation.id ? invitation : item,
          ),
        );
        setKnownId("");
        setRevokeMutation({ status: "success", invitation });
      },
      (reason: unknown) => {
        const retryable = Boolean(
          reason &&
            typeof reason === "object" &&
            "retryable" in reason &&
            (reason as { retryable?: boolean }).retryable,
        );
        setRevokeMutation({
          status: "error",
          message:
            reason instanceof Error
              ? reason.message
              : "The invitation could not be revoked.",
          retryable,
        });
      },
    );
  }

  const busy = mutation.status === "submitting";
  const createDisabled = busy || !invitationsAvailable;
  const revoking = revokeMutation.status === "submitting";
  return (
    <section className={styles.panel} aria-labelledby="review-invitation-title">
      <div className={styles.heading}>
        <span className={styles.eyebrow}>Grow your review team</span>
        <h2 id="review-invitation-title">Invite a reviewer</h2>
        <p>
          Choose a saved analysis, add their email, and select what you would
          like them to review.
        </p>
      </div>
      <div className={styles.form}>
        <label>
          <span>Analysis to review</span>
          <input
            id="invitation-run-id"
            list="review-known-runs"
            value={runId}
            onChange={(event) => setRunId(event.target.value)}
            disabled={createDisabled}
          />
          <datalist id="review-known-runs">
            {[...new Map(runs.map((run) => [run.run_id, run])).values()].map(
              (run) => (
                <option key={run.run_id} value={run.run_id}>
                  Saved analysis {run.run_id.slice(0, 8)} · revision{" "}
                  {run.run_generation}
                </option>
              ),
            )}
          </datalist>
          <small>
            Choose a recent run or paste the run ID from a saved analysis.
          </small>
        </label>
        <label>
          <span>Invited email</span>
          <input
            id="invitation-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={createDisabled}
          />
        </label>
        <fieldset>
          <legend>Review perspectives</legend>
          <div className={styles.lenses}>
            {reviewLenses.map((lens) => (
              <label key={lens}>
                <input
                  type="checkbox"
                  checked={lenses.includes(lens)}
                  onChange={(event) =>
                    setLenses((current) =>
                      event.target.checked
                        ? [...current, lens]
                        : current.filter((item) => item !== lens),
                    )
                  }
                  disabled={createDisabled}
                />
                <span>{lensLabels[lens]}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <label>
          <span>
            Access expires <small>Your local time · within 30 days</small>
          </span>
          <input
            type="datetime-local"
            id="invitation-expiry"
            value={expiry}
            onChange={(event) => setExpiry(event.target.value)}
            disabled={createDisabled}
          />
        </label>
        <button
          className="button button-primary"
          type="button"
          onClick={submit}
          disabled={createDisabled}
        >
          <Mail size={15} aria-hidden="true" />
          {!invitationsAvailable
            ? "Reviewer access unavailable"
            : busy
              ? "Sending invitation…"
              : "Send invitation"}
        </button>
      </div>
      {mutation.status === "success" ? (
        <div className={styles.success} role="status">
          <CheckCircle2 size={17} aria-hidden="true" />
          <span>
            <strong>Invitation queued for delivery.</strong> The review link
            will be emailed to{" "}
            <strong>{mutation.invitation.invited_email}</strong>.
          </span>
        </div>
      ) : null}
      {mutation.status === "error" ? (
        <div className={styles.error} role="alert">
          <CircleAlert size={17} aria-hidden="true" />
          <span>{mutation.message}</span>
          {mutation.retryable ? (
            <button type="button" onClick={submit}>
              Retry same request
            </button>
          ) : null}
        </div>
      ) : null}
      <details className={styles.known}>
        <summary>Revoke an earlier invitation by ID</summary>
        <label>
          <span>
            Revoke a known invitation{" "}
            <small>paste the server invitation ID</small>
          </span>
          <input
            value={knownId}
            onChange={(event) => setKnownId(event.target.value)}
            disabled={revoking}
          />
        </label>
        <button
          className="button button-secondary"
          type="button"
          onClick={() => revoke(knownId.trim())}
          disabled={revoking || !validUuid(knownId.trim())}
        >
          <XCircle size={15} aria-hidden="true" />
          {revoking ? "Revoking…" : "Revoke known invitation"}
        </button>
      </details>
      {revokeMutation.status === "error" ? (
        <p className={styles.errorText} role="alert">
          {revokeMutation.message}
        </p>
      ) : null}
      {revokeMutation.status === "success" ? (
        <p className={styles.success} role="status">
          Invitation revoked. Its link can no longer grant review access.
        </p>
      ) : null}
      {items.length > 0 ? (
        <div className={styles.receipts} aria-label="Invitation receipts">
          <h3>Invitations from this visit</h3>
          {items.map((item) => (
            <article key={item.id}>
              <div>
                <strong>{item.invited_email}</strong>
                <span>
                  {stateLabel(item.state)} ·{" "}
                  {item.allowed_lenses
                    .map((lens) => lensLabels[lens])
                    .join(", ")}
                </span>
              </div>
              <details>
                <summary>Invitation details</summary>
                <code>{item.id}</code>
              </details>
              {item.state === "pending" ? (
                <button
                  type="button"
                  onClick={() => revoke(item.id)}
                  disabled={revoking}
                >
                  Revoke
                </button>
              ) : null}
            </article>
          ))}
        </div>
      ) : (
        <p className={styles.empty}>
          Invitations you send during this visit will appear here.
        </p>
      )}
    </section>
  );
}
