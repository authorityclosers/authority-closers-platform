"use client";

/**
 * Lead sources, as simple as signing in (owner, 16 Oct): three big Connect
 * buttons — Facebook & Instagram, Google Ads, LinkedIn — and one line per
 * connected account. Files, sheets and website forms sit behind one collapsed
 * "Other ways to add leads"; technical details appear only when asked for.
 */

import { ChevronDown, Copy, FileSpreadsheet, FlaskConical } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Badge, Button, Field } from "../ui/kit";
import {
  addSource,
  LeadsError,
  readSources,
  rotateSource,
  seedTestLeads,
  setSourceActive,
  syncSource,
  type SourceView,
} from "./leads-client";
import styles from "./leads.module.css";

/* ---------- Meta connector API (lead_desk/connectors) ---------- */

type MetaPage = {
  pageId: string;
  name: string;
  active: boolean;
  received: number;
};
type MetaStatus = { configured: boolean; pages: MetaPage[] };
const META = "/v1/lead-desk/meta";
const RETURNED: Record<string, string> = {
  connected: "Connected. Turn on the Pages you want leads from.",
  nopages: "No Pages were shared. Connect again and tick your Page.",
  cancelled: "Connecting was cancelled.",
  failed: "That didn't finish. Try connecting again.",
};

