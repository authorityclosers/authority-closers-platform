"use client";

/**
 * Lead stages back to Meta (Conversions API for CRM): the customer picks or
 * creates one of their own Meta datasets while connecting, names the event for
 * each CRM stage, and sees what went out. Only Meta's lead id and hashed
 * contact details leave Sales Xray; the CRM's own history stays the record.
 */

import { Target } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge, Button, Field } from "../ui/kit";
import { ago, LeadsError } from "./leads-client";
import { Group, SwitchRow } from "./app-card";
import styles from "./leads.module.css";

export type MetaDataset = { id: string; name: string };
export type ConversionEvent = {
  id: string;
  leadId: string;
  leadName: string;
  stage: string;
  eventName: string;
  status: "pending" | "delivered" | "rejected" | "dead_letter" | "dropped";
  attempts: number;
  eventTime: string;
  deliveredAt?: string | null;
  error?: string | null;
};
export type Conversions = {
  configured: boolean;
  connected: boolean;
  connectionExpiresAt?: string | null;
  dataset?: MetaDataset | null;
  on: boolean;
  events: Record<string, string | null>;
  testCode?: string | null;
  counts: Record<string, number>;
  lastDeliveredAt?: string | null;
  waitingOn?: string | null;
  /** Stage changes that go once they settle (5 minutes, in case they change back). */
  settling?: number;
  sendsAt?: string | null;
  recent: ConversionEvent[];
};
type Datasets = { adAccounts: MetaDataset[]; datasets: MetaDataset[] };

const BASE = "/v1/lead-desk/meta";
export const STAGES: [string, string][] = [
  ["new", "New"],
  ["not_connected", "Not connected"],
  ["follow_up", "Follow-up"],
  ["interested", "Interested"],
  ["won", "Won"],
  ["lost", "Lost"],
];
const STATUS: Record<ConversionEvent["status"], string> = {
  pending: "Waiting",
  delivered: "Sent",
  rejected: "Refused",
  dead_letter: "Gave up",
  dropped: "Not sent",
};

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    ...init,
    headers: {
      accept: "application/json",
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* no body */
    }
    throw new LeadsError(
      detail ?? "That didn't work. Try again.",
      response.status,
    );
  }
  return (await response.json()) as T;
}

/** One line on what went to Meta lately. */
export function sentLine(view: Conversions): string {
  if (!view.dataset) return "No dataset chosen yet";
  if (!view.on) return `Switched off · ${view.dataset.name}`;
  const sent = view.counts.delivered ?? 0;
  const parts = [
    `Sending to ${view.dataset.name}`,
    `${sent} stage${sent === 1 ? "" : "s"} sent this week`,
  ];
  if (view.lastDeliveredAt) parts.push(`last ${ago(view.lastDeliveredAt)}`);
  const waiting = view.settling ?? 0;
  if (waiting > 0) {
    const minutes = view.sendsAt
      ? Math.ceil((Date.parse(view.sendsAt) - Date.now()) / 60_000)
      : 0;
    parts.push(
      `${waiting} stage${waiting === 1 ? "" : "s"} going ${
        minutes > 1 ? `in about ${minutes} min` : "within a minute"
      }`,
    );
  }
  const pending = view.counts.pending ?? 0;
  if (pending > 0) parts.push(`${pending} waiting to send`);
  return parts.join(" · ");
}

