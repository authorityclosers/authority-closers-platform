"use client";

/**
 * Meta lead forms (Facebook and Instagram Instant Forms) on the Sources tab.
 *
 * Continue with Meta → choose a Page → choose its Instant Forms → Connect.
 * Leads then arrive through Meta's signed webhook, and the last 7 days are
 * pulled in on connect. The connector API is lead_desk/connectors (alignment
 * session); this card only drives it. Until AC's Meta app is set up it says so.
 */

import { useEffect, useState } from "react";

import { Badge, Button } from "../ui/kit";
import { LeadsError, when } from "./leads-client";
import styles from "./leads.module.css";

type MetaPage = {
  pageId: string;
  name: string;
  active: boolean;
  forms: "all" | string[];
  received: number;
  lastReceivedAt: string | null;
};
type MetaStatus = { configured: boolean; pages: MetaPage[] };
type MetaForm = { id: string; name: string; status: string };

const API = "/v1/lead-desk/meta";
const RETURN_NOTES: Record<string, string> = {
  connected:
    "Meta is connected. Choose the forms to bring in for each Page below.",
  nopages:
    "Meta didn't share any Pages. Continue with Meta again and tick at least one Page.",
  cancelled: "Connecting to Meta was cancelled.",
  failed: "Meta didn't finish connecting. Try Continue with Meta again.",
};

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    ...init,
    headers: { accept: "application/json", ...(init.headers ?? {}) },
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
      detail ?? "Meta didn't answer. Try again.",
      response.status,
    );
  }
  return (await response.json()) as T;
}

function PageRow({
  page,
  onChanged,
}: {
  page: MetaPage;
  onChanged: (note: string) => void;
}) {
  const [forms, setForms] = useState<MetaForm[] | null>(null);
  const [picked, setPicked] = useState<"all" | Set<string>>(
    page.forms === "all" ? "all" : new Set(page.forms),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadForms = async () => {
    setBusy(true);
    setError(null);
    try {
      setForms(
        await call<MetaForm[]>(
          `/pages/${encodeURIComponent(page.pageId)}/forms`,
        ),
      );
    } catch (reason) {
      setError(
        reason instanceof LeadsError
          ? reason.message
          : "The forms didn't load.",
      );
    } finally {
      setBusy(false);
    }
  };

  const connect = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await call<{ imported: number }>(
        `/pages/${encodeURIComponent(page.pageId)}`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            forms: picked === "all" ? "all" : Array.from(picked),
          }),
        },
      );
      setForms(null);
      onChanged(
        `${page.name} is connected. ${result.imported} lead${result.imported === 1 ? "" : "s"} from the last 7 days came in.`,
      );
    } catch (reason) {
      setError(
        reason instanceof LeadsError
          ? reason.message
          : "Not connected. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async () => {
    setBusy(true);
    setError(null);
    try {
      await call(`/pages/${encodeURIComponent(page.pageId)}/disconnect`, {
        method: "POST",
      });
      onChanged(`${page.name} is switched off. Its leads stay in Sales Xray.`);
    } catch (reason) {
      setError(
        reason instanceof LeadsError
          ? reason.message
          : "Not switched off. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className={styles.metaPage}>
      <span className={styles.sourceMain}>
        <strong>
          {page.name}{" "}
          {page.active ? (
            <Badge tone="good">Bringing leads in</Badge>
          ) : (
            <Badge>Off</Badge>
          )}
        </strong>
        <small>
          {page.forms === "all"
            ? "All Instant Forms"
            : `${page.forms.length} form${page.forms.length === 1 ? "" : "s"}`}
          {" · "}
          {page.received} received
          {page.lastReceivedAt ? ` · last ${when(page.lastReceivedAt)}` : ""}
        </small>
      </span>
      {forms ? (
        <div className={styles.formPicker}>
          <label className={styles.toggle}>
            <input
              type="checkbox"
              checked={picked === "all"}
              onChange={(event) =>
                setPicked(event.target.checked ? "all" : new Set())
              }
            />
            All Instant Forms, including new ones
          </label>
          {picked !== "all"
            ? forms.map((form) => (
                <label key={form.id} className={styles.toggle}>
                  <input
                    type="checkbox"
                    checked={picked.has(form.id)}
                    onChange={(event) => {
                      const next = new Set(picked);
                      if (event.target.checked) next.add(form.id);
                      else next.delete(form.id);
                      setPicked(next);
                    }}
                  />
                  {form.name}
                  {form.status && form.status !== "ACTIVE" ? (
                    <Badge>{form.status.toLowerCase()}</Badge>
                  ) : null}
                </label>
              ))
            : null}
          {picked !== "all" && forms.length === 0 ? (
            <p className={styles.hint}>This Page has no Instant Forms yet.</p>
          ) : null}
          <div className={styles.row}>
            <Button onClick={() => setForms(null)}>Cancel</Button>
            <Button
              variant="primary"
              onClick={connect}
              disabled={busy || (picked !== "all" && picked.size === 0)}
            >
              {busy ? "Connecting…" : "Connect"}
            </Button>
          </div>
        </div>
      ) : (
        <span className={styles.sourceActions}>
          <Button disabled={busy} onClick={loadForms}>
            {page.active ? "Change forms" : "Choose forms"}
          </Button>
          {page.active ? (
            <Button variant="ghost" disabled={busy} onClick={disconnect}>
              Switch off
            </Button>
          ) : null}
        </span>
      )}
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
    </li>
  );
}

export function MetaCard({ returned }: { returned: string | null }) {
  const [status, setStatus] = useState<MetaStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(
    returned ? (RETURN_NOTES[returned] ?? null) : null,
  );

  const load = () =>
    call<MetaStatus>("/status")
      .then((next) => {
        setStatus(next);
        setError(null);
      })
      .catch((reason: unknown) =>
        setError(
          reason instanceof LeadsError
            ? reason.message
            : "Meta status didn't load.",
        ),
      );

  useEffect(() => {
    void load();
  }, []);

  return (
    <div className={styles.metaCard}>
      <div className={styles.metaHead}>
        <strong>Meta lead forms</strong>
        {status === null ? null : status.configured ? (
          <Badge tone="good">Ready</Badge>
        ) : (
          <Badge tone="warn">Waiting for AC's Meta app</Badge>
        )}
      </div>
      <p className={styles.hint}>
        Facebook and Instagram Instant Forms. Continue with Meta, choose your
        Page, then the forms. New leads arrive here within seconds; the last 7
        days come in when you connect.
      </p>
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      {note ? (
        <p className={styles.hint} role="status">
          {note}
        </p>
      ) : null}
      {status?.configured ? (
        <>
          {status.pages.length ? (
            <ul className={styles.sourceList}>
              {status.pages.map((page) => (
                <PageRow
                  key={page.pageId}
                  page={page}
                  onChanged={(message) => {
                    setNote(message);
                    void load();
                  }}
                />
              ))}
            </ul>
          ) : null}
          <div className={styles.row}>
            <a className={styles.metaButton} href={`${API}/connect`}>
              {status.pages.length ? "Add another Page" : "Continue with Meta"}
            </a>
          </div>
        </>
      ) : status ? (
        <p className={styles.hint}>
          AC's Meta app isn't set up yet. Once it is, a Continue with Meta
          button appears here.
        </p>
      ) : null}
    </div>
  );
}
