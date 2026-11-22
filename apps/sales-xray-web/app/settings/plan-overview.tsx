"use client";

/**
 * Plan & billing, summary first (sx-redesign board, pick 07 C, owner 21 Nov
 * 2026): one hero says the plan and the analysis minutes left once, in big
 * type, with a small "% left" ring and the one green button; then short rows,
 * each one line with a quiet value: minutes by person, add minutes, invoices,
 * seats. Under 20% left the hero turns amber and its button adds minutes.
 * Everything here is read from the billing account; nothing is made up (no
 * payment method: the app has none to show).
 */

import Link from "next/link";
import {
  Armchair,
  ChevronRight,
  FileText,
  Layers,
  Plus,
  Users,
} from "lucide-react";
import { useEffect, useState } from "react";

import type { Allowance } from "../acquisition-client";
import { documentStatus } from "../billing/document-status";
import { day, formatMoney, money, count } from "../billing/money";
import { RefundRequest, type RequestRefund } from "../billing/refund-request";
import type { BillingDocument } from "../billing/billing-view";
import type { MePlan, Subscriptions } from "../billing/contract";
import { trialHeadline, trialLeft } from "../billing/trial-copy";
import { Ring } from "../organisation/family";
import family from "../organisation/family.module.css";
import { readSeats, type OrgSeats } from "../organisation/organisation-api";
import { SeatsPanel } from "../organisation/seats-panel";
import type { DisplayTopUpPack } from "../plans/plans-catalogue-fixture";
import { Sheet } from "../ui/sheet";
import { readTeamTime, type MemberTime } from "./analysis-time";
import styles from "./plan-overview.module.css";

type Loaded<T> =
  | { state: "loading" }
  | { state: "ready"; value: T }
  | { state: "error" };

const LOW_SHARE = 0.2;
const mins = (seconds: number) => Math.max(0, Math.floor(seconds / 60));
const first = (name: string) => name.trim().split(/\s+/)[0] || name;

function statusWord(
  subs: Subscriptions | null,
  unread: boolean,
): {
  label: string;
  tone?: string;
} {
  const current = subs?.current;
  if (unread) return { label: "Couldn't load" };
  if (!current) return { label: "No plan yet", tone: "amber" };
  if (current.cancelAtPeriodEnd)
    return { label: "Cancels at period end", tone: "amber" };
  switch (current.status) {
    case "active":
      return { label: "Active", tone: "good" };
    case "pending_authorisation":
      return { label: "Awaiting payment", tone: "amber" };
    case "past_due":
      return { label: "Payment due", tone: "red" };
    case "halted":
      return { label: "Paused", tone: "amber" };
    default:
      return { label: "Ended" };
  }
}