async function metaCall<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${META}${path}`, {
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
      detail ?? "That didn't work. Try again.",
      response.status,
    );
  }
  return (await response.json()) as T;
}

/* ---------- Brand marks (simple, token-coloured) ---------- */

function Mark({ kind }: { kind: "meta" | "google" | "linkedin" }) {
  const text = kind === "meta" ? "f" : kind === "google" ? "G" : "in";
  return (
    <span className={styles.brandMark} data-brand={kind} aria-hidden="true">
      {text}
    </span>
  );
}

function ConnectTile({
  kind,
  title,
  text,
  children,
}: {
  kind: "meta" | "google" | "linkedin";
  title: string;
  text: string;
  children: ReactNode;
}) {
  return (
    <article className={styles.connectTile} data-brand={kind}>
      <Mark kind={kind} />
      <h3 className={styles.connectTitle}>{title}</h3>
      <p className={styles.connectText}>{text}</p>
      <div className={styles.connectBody}>{children}</div>
    </article>
  );
}

function MetaTile() {
  const params = useSearchParams();
  const [status, setStatus] = useState<MetaStatus | null>(null);
  const [note, setNote] = useState<string | null>(
    RETURNED[params.get("meta") ?? ""] ?? null,
  );
  const [busy, setBusy] = useState<string | null>(null);

  const load = () =>
    metaCall<MetaStatus>("/status")
      .then(setStatus)
      .catch(() => setStatus({ configured: false, pages: [] }));
  useEffect(() => {
    void load();
  }, []);

  const toggle = async (page: MetaPage) => {
    setBusy(page.pageId);
    setNote(null);
    try {
      if (page.active) {
        await metaCall(`/pages/${encodeURIComponent(page.pageId)}/disconnect`, {
          method: "POST",
        });
      } else {
        const result = await metaCall<{ imported: number }>(
          `/pages/${encodeURIComponent(page.pageId)}`,
          {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ forms: "all" }),
          },
        );
        if (result.imported)
          setNote(
            `${result.imported} recent lead${result.imported === 1 ? "" : "s"} came in.`,
          );
      }
      await load();
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <ConnectTile
      kind="meta"
      title="Facebook & Instagram"
      text="Leads from your Instant Form ads arrive here in seconds."
    >
      {status === null ? (
        <span className={styles.connectSoon}>Checking…</span>
      ) : !status.configured ? (
        <span className={styles.connectSoon}>Coming soon</span>
      ) : (
        <>
          {status.pages.map((page) => (
            <div key={page.pageId} className={styles.connectedLine}>
              <span>
                {page.active ? "Connected: " : ""}
                <strong>{page.name}</strong>
                {page.active ? ` · ${page.received} leads` : ""}
              </span>
              <Button
                variant={page.active ? "ghost" : "primary"}
                disabled={busy === page.pageId}
                onClick={() => toggle(page)}
              >
                {page.active ? "Switch off" : "Turn on"}
              </Button>
            </div>
          ))}
          <a
            className={styles.connectButton}
            data-brand="meta"
            href={`${META}/connect`}
          >
            {status.pages.length ? "Add another Page" : "Connect"}
          </a>
        </>
      )}
      {note ? (
        <p className={styles.connectNote} role="status">
          {note}
        </p>
      ) : null}
    </ConnectTile>
  );
}

/* ---------- Other ways (collapsed) ---------- */

function CopyLine({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className={styles.copy}>
      <code>{value}</code>
      <Button
        variant="icon"
        aria-label={`Copy ${label}`}
        onClick={() =>
          navigator.clipboard
            .writeText(value)
            .then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            })
            .catch(() => undefined)
        }
      >
        <Copy size={14} aria-hidden="true" />
      </Button>
      {copied ? <small role="status">Copied</small> : null}
    </span>
  );
}

const isGoogleAds = (source: SourceView) =>
  source.kind === "webhook" && source.label.startsWith("Google Ads");

function OtherSource({
  source,
  onChanged,
}: {
  source: SourceView;
  onChanged: (next: SourceView | null, note?: string) => void;
}) {
  const [details, setDetails] = useState(!!source.token);
  const [busy, setBusy] = useState(false);
  const act = async (work: () => Promise<void>) => {
    setBusy(true);
    try {
      await work();
    } catch (reason) {
      onChanged(
        null,
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(false);
    }
  };
  const address = source.endpoint
    ? isGoogleAds(source)
      ? `${source.endpoint}/google-ads`
      : source.endpoint
    : null;
  return (
    <li className={styles.otherItem}>
      <div className={styles.otherHead}>
        <span>
          <strong>{source.label}</strong> · {source.received} leads
          {source.active ? null : <Badge>Off</Badge>}
        </span>
        <span className={styles.sourceActions}>
          {source.kind === "sheet" && source.active ? (
            <Button
              disabled={busy}
              onClick={() =>
                act(async () => {
                  const result = await syncSource(source.source_id);
                  onChanged(
                    null,
                    `${result.created} new leads from the sheet.`,
                  );
                })
              }
            >
              Sync
            </Button>
          ) : null}
          {address ? (
            <Button
              variant="ghost"
              onClick={() => setDetails((value) => !value)}
            >
              {details ? "Hide details" : "Setup details"}
            </Button>
          ) : null}
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() =>
              act(async () =>
                onChanged(
                  await setSourceActive(source.source_id, !source.active),
                ),
              )
            }
          >
            {source.active ? "Switch off" : "Turn on"}
          </Button>
        </span>
      </div>
      {details && address ? (
        <div className={styles.otherDetails}>
          <CopyLine value={address} label="address" />
          {source.token ? (
            <span className={styles.secretOnce}>
              Key, shown once: <CopyLine value={source.token} label="key" />
            </span>
          ) : (
            <Button
              disabled={busy}
              onClick={() =>
                act(async () => onChanged(await rotateSource(source.source_id)))
              }
            >
              Show a new key
            </Button>
          )}
          <p className={styles.hint}>
            {isGoogleAds(source)
              ? "In Google Ads: lead form → Export leads → Webhook. Paste the address and key, then Send test data."
              : "Give these to whoever runs your website form. Each enquiry then lands here."}
          </p>
        </div>
      ) : null}
    </li>
  );
}

type AddKind = "webhook" | "google_ads" | "sheet";

function OtherWays({
  sandbox,
  onChanged,
  onImport,
}: {
  sandbox: boolean;
  onChanged: () => void;
  onImport: () => void;
}) {
  const [sources, setSources] = useState<SourceView[] | null>(null);
  const [fresh, setFresh] = useState<Record<string, SourceView>>({});
  const [adding, setAdding] = useState<AddKind | null>(null);
  const [url, setUrl] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () =>
    readSources()
      .then((data) =>
        setSources(data.sources.filter((source) => source.kind !== "meta")),
      )
      .catch(() => setSources([]));
  useEffect(() => {
    void load();
  }, []);

  const add = async () => {
    if (!adding) return;
    setBusy(true);
    setNote(null);
    try {
      const made = await addSource(
        adding === "sheet"
          ? { kind: "sheet", label: "Google Sheet", sheet_url: url.trim() }
          : {
              kind: "webhook",
              label:
                adding === "google_ads"
                  ? "Google Ads lead form"
                  : "Website form",
            },
      );
      setFresh((current) => ({ ...current, [made.source_id]: made }));
      setAdding(null);
      setUrl("");
      await load();
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(false);
    }
  };

  const seed = async () => {
    setBusy(true);
    try {
      const result = await seedTestLeads(25);
      setNote(`${result.created} test leads added and shared out.`);
      onChanged();
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <details className={styles.otherWays}>
      <summary>
        Other ways to add leads
        <ChevronDown size={16} aria-hidden="true" />
      </summary>
      <div className={styles.otherBody}>
        <div className={styles.row}>
          <Button onClick={onImport}>
            <FileSpreadsheet size={14} aria-hidden="true" />
            Upload a file
          </Button>
          <Button onClick={() => setAdding("sheet")}>Google Sheet</Button>
          <Button onClick={() => setAdding("webhook")}>Website form</Button>
          <Button onClick={() => setAdding("google_ads")}>
            Google Ads (by hand)
          </Button>
          {sandbox ? (
            <Button onClick={seed} disabled={busy}>
              <FlaskConical size={14} aria-hidden="true" />
              Add 25 test leads
            </Button>
          ) : null}
        </div>
        {adding ? (
          <div className={styles.form}>
            {adding === "sheet" ? (
              <Field
                label="Google Sheet link"
                hint='In the sheet: Share → "Anyone with the link" → Viewer.'
              >
                <input
                  value={url}
                  maxLength={500}
                  placeholder="https://docs.google.com/spreadsheets/d/…"
                  onChange={(event) => setUrl(event.target.value)}
                />
              </Field>
            ) : (
              <p className={styles.hint}>
                {adding === "google_ads"
                  ? "You'll get two values to paste into your Google Ads lead form."
                  : "You'll get two values to give whoever runs your website form."}
              </p>
            )}
            <div className={styles.row}>
              <Button onClick={() => setAdding(null)}>Cancel</Button>
              <Button variant="primary" onClick={add} disabled={busy}>
                {adding === "sheet" ? "Connect sheet" : "Create"}
              </Button>
            </div>
          </div>
        ) : null}
        {sources?.length ? (
          <ul className={styles.otherList}>
            {sources.map((source) => (
              <OtherSource
                key={source.source_id}
                source={fresh[source.source_id] ?? source}
                onChanged={(next, message) => {
                  if (next)
                    setFresh((current) => ({
                      ...current,
                      [next.source_id]: next,
                    }));
                  if (message) setNote(message);
                  void load();
                  onChanged();
                }}
              />
            ))}
          </ul>
        ) : null}
        {note ? (
          <p className={styles.hint} role="status">
            {note}
          </p>
        ) : null}
      </div>
    </details>
  );
}

export function SourcesView({
  sandbox,
  onChanged,
  onImport,
}: {
  sandbox: boolean;
  onChanged: () => void;
  onImport: () => void;
}) {
  return (
    <div className={styles.sourcesGrid}>
      <section
        className={styles.connectGrid}
        aria-label="Connect where your leads come from"
      >
        <MetaTile />
        <ConnectTile
          kind="google"
          title="Google Ads"
          text="Leads from your lead form ads, without copying anything."
        >
          <span className={styles.connectSoon}>Coming soon</span>
        </ConnectTile>
        <ConnectTile
          kind="linkedin"
          title="LinkedIn"
          text="Leads from your Lead Gen Form ads."
        >
          <span className={styles.connectSoon}>Coming soon</span>
        </ConnectTile>
      </section>
      <OtherWays sandbox={sandbox} onChanged={onChanged} onImport={onImport} />
    </div>
  );
}
