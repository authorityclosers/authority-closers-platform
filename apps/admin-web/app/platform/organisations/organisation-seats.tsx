"use client";

/**
 * One organisation's seats in Admin (owner, 30 Oct 2026: "a proper seats system";
 * founding clients get seats without paying). Shows the paid period's seats and plan,
 * the complimentary grants and who holds the seats. Only the owner gives, changes or
 * ends free seats, after a confirm step that shows the seats before and after; each
 * is an append-only grant row and an audit event in the organisation's own trail
 * (POST /v1/platform/organisations/{id}/seat-grants). No payment, no billing row.
 */
import { Gift, Lock } from "lucide-react";
import { useEffect, useState } from "react";
import {
  grantOrganisationSeats,
  loadOrganisationSeats,
  type OrganisationSeats,
  type SeatGrant,
} from "@ac/operations-web/organisations";
import { Badge, Button, Field, Panel, Table, kitStyles } from "../../ui/kit";
import { istStamp } from "../../lib/time";
import { organisationError } from "./organisation-action";
import styles from "./organisation-seats.module.css";

const DAY = new Intl.DateTimeFormat("en-IN", {
  dateStyle: "medium",
  timeZone: "UTC",
});
/** "31 Jan 2027" for a plain YYYY-MM-DD day. */
export const dayText = (value: string | null) =>
  value ? DAY.format(new Date(`${value}T00:00:00Z`)) : "—";
const seats = (value: number) => `${value} ${value === 1 ? "seat" : "seats"}`;
const KIND: Record<SeatGrant["kind"], string> = {
  grant: "Given",
  change: "Changed",
  end: "Ended",
};

/** Three months from the first allowed day, as a starting suggestion. */
function suggestedUntil(earliest: string) {
  const date = new Date(`${earliest}T00:00:00Z`);
  date.setUTCMonth(date.getUTCMonth() + 3);
  return date.toISOString().slice(0, 10);
}

type Editing = { mode: "grant" } | { mode: "change" | "end"; grant: SeatGrant };