function Chooser({
  view,
  onSaved,
  onCancel,
}: {
  view: Conversions;
  onSaved: (next: Conversions) => void;
  onCancel?: () => void;
}) {
  const [found, setFound] = useState<Datasets | null>(null);
  const [picked, setPicked] = useState<MetaDataset | null>(
    view.dataset ?? null,
  );
  const [events, setEvents] = useState<Record<string, string | null>>(
    view.events,
  );
  const [account, setAccount] = useState("");
  const [name, setName] = useState("Sales Xray CRM");
  const [testCode, setTestCode] = useState(view.testCode ?? "");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    call<Datasets>("/datasets")
      .then((data) => {
        setFound(data);
        setAccount(data.adAccounts[0]?.id ?? "");
        // One dataset: it is the one (nothing to choose).
        if (data.datasets.length === 1)
          setPicked((current) => current ?? data.datasets[0]);
      })
      .catch((reason: unknown) => {
        setFound({ adAccounts: [], datasets: [] });
        setNote(
          reason instanceof LeadsError
            ? reason.message
            : "Meta didn't list your datasets.",
        );
      });
  }, []);

  const create = async () => {
    setBusy(true);
    setNote(null);
    try {
      const made = await call<MetaDataset>("/datasets", {
        method: "POST",
        body: JSON.stringify({ adAccountId: account, name: name.trim() }),
      });
      setFound((current) => ({
        adAccounts: current?.adAccounts ?? [],
        datasets: [made, ...(current?.datasets ?? [])],
      }));
      setPicked(made);
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    // Never a silent button: say what is missing.
    if (!picked) {
      setNote(
        "Pick the dataset that gets your lead stages, or create one above.",
      );
      return;
    }
    if (Object.values(events).some((name) => name != null && !name.trim())) {
      setNote(
        "Give each stage that is switched on a Meta event name, or switch it off.",
      );
      return;
    }
    setBusy(true);
    setNote(null);
    try {
      onSaved(
        await call<Conversions>("/conversions", {
          method: "PUT",
          body: JSON.stringify({
            datasetId: picked.id,
            datasetName: picked.name,
            on: true,
            events,
            testCode: testCode.trim() || null,
          }),
        }),
      );
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.capiChooser}>
      <fieldset className={styles.capiDatasets}>
        <legend>Which Meta dataset gets your lead stages?</legend>
        {found === null ? <p className={styles.hint}>Asking Meta…</p> : null}
        {found?.datasets.map((dataset) => (
          <label key={dataset.id}>
            <input
              type="radio"
              name="meta-dataset"
              checked={picked?.id === dataset.id}
              onChange={() => setPicked(dataset)}
            />
            <span>
              {dataset.name}
              <small> · {dataset.id}</small>
            </span>
          </label>
        ))}
        {found && !found.datasets.length ? (
          <p className={styles.hint}>
            No datasets yet. Make one for your lead stages below.
          </p>
        ) : null}
      </fieldset>
      {found?.adAccounts.length ? (
        <details className={styles.capiNew} open={!found.datasets.length}>
          <summary>Create a new dataset</summary>
          <div className={styles.row}>
            <Field label="Ad account">
              <select
                value={account}
                onChange={(event) => setAccount(event.target.value)}
              >
                {found.adAccounts.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Dataset name">
              <input
                value={name}
                maxLength={60}
                onChange={(event) => setName(event.target.value)}
              />
            </Field>
            <Button
              disabled={busy || !account || !name.trim()}
              onClick={create}
            >
              Create
            </Button>
          </div>
        </details>
      ) : null}
      <Group
        title="Which stages Meta learns from"
        hint="Switch on the stages to send, and name each as Meta should see it. A lead that jumps ahead also sends the stages it skipped, so Meta sees the whole way from New to Won."
      >
        {STAGES.map(([stage, label]) => {
          const on = events[stage] != null;
          return (
            <SwitchRow
              key={stage}
              label={label}
              hint={
                on
                  ? `Sent to Meta as "${events[stage]?.trim() || "…"}"`
                  : "Not sent to Meta"
              }
              checked={on}
              onChange={(next) =>
                setEvents((current) => ({
                  ...current,
                  [stage]: next ? label : null,
                }))
              }
            >
              <input
                aria-label={`Meta event for ${label}`}
                placeholder={label}
                value={events[stage] ?? ""}
                maxLength={50}
                onChange={(event) =>
                  setEvents((current) => ({
                    ...current,
                    [stage]: event.target.value,
                  }))
                }
              />
            </SwitchRow>
          );
        })}
      </Group>
      <details className={styles.capiNew}>
        <summary>Check it with Meta&apos;s test events</summary>
        <Field
          label="Test code"
          hint="From Meta Events Manager → your dataset → Test events. Leave it empty when you're done checking."
        >
          <input
            value={testCode}
            maxLength={32}
            onChange={(event) => setTestCode(event.target.value)}
          />
        </Field>
      </details>
      <div className={styles.row}>
        {onCancel ? <Button onClick={onCancel}>Cancel</Button> : null}
        <Button variant="primary" disabled={busy} onClick={save}>
          Send lead stages to Meta
        </Button>
      </div>
      {note ? (
        <p className={styles.pageProblem} role="alert">
          {note}
        </p>
      ) : null}
    </div>
  );
}

export function MetaConversions({
  returned,
  onConnect,
}: {
  returned: boolean;
  /** Continue with Meta's click, so the Sales Xray app opens it in the phone's browser. */
  onConnect?: (event: { preventDefault: () => void }) => void;
}) {
  const [view, setView] = useState<Conversions | null>(null);
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    call<Conversions>("/conversions")
      .then((data) => {
        if (!live) return;
        setView(data);
        // Right after Continue with Meta, go straight on to the dataset.
        if (returned && data.connected && !data.dataset) setEditing(true);
      })
      .catch(() => live && setView(null));
    return () => {
      live = false;
    };
  }, [returned]);

  if (!view?.configured) return null;

  const switchTo = async (on: boolean) => {
    if (!view.dataset) return;
    setBusy(true);
    setNote(null);
    try {
      setView(
        await call<Conversions>("/conversions", {
          method: "PUT",
          body: JSON.stringify({
            datasetId: view.dataset.id,
            datasetName: view.dataset.name,
            on,
            events: view.events,
            testCode: view.testCode ?? null,
          }),
        }),
      );
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(false);
    }
  };

  const again = async (event: ConversionEvent) => {
    setBusy(true);
    setNote(null);
    try {
      setView(
        await call<Conversions>(`/conversions/${event.id}/retry`, {
          method: "POST",
        }),
      );
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={styles.capi} aria-label="Lead stages back to Meta">
      <div className={styles.capiHead}>
        <Target size={16} aria-hidden="true" />
        <strong>Lead stages back to Meta</strong>
        {view.dataset ? (
          <Badge tone={view.on ? "good" : "neutral"}>
            {view.on ? "On" : "Off"}
          </Badge>
        ) : null}
      </div>
      <p className={styles.hint}>
        Your ads learn which leads become customers and find more like them.
        Sales Xray sends each Meta lead&apos;s stage to your dataset:
        Meta&apos;s lead id and hashed contact details, nothing else.
      </p>
      {!view.connected ? (
        <p className={styles.hint}>
          <a href={`${BASE}/connect`} onClick={onConnect}>
            Continue with Meta
          </a>{" "}
          again to choose a dataset.
        </p>
      ) : editing || !view.dataset ? (
        <Chooser
          view={view}
          onSaved={(next) => {
            setView(next);
            setEditing(false);
            setNote(
              "Lead stages now go to Meta. In Meta Events Manager, open the dataset and set up your sales funnel: put the stages in order and pick the one your ads aim for.",
            );
          }}
          onCancel={view.dataset ? () => setEditing(false) : undefined}
        />
      ) : (
        <>
          <div className={styles.capiStatus}>
            <span>{sentLine(view)}</span>
            <span className={styles.pageActions}>
              <Button variant="ghost" onClick={() => setEditing(true)}>
                Change
              </Button>
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => switchTo(!view.on)}
              >
                {view.on ? "Switch off" : "Turn on"}
              </Button>
            </span>
          </div>
          {view.waitingOn ? (
            <p className={styles.pageProblem} role="alert">
              {view.waitingOn}
            </p>
          ) : null}
          {view.recent.length ? (
            <details className={styles.capiLog}>
              <summary>What went to Meta</summary>
              <ul>
                {view.recent.map((event) => (
                  <li key={event.id}>
                    <span>
                      <strong>{event.leadName}</strong> · {event.eventName}
                    </span>
                    <Badge
                      tone={
                        event.status === "delivered"
                          ? "good"
                          : event.status === "pending"
                            ? "neutral"
                            : "bad"
                      }
                    >
                      {STATUS[event.status]}
                    </Badge>
                    <small>
                      {ago(event.deliveredAt ?? event.eventTime)}
                      {event.attempts > 1 ? ` · ${event.attempts} tries` : ""}
                    </small>
                    {event.status === "rejected" ||
                    event.status === "dead_letter" ? (
                      <Button
                        variant="ghost"
                        disabled={busy}
                        onClick={() => again(event)}
                      >
                        Try again
                      </Button>
                    ) : null}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </>
      )}
      {note ? (
        <p className={styles.hint} role="status">
          {note}
        </p>
      ) : null}
    </section>
  );
}
