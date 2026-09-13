import { useRef, useState } from "react";
import { CheckCircle2, CircleAlert, Mail, XCircle } from "lucide-react";
import { ZodError } from "zod";

import {
  newReviewIdempotencyKey,
  reviewLenses,
  type ReviewMode,
} from "./review-api";
import {
  type ReviewInvitation,
  createReviewInvitation as sendReviewInvitation,
  revokeReviewInvitation as revokeInvitation,
} from "./review-invitation-api";
import styles from "./review-invitation-panel.module.css";

const lensLabels: Record<ReviewMode, string> = {
  sales: "Sales",
  technical: "Technical",
  ux: "UX",
};

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

export function ReviewInvitationPanel() {
  const [runId, setRunId] = useState("");
  const [email, setEmail] = useState("");
  const [lenses, setLenses] = useState<ReviewMode[]>([...reviewLenses]);
  const [nowEpoch] = useState(() => Math.floor(Date.now() / 1000));
  const [expiry, setExpiry] = useState(String(nowEpoch + 7 * 24 * 60 * 60));
  const [knownId, setKnownId] = useState("");
  const [items, setItems] = useState<ReviewInvitation[]>([]);
  const [mutation, setMutation] = useState<Mutation>({ status: "idle" });
  const [revokeMutation, setRevokeMutation] = useState<Mutation>({
    status: "idle",
  });
  const createKey = useRef<{ fingerprint: string; key: string } | null>(null);
  const createPending = useRef(false);
  const revokePending = useRef(false);
  const revokeKeys = useRef(new Map<string, string>());

  function validate(): string | null {
    if (!validUuid(runId.trim())) return "Enter the exact saved run UUID.";
    if (!email.trim() || !email.includes("@") || email.trim().length > 320)
      return "Enter the invited email address.";
    if (lenses.length === 0) return "Choose at least one review lens.";
    const timestamp = Number(expiry.trim());
    if (
      !Number.isInteger(timestamp) ||
      timestamp <= Math.floor(Date.now() / 1000)
    )
      return "Expiry must be a future UTC epoch second.";
    return null;
  }

  async function submit() {
    if (createPending.current) return;
    const error = validate();
    if (error) {
      setMutation({ status: "error", message: error, retryable: false });
      return;
    }
    const intent = {
      runId: runId.trim(),
      invitedEmail: email.trim(),
      allowedLenses: [...lenses].sort(),
      expiresAtEpoch: Number(expiry.trim()),
    };
    const fingerprint = JSON.stringify(intent);
    const key =
      createKey.current?.fingerprint === fingerprint
        ? createKey.current.key
        : newReviewIdempotencyKey();
    createKey.current = { fingerprint, key };
    createPending.current = true;
    setMutation({ status: "submitting" });
    try {
      const invitation = await sendReviewInvitation({
        ...intent,
        idempotencyKey: key,
      });
      createKey.current = null;
      setItems((current) => [
        invitation,
        ...current.filter((item) => item.id !== invitation.id),
      ]);
      setMutation({ status: "success", invitation });
    } catch (reason: unknown) {
      const retryable = Boolean(
        reason instanceof TypeError ||
          (reason &&
            typeof reason === "object" &&
            "retryable" in reason &&
            (reason as { retryable?: boolean }).retryable),
      );
      setMutation({
        status: "error",
        message:
          reason instanceof ZodError
            ? "Check the run ID, email address, lenses and expiry."
            : reason instanceof Error
              ? reason.message
              : "The invitation was not queued.",
        retryable,
      });
    } finally {
      createPending.current = false;
    }
  }

  async function revoke(invitationId: string) {
    if (revokePending.current) return;
    revokePending.current = true;
    const key =
      revokeKeys.current.get(invitationId) ?? newReviewIdempotencyKey();
    revokeKeys.current.set(invitationId, key);
    setRevokeMutation({ status: "submitting" });
    try {
      const invitation = await revokeInvitation({
        invitationId,
        idempotencyKey: key,
      });
      setItems((current) =>
        current.map((item) => (item.id === invitation.id ? invitation : item)),
      );
      setKnownId("");
      setRevokeMutation({ status: "success", invitation });
    } catch (reason: unknown) {
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
    } finally {
      revokePending.current = false;
    }
  }

  const busy = mutation.status === "submitting";
  const revoking = revokeMutation.status === "submitting";
  return (
    <section className={styles.panel} aria-labelledby="review-invitation-title">
      <div className={styles.heading}>
        <span className={styles.eyebrow}>Email handoff</span>
        <h2 id="review-invitation-title">Invite a verified reviewer</h2>
        <p>
          Invite someone to review a saved call. They must sign in with the
          email address you enter here.
        </p>
      </div>
      <div className={styles.form}>
        <label>
          <span>
            Exact run ID <small>canonical UUID</small>
          </span>
          <input
            value={runId}
            onChange={(event) => setRunId(event.target.value)}
            disabled={busy}
          />
        </label>
        <label>
          <span>Invited email</span>
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={busy}
          />
        </label>
        <fieldset>
          <legend>Allowed review lenses</legend>
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
                  disabled={busy}
                />
                <span>{lensLabels[lens]}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <label>
          <span>
            Expiry <small>UTC epoch seconds · max 30 days server-side</small>
          </span>
          <input
            type="number"
            min={nowEpoch + 1}
            value={expiry}
            onChange={(event) => setExpiry(event.target.value)}
            disabled={busy}
          />
        </label>
        <button
          className="button button-primary"
          type="button"
          onClick={submit}
          disabled={busy}
        >
          <Mail size={15} aria-hidden="true" />
          {busy ? "Queueing invitation…" : "Queue invitation"}
        </button>
      </div>
      {mutation.status === "success" ? (
        <div className={styles.success} role="status">
          <CheckCircle2 size={17} aria-hidden="true" />
          <span>
            <strong>Invitation queued for email delivery.</strong>{" "}
            <code>{mutation.invitation.invited_email}</code>
          </span>
        </div>
      ) : null}
      {mutation.status === "error" ? (
        <div className={styles.error} role="alert">
          <CircleAlert size={17} aria-hidden="true" />
          <span>{mutation.message}</span>
          {mutation.retryable ? (
            <button type="button" onClick={submit}>
              Retry invitation
            </button>
          ) : null}
        </div>
      ) : null}
      <div className={styles.known}>
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
      </div>
      {revokeMutation.status === "error" ? (
        <p className={styles.errorText} role="alert">
          {revokeMutation.message}
        </p>
      ) : null}
      {revokeMutation.status === "success" ? (
        <p className={styles.success} role="status">
          Invitation revoked. <code>{revokeMutation.invitation.id}</code>
        </p>
      ) : null}
      {items.length > 0 ? (
        <div className={styles.receipts} aria-label="Invitation receipts">
          <h3>Invitations created during this visit</h3>
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
              <code title={item.id}>{item.id}</code>
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
          No invitations created during this visit. To revoke an earlier
          invitation, enter its invitation ID above.
        </p>
      )}
    </section>
  );
}