export function PlanOverview({
  allowance,
  mePlan,
  subs,
  documents,
  status,
  invoicesStatus,
  busy,
  onCancel,
  onRefund,
  onBuyTopUp,
  packs,
  purchasesAllowed,
  plansOnWeb,
  seesSeats,
}: {
  allowance: Loaded<Allowance>;
  mePlan: MePlan | null;
  subs: Subscriptions | null;
  documents?: BillingDocument[];
  status: "loading" | "ready" | "error";
  invoicesStatus: "loading" | "ready" | "error";
  busy: boolean;
  onCancel?: (subscriptionId: string) => void;
  onRefund?: RequestRefund;
  onBuyTopUp?: (pack: DisplayTopUpPack) => void;
  packs: DisplayTopUpPack[];
  purchasesAllowed: boolean;
  plansOnWeb: string | null;
  seesSeats: boolean;
}) {
  const [open, setOpen] = useState<"people" | "invoices" | "seats" | null>(
    null,
  );
  const [shown, setShown] = useState(open);
  if (open && open !== shown) setShown(open);
  const [cancelAsk, setCancelAsk] = useState(false);
  const [team, setTeam] = useState<MemberTime[] | null>(null);
  const [seats, setSeats] = useState<OrgSeats | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    readTeamTime(controller.signal).then(setTeam, () => undefined);
    if (seesSeats) readSeats(controller.signal).then(setSeats, () => undefined);
    return () => controller.abort();
  }, [seesSeats]);

  const current = subs?.current ?? null;
  const loading = status === "loading";
  const unread = !loading && status !== "ready";
  // On the free month the chip says so, not "No plan yet" (owner, 22 Nov 2026).
  const onTrial = !current && !unread && Boolean(mePlan?.trial);
  const word = onTrial
    ? { label: "Free", tone: "good" }
    : statusWord(subs, unread);
  const planName = mePlan?.plan.name ?? current?.planName ?? null;
  const time = allowance.state === "ready" ? allowance.value : null;
  const total = time ? mins(time.allowance_seconds) : 0;
  const left = time ? mins(time.available_seconds) : 0;
  const share = total > 0 ? left / total : 0;
  const unlimited = time?.unlimited === true;
  // The free trial in plain words (owner, 22 Nov 2026: "1 month + 3 hours"):
  // "Free for 1 month · 3 hours of call analysis", "27 days · 2 h 10 min left".
  const trial = !current && !unlimited ? (mePlan?.trial ?? null) : null;
  const low = Boolean(time) && !unlimited && total > 0 && share < LOW_SHARE;
  const topUp = purchasesAllowed && onBuyTopUp ? packs[0] : undefined;
  const canCancel =
    current &&
    !current.cancelAtPeriodEnd &&
    ["active", "past_due", "halted"].includes(current.status);
  const renewal = current?.cancelAtPeriodEnd
    ? `Access until ${day(current.currentPeriod?.end ?? null) || "the period ends"}`
    : current?.renewsAt
      ? `Renews ${day(current.renewsAt)}`
      : status === "ready" && !current && !trial
        ? "No subscription yet."
        : null;
  const used = [...(team ?? [])]
    .filter((person) => person.used_seconds > 0)
    .sort((a, b) => b.used_seconds - a.used_seconds);
  const latest = documents?.[0] ?? null;

  // "Get more minutes" (a call report's limit, issue 243) lands here: the card
  // comes into view once the top-up is read.
  useEffect(() => {
    if (!topUp || window.location.hash !== "#add-minutes") return;
    document.getElementById("add-minutes")?.scrollIntoView({ block: "center" });
  }, [topUp]);

  const heroButton =
    low && topUp ? (
      <button
        type="button"
        className={family.primary}
        disabled={busy}
        onClick={() => onBuyTopUp?.(topUp)}
      >
        Add minutes
      </button>
    ) : purchasesAllowed ? (
      <Link className={family.primary} href="/plans">
        {current ? "Change plan" : "Choose a plan"}
      </Link>
    ) : null;

  return (
    <div className={`${family.stack} ${styles.overview}`} data-plan-overview="">
      <section
        className={`${family.hero} ${styles.hero}`}
        data-tone={low ? "amber" : undefined}
        data-ringless={time && !unlimited && total > 0 ? undefined : ""}
        aria-labelledby="plan-hero"
      >
        <div className={styles.heroMain}>
          <div className={styles.planLine}>
            <span className={family.tile}>
              <Layers aria-hidden="true" />
            </span>
            <h2 id="plan-hero" className={styles.planName}>
              {loading ? "Loading your plan…" : (planName ?? "No plan yet")}
            </h2>
            {loading || (!current && !unread) ? null : (
              <span className={family.chip} data-tone={word.tone}>
                {word.label}
              </span>
            )}
          </div>
          <p className={styles.minutes}>
            {allowance.state === "loading"
              ? "Reading your minutes…"
              : allowance.state === "error"
                ? "Minutes couldn't load"
                : unlimited
                  ? "Unlimited minutes"
                  : trial && time
                    ? trialLeft(trial, time.available_seconds)
                    : total > 0
                      ? `${count(left)} of ${count(total)} min left`
                      : "No analysis minutes yet"}
          </p>
          {loading ? (
            <p className={family.heroLine} role="status">
              Loading billing details…
            </p>
          ) : null}
          <p className={family.heroLine}>
            {unread ? "We couldn't load your plan details right now. " : null}
            {[
              unlimited && time
                ? `${count(mins(time.committed_seconds))} min used or reserved`
                : trial
                  ? trialHeadline(trial)
                  : total <= 0 && allowance.state === "ready"
                    ? "Ask the AC team to allot minutes."
                    : mePlan
                      ? `Analysis minutes for calls up to ${count(mePlan.longestCallSeconds / 60)} min long`
                      : "Analysis minutes for your sales calls",
              renewal,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
          {heroButton ? (
            <div className={`${family.heroActions} ${styles.heroButton}`}>
              {heroButton}
            </div>
          ) : null}
        </div>
        {time && !unlimited && total > 0 ? (
          <Ring
            done={left}
            total={total}
            size={104}
            tone={low ? "amber" : undefined}
            label={`${Math.round(share * 100)}% of the minutes left`}
          >
            <b>{Math.round(share * 100)}%</b>
            <small>left</small>
          </Ring>
        ) : null}
      </section>

      <div className={styles.rows}>
        {used.length ? (
          <button
            type="button"
            className={`${family.card} ${family.row} ${styles.rowCard}`}
            onClick={() => setOpen("people")}
          >
            <span className={family.tile}>
              <Users aria-hidden="true" />
            </span>
            <span className={family.rowText}>
              <span className={family.rowTitle}>Minutes by person</span>
              <span className={family.rowSub}>
                {used
                  .slice(0, 3)
                  .map(
                    (person) =>
                      `${first(person.name)} ${count(mins(person.used_seconds))}`,
                  )
                  .join(" · ")}
              </span>
            </span>
            <ChevronRight className={family.chevron} aria-hidden="true" />
          </button>
        ) : null}

        {topUp ? (
          <div
            id="add-minutes"
            className={`${family.card} ${family.row} ${styles.rowCard}`}
          >
            <span className={family.tile}>
              <Plus aria-hidden="true" />
            </span>
            <span className={family.rowText}>
              <span className={family.rowTitle}>Add minutes</span>
              <span className={family.rowSub}>
                {`${count(topUp.minutes)} min for ${money(topUp.pricePaise)}${topUp.gstInclusive ? "" : " + GST"}`}
              </span>
            </span>
            {low ? (
              <span />
            ) : (
              <button
                type="button"
                className={family.outline}
                disabled={busy}
                aria-label={`Top up ${topUp.minutes} min`}
                onClick={() => onBuyTopUp?.(topUp)}
              >
                Add
              </button>
            )}
          </div>
        ) : null}

        {documents && purchasesAllowed ? (
          <button
            type="button"
            className={`${family.card} ${family.row} ${styles.rowCard}`}
            onClick={() => setOpen("invoices")}
            disabled={invoicesStatus !== "ready"}
          >
            <span className={family.tile}>
              <FileText aria-hidden="true" />
            </span>
            <span className={family.rowText}>
              <span className={family.rowTitle}>Invoices</span>
              <span className={family.rowSub}>
                {invoicesStatus === "loading"
                  ? "Loading invoices…"
                  : invoicesStatus !== "ready"
                    ? "Invoices are unavailable right now"
                    : latest
                      ? `${day(latest.createdAt)} · ${formatMoney(latest.amount)} · ${documentStatus(latest)}`
                      : "No invoices or receipts yet."}
              </span>
            </span>
            <ChevronRight className={family.chevron} aria-hidden="true" />
          </button>
        ) : null}

        {seesSeats ? (
          <button
            type="button"
            className={`${family.card} ${family.row} ${styles.rowCard}`}
            onClick={() => setOpen("seats")}
          >
            <span className={family.tile}>
              <Armchair aria-hidden="true" />
            </span>
            <span className={family.rowText}>
              <span className={family.rowTitle}>Seats</span>
              <span className={family.rowSub}>
                {!seats
                  ? "People who can sign in"
                  : seats.exempt
                    ? "No seat limit"
                    : seats.totalSeats > 0
                      ? `${seats.activeMembers + seats.pendingInvites} of ${seats.totalSeats} seats taken`
                      : "No seats yet"}
              </span>
            </span>
            <ChevronRight className={family.chevron} aria-hidden="true" />
          </button>
        ) : null}
      </div>

      {!purchasesAllowed && plansOnWeb ? (
        <p className={family.note}>{plansOnWeb}</p>
      ) : null}
      {purchasesAllowed && current?.renewalNeedsCustomerApproval ? (
        <p className={family.note}>
          Your bank will ask you to approve each renewal above ₹15,000.
        </p>
      ) : null}
      {purchasesAllowed ? (
        <p className={family.note}>
          Full refund within 7 days if none of a payment&apos;s minutes were
          used.
        </p>
      ) : null}

      {canCancel && current ? (
        cancelAsk ? (
          <div className={`${family.card} ${styles.confirm}`}>
            <p className={family.note}>
              Renewal stops; you keep access to the end of the period.
            </p>
            <div className={family.heroActions}>
              <button
                type="button"
                className={family.neutral}
                disabled={busy}
                onClick={() => setCancelAsk(false)}
              >
                Keep renewal
              </button>
              <button
                type="button"
                className={family.dangerText}
                disabled={busy || !onCancel}
                onClick={() => onCancel?.(current.subscriptionId)}
              >
                Yes, stop renewal
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            className={family.dangerText}
            disabled={busy || status !== "ready" || !onCancel}
            onClick={() => setCancelAsk(true)}
          >
            Cancel renewal
          </button>
        )
      ) : null}

      <Sheet
        open={open === "people"}
        onClose={() => setOpen(null)}
        title="Minutes by person"
        wide="center"
      >
        <ul
          className={family.plainList}
          aria-label="Minutes used by each person"
        >
          {used.map((person) => (
            <li key={person.person_id} className={family.row}>
              <span />
              <span className={family.rowTitle}>{person.name}</span>
              <span className={styles.value}>
                {count(mins(person.used_seconds))} min
              </span>
            </li>
          ))}
        </ul>
      </Sheet>

      <Sheet
        open={open === "invoices"}
        onClose={() => setOpen(null)}
        title="Invoices"
        wide="center"
      >
        {documents?.length ? (
          <ul className={family.plainList} aria-label="Invoices and receipts">
            {documents.map((document) => (
              <li
                key={document.id}
                className={`${family.row} ${styles.invoice}`}
              >
                <span />
                <span className={family.rowText}>
                  <span className={family.rowTitle}>
                    {formatMoney(document.amount)}
                  </span>
                  <span className={family.rowSub} data-wrap="">
                    {day(document.createdAt)} · {document.description}
                  </span>
                  <span className={family.chips}>
                    {document.invoiceHref ? (
                      <a className={family.link} href={document.invoiceHref}>
                        Invoice
                      </a>
                    ) : null}
                    {document.receiptHref ? (
                      <a className={family.link} href={document.receiptHref}>
                        Receipt
                      </a>
                    ) : null}
                    {onRefund && document.refund?.state === "available" ? (
                      <RefundRequest
                        refund={document.refund}
                        amount={formatMoney(document.amount)}
                        onRequest={onRefund}
                        className={family.outline}
                      />
                    ) : null}
                  </span>
                </span>
                <span className={family.chip}>{documentStatus(document)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className={family.note}>No invoices or receipts yet.</p>
        )}
      </Sheet>

      <Sheet
        open={open === "seats"}
        onClose={() => setOpen(null)}
        title="Seats"
        wide="center"
      >
        {shown === "seats" ? (
          <SeatsPanel version={0} onSeats={setSeats} />
        ) : null}
      </Sheet>
    </div>
  );
}
