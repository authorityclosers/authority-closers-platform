"use client";

/**
 * Lead sources, as simple as signing in (owner, 16 Oct): Facebook &
 * Instagram, Google Ads and LinkedIn, each one row with its real logo, a
 * status and one action, and one line per connected Page under it (owner,
 * 18 Oct: proper icons and a cleaner layout). Files, sheets and website forms
 * sit behind one collapsed "Other ways to add leads"; technical details
 * appear only when asked for.
 */

import {
  ChevronDown,
  Copy,
  FileSpreadsheet,
  FlaskConical,
  Plus,
  RefreshCw,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { BRANDS, type Brand } from "../brands/brand-registry";
import { BrandMark } from "../report-entities";
import { Badge, Button, Field, kitStyles } from "../ui/kit";
import {
  addSource,
  ago,
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
  /** When Sales Xray last asked Meta for this Page's leads (every 10 minutes). */
  lastPulledAt?: string | null;
};
type MetaPull = {
  page: MetaPage;
  fetched: number;
  created: number;
  repeat: number;
  known: number;
  skipped: number;
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

/* ---------- Brand marks (our own public/brands files) ---------- */

const brand = (key: string): Brand =>
  BRANDS.find((item) => item.key === key) as Brand;

/**
 * The official marks from our own brand files (Simple Icons, CC0). Instagram's
 * colour file is a black glyph that vanishes in dark mode, so it uses its
 * one-colour mark in Instagram's colour instead.
 */
function SourceLogo({ kind }: { kind: "meta" | "google" | "linkedin" }) {
  if (kind === "meta")
    return (
      <span className={styles.sourceLogo} aria-hidden="true">
        <BrandMark brand={brand("facebook")} size={26} />
        <span className={styles.sourceLogoBadge}>
          <BrandMark brand={{ ...brand("instagram"), logo: false }} size={14} />
        </span>
      </span>
    );
  return (
    <span className={styles.sourceLogo} aria-hidden="true">
      <BrandMark
        brand={brand(kind === "google" ? "googleads" : "linkedin")}
        size={24}
      />
    </span>
  );
}

function SourceRow({
  kind,
  title,
  text,
  status,
  action,
  children,
}: {
  kind: "meta" | "google" | "linkedin";
  title: string;
  text: string;
  status?: ReactNode;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <article className={styles.sourceRow} data-brand={kind}>
      <SourceLogo kind={kind} />
      <div className={styles.sourceMain}>
        <div className={styles.sourceTitle}>
          <h3>{title}</h3>
          {status}
        </div>
        <p>{text}</p>
      </div>
      {action ? <div className={styles.sourceAction}>{action}</div> : null}
      {children ? <div className={styles.sourceMore}>{children}</div> : null}
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

  // Meta's push can be late or missing (apps in development mode never get it),
  // so Sales Xray also asks every 10 minutes; this asks now.
  const pull = async (page: MetaPage) => {
    setBusy(page.pageId);
    setNote(null);
    try {
      const result = await metaCall<MetaPull>(
        `/pages/${encodeURIComponent(page.pageId)}/pull`,
        { method: "POST" },
      );
      const added = result.created + result.repeat;
      setNote(
        added
          ? `${added} new lead${added === 1 ? "" : "s"} from ${page.name}.`
          : `No new leads from ${page.name}.`,
      );
      await load();
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(null);
    }
  };

  const live = status?.pages.filter((page) => page.active).length ?? 0;
  return (
    <SourceRow
      kind="meta"
      title="Facebook & Instagram"
      text="Leads from your Instant Form ads arrive here in seconds."
      status={
        status === null ? (
          <Badge>Checking…</Badge>
        ) : !status.configured ? (
          <Badge>Coming soon</Badge>
        ) : live ? (
          <Badge tone="good">Connected</Badge>
        ) : status.pages.length ? (
          <Badge>Switched off</Badge>
        ) : null
      }
      action={
        status?.configured ? (
          <a
            className={kitStyles.button}
            data-variant={status.pages.length ? undefined : "primary"}
            href={`${META}/connect`}
          >
            {status.pages.length ? (
              <>
                <Plus size={14} aria-hidden="true" />
                Add a Page
              </>
            ) : (
              "Connect"
            )}
          </a>
        ) : null
      }
    >
      {status?.configured && status.pages.length ? (
        <ul className={styles.pageList} aria-label="Facebook Pages">
          {status.pages.map((page) => (
            <li
              key={page.pageId}
              className={styles.pageRow}
              data-off={page.active ? undefined : ""}
            >
              <span className={styles.pageName}>
                <strong>{page.name}</strong>
                <small>
                  {page.active
                    ? [
                        `${page.received} lead${page.received === 1 ? "" : "s"}`,
                        page.lastPulledAt
                          ? `checked ${ago(page.lastPulledAt)}`
                          : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")
                    : "Switched off: no new leads come in"}
                </small>
              </span>
              <span className={styles.pageActions}>
                {page.active ? (
                  <Button
                    variant="ghost"
                    disabled={busy === page.pageId}
                    onClick={() => pull(page)}
                  >
                    <RefreshCw size={14} aria-hidden="true" />
                    Check now
                  </Button>
                ) : null}
                <Button
                  variant={page.active ? "ghost" : "primary"}
                  disabled={busy === page.pageId}
                  onClick={() => toggle(page)}
                >
                  {page.active ? "Switch off" : "Turn on"}
                </Button>
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {note ? (
        <p className={styles.hint} role="status">
          {note}
        </p>
      ) : null}
    </SourceRow>
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
        className={styles.sourceList}
        aria-label="Connect where your leads come from"
      >
        <MetaTile />
        <SourceRow
          kind="google"
          title="Google Ads"
          text="Leads from your lead form ads, without copying anything."
          status={<Badge>Coming soon</Badge>}
        />
        <SourceRow
          kind="linkedin"
          title="LinkedIn"
          text="Leads from your Lead Gen Form ads."
          status={<Badge>Coming soon</Badge>}
        />
      </section>
      <OtherWays sandbox={sandbox} onChanged={onChanged} onImport={onImport} />
    </div>
  );
}