export function OrganisationSeatsPanel({
  organisation,
  canManage,
  onChanged,
}: {
  organisation: { tenant_id: string; name: string };
  /** The platform organisation capability; the server also checks the owner. */
  canManage: boolean;
  onChanged: () => void;
}) {
  const [view, setView] = useState<OrganisationSeats | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Editing | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    loadOrganisationSeats(organisation.tenant_id, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setView(value);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(organisationError(failure));
      });
    return () => controller.abort();
  }, [organisation.tenant_id]);

  const owner = !!view?.can_grant && canManage;
  return (
    <Panel
      title={`${organisation.name} · Seats`}
      sub="Paid seats come from the plan; free seats only from the owner"
      tools={
        owner ? (
          <Button
            variant="primary"
            disabled={!view || !!editing}
            onClick={() => setEditing({ mode: "grant" })}
          >
            <Gift size={14} aria-hidden="true" />
            Give free seats
          </Button>
        ) : (
          <Badge>
            <Lock size={12} aria-hidden="true" /> Owner gives free seats
          </Badge>
        )
      }
    >
      {error ? (
        <p role="alert" className={kitStyles.fieldError}>
          {error}
        </p>
      ) : null}
      {view ? (
        <>
          <dl className={styles.counts}>
            {(
              [
                ["Seats", view.seats.total_seats],
                ["Paid", view.seats.paid_seats],
                ["Free", view.seats.complimentary_seats],
                ["Members", view.seats.active_members],
                ["Invites", view.seats.pending_invites],
                ["Open", view.seats.seats_available],
              ] as const
            ).map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          <p className={kitStyles.muted}>
            {view.plan
              ? `Plan: ${view.plan.name}, ${seats(view.plan.seats)} a ${view.plan.interval}, this period ends ${istStamp(view.plan.period_end)}.`
              : "No paid plan now."}
          </p>
          {editing && owner ? (
            <SeatGrantEditor
              key={`${editing.mode}:${"grant" in editing ? editing.grant.id : ""}`}
              tenantId={organisation.tenant_id}
              editing={editing}
              view={view}
              onCancel={() => setEditing(null)}
              onSaved={(next) => {
                setView(next);
                setEditing(null);
                onChanged();
              }}
            />
          ) : null}
          {view.grants.length ? (
            <Table label={`${organisation.name} seat grants`}>
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">What</th>
                  <th scope="col" data-num="">
                    Seats
                  </th>
                  <th scope="col">Last day</th>
                  <th scope="col">Reason</th>
                  <th scope="col">By</th>
                  {owner ? <th scope="col" aria-label="Actions" /> : null}
                </tr>
              </thead>
              <tbody>
                {view.grants.map((grant) => (
                  <tr key={grant.id}>
                    <td>{istStamp(grant.created_at)}</td>
                    <td>
                      {KIND[grant.kind]}{" "}
                      {grant.live ? <Badge tone="good">Counting</Badge> : null}
                    </td>
                    <td data-num="">{grant.seats}</td>
                    <td>{dayText(grant.until)}</td>
                    <td>{grant.reason}</td>
                    <td>{grant.granted_by ?? "—"}</td>
                    {owner ? (
                      <td className={styles.actions}>
                        {grant.live ? (
                          <>
                            <Button
                              variant="ghost"
                              disabled={!!editing}
                              onClick={() =>
                                setEditing({ mode: "change", grant })
                              }
                            >
                              Change
                            </Button>
                            <Button
                              variant="ghost"
                              disabled={!!editing}
                              onClick={() => setEditing({ mode: "end", grant })}
                            >
                              End
                            </Button>
                          </>
                        ) : null}
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : (
            <p className={kitStyles.muted}>No free seats given yet.</p>
          )}
          {!owner ? (
            <p className={`${kitStyles.muted} ${styles.note}`}>
              <Lock size={13} aria-hidden="true" /> Only the owner gives,
              changes or ends free seats.
            </p>
          ) : null}
        </>
      ) : error ? null : (
        <p role="status" className={kitStyles.muted}>
          Loading seats…
        </p>
      )}
    </Panel>
  );
}

function SeatGrantEditor({
  tenantId,
  editing,
  view,
  onCancel,
  onSaved,
}: {
  tenantId: string;
  editing: Editing;
  view: OrganisationSeats;
  onCancel: () => void;
  onSaved: (next: OrganisationSeats) => void;
}) {
  const replaced = editing.mode === "grant" ? null : editing.grant;
  const ending = editing.mode === "end";
  const [count, setCount] = useState(String(replaced?.seats ?? 4));
  const [until, setUntil] = useState(
    replaced?.until ?? suggestedUntil(view.earliest_until),
  );
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // One key per intent: a retry of the same request is answered, not repeated.
  const [key, setKey] = useState(() => crypto.randomUUID());

  const number = ending ? 0 : Number(count);
  const free = view.seats.complimentary_seats - (replaced?.seats ?? 0) + number;
  const total = view.seats.paid_seats + free;
  const held = view.seats.active_members + view.seats.pending_invites;
  const problem = ending
    ? !reason.trim()
      ? "Add a short reason; it goes in the audit trail."
      : null
    : !/^\d{1,3}$/.test(count.trim()) || number < 1 || number > 500
      ? "Give between 1 and 500 seats."
      : !until || until < view.earliest_until || until > view.latest_until
        ? `Choose a last day from ${dayText(view.earliest_until)} to ${dayText(view.latest_until)}.`
        : reason.trim().length < 3
          ? "Add a short reason; it goes in the audit trail."
          : replaced && number === replaced.seats && until === replaced.until
            ? "That is the grant as it stands."
            : null;

  function edit(setter: (value: string) => void) {
    return (value: string) => {
      setter(value);
      setConfirming(false);
      setError("");
      setKey(crypto.randomUUID());
    };
  }

  async function save() {
    if (problem || busy) return;
    setBusy(true);
    setError("");
    try {
      onSaved(
        await grantOrganisationSeats(
          tenantId,
          {
            seats: number,
            until: ending ? null : until,
            reason: reason.trim(),
            supersedes_grant_id: replaced?.id ?? null,
          },
          { key },
        ),
      );
    } catch (failure) {
      setError(organisationError(failure));
      setBusy(false);
    }
  }

  const verb = ending
    ? `End ${seats(replaced!.seats)}`
    : replaced
      ? `Change to ${seats(number)} until ${dayText(until)}`
      : `Give ${seats(number)} until ${dayText(until)}`;
  return (
    <div className={styles.editor}>
      {ending ? (
        <p>
          End the grant of {seats(replaced!.seats)} (last day{" "}
          {dayText(replaced!.until)}) now.
        </p>
      ) : (
        <>
          <Field label="Free seats">
            <input
              aria-label="Free seats"
              type="text"
              inputMode="numeric"
              value={count}
              onChange={(event) => edit(setCount)(event.target.value)}
              disabled={busy}
            />
          </Field>
          <Field label="Last day they count">
            <input
              aria-label="Last day they count"
              type="date"
              min={view.earliest_until}
              max={view.latest_until}
              value={until}
              onChange={(event) => edit(setUntil)(event.target.value)}
              disabled={busy}
            />
          </Field>
        </>
      )}
      <Field label="Reason (audited)" wide>
        <input
          aria-label="Reason for the free seats"
          type="text"
          maxLength={300}
          value={reason}
          onChange={(event) => edit(setReason)(event.target.value)}
          disabled={busy}
        />
      </Field>
      {confirming && !problem ? (
        <div
          className={styles.confirm}
          role="group"
          aria-label="Confirm the free seats"
        >
          <p>
            <strong>{verb}</strong>
          </p>
          <ul>
            <li>
              Seats now: {seats(view.seats.total_seats)} (
              {view.seats.paid_seats} paid, {view.seats.complimentary_seats}{" "}
              free)
            </li>
            <li>
              Seats after: <strong>{seats(total)}</strong> (
              {view.seats.paid_seats} paid, {free} free)
            </li>
          </ul>
          {held > total ? (
            <p className={kitStyles.muted}>
              {held} members and invites hold seats, more than {total}. No one
              is removed; new invites wait until a seat is free.
            </p>
          ) : null}
          <p className={kitStyles.muted}>
            No payment and no billing record. The organisation sees the seat
            count, never the reason or the last day.
          </p>
          <span className={styles.buttons}>
            <Button
              variant="primary"
              onClick={() => void save()}
              disabled={busy}
            >
              {busy ? "Saving…" : verb}
            </Button>
            <Button
              variant="ghost"
              onClick={() => setConfirming(false)}
              disabled={busy}
            >
              Back
            </Button>
          </span>
        </div>
      ) : (
        <span className={styles.buttons}>
          <Button
            variant="primary"
            onClick={() => setConfirming(true)}
            disabled={busy || !!problem}
            title={problem ?? ""}
          >
            Review
          </Button>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        </span>
      )}
      {problem && (reason || !ending) ? (
        <small className={kitStyles.muted}>{problem}</small>
      ) : null}
      {error ? (
        <small role="alert" className={kitStyles.fieldError}>
          {error}
        </small>
      ) : null}
    </div>
  );
}
