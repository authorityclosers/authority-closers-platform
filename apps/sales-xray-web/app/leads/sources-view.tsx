"use client";

/**
 * Lead sources, as simple as signing in (owner, 16 Oct): Facebook &
 * Instagram, Google Ads (Continue with Google, owner 18 Oct: "done now") and
 * LinkedIn, each one row with its real logo, a
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
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Badge, Button, Field } from "../ui/kit";
import {
  AppCard,
  AppCardSkeleton,
  AppLogo,
  cardStyles,
  StatusPill,
} from "./app-card";
import { useAppConnect } from "./app-connect";
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
import formStyles from "./meta-forms.module.css";
import { SpendSummary } from "./ad-spend";
import { JourneyStrip } from "./journey/journey-strip";
import { WebsitesCard } from "./websites/websites-card";
import { topLine } from "../organisation/setup/meta-accounts";

/* ---------- Meta connector API (lead_desk/connectors) ---------- */

export type MetaForm = {
  id: string;
  name: string;
  status: string;
  /** How many leads Meta holds for the form, when it says. */
  leads?: number | null;
};
export type MetaBackfill = {
  state: "running" | "done" | "blocked";
  created: number;
  /** Read from Meta and already in the leads: linked, asked again, or the same lead. */
  linked?: number;
  repeat?: number;
  known?: number;
  /** How many forms this run reads. */
  forms?: number;
  /** The older leads asked for: sent in these days before the Page went on. */
  days?: number | null;
  seen: number;
  finishedAt?: string | null;
  error?: string | null;
};
export type MetaProblem = {
  kind: "token" | "permission" | "lead_access" | "other";
  text: string;
};
/** The Facebook account a Page was shared through (bug report #8), and since
 *  when it is connected here. */
export type MetaAccount = {
  id?: string | null;
  name: string;
  picture?: string | null;
  connectedAt?: string | null;
};
export type MetaPage = {
  pageId: string;
  name: string;
  active: boolean;
  account?: MetaAccount | null;
  received: number;
  lastReceivedAt?: string | null;
  /** When it was switched on: only leads sent since come in by themselves. */
  connectedAt?: string | null;
  /** A real form has sent it a lead, not only Meta's testing tool. */
  realLeads?: boolean;
  /** Removed by a manager: off, and out of the list until put back. */
  removed?: boolean;
  /** When Sales Xray last asked Meta for this Page's leads (every 10 minutes). */
  lastPulledAt?: string | null;
  /** "all" takes every form on the Page, ones made later too. */
  forms?: "all" | string[];
  formsCovered?: MetaForm[];
  /** Every form on the Page, taken or not, archived ones too. */
  formsOnPage?: MetaForm[];
  /** Bringing in the older leads Meta still keeps (90 days). */
  backfill?: MetaBackfill | null;
  /** Why Meta last refused this Page. */
  problem?: MetaProblem | null;
};

/** Which forms bring leads in, in a few words. */
export function formsLine(page: MetaPage): string {
  const names = (page.formsCovered ?? []).map((form) =>
    form.status && form.status !== "ACTIVE"
      ? `${form.name} (${form.status.toLowerCase()})`
      : form.name,
  );
  const all = !page.forms || page.forms === "all";
  if (!names.length)
    return all
      ? "All forms on this Page, new ones too"
      : "The forms you picked";
  return all
    ? `All forms, new ones too: ${names.join(", ")}`
    : `Forms: ${names.join(", ")}`;
}

/**
 * What a "Check now" found, in words: new leads apart from people who asked
 * again (repeats were counted as new before, 25 Oct 2026).
 */
export function checkedLine(
  name: string,
  created: number,
  repeat: number,
): string {
  if (!created && !repeat) return `No new leads from ${name}.`;
  const parts = [
    created ? `${created} new lead${created === 1 ? "" : "s"}` : null,
    repeat
      ? `${repeat} ${repeat === 1 ? "person" : "people"} asked again`
      : null,
  ].filter(Boolean);
  return `${parts.join(", ")} from ${name}.`;
}

/** How many leads a run read that were already in the leads. */
export function alreadyHere(backfill?: MetaBackfill | null): number {
  if (!backfill) return 0;
  return (
    (backfill.linked ?? 0) + (backfill.repeat ?? 0) + (backfill.known ?? 0)
  );
}

/**
 * Where bringing in older leads has got to, or null when it never ran. It says
 * what was read, not only what was new (bug report #10, 25 Oct 2026: "Bring old
 * leads did nothing, says no added" when every lead was already here).
 */
export function backfillLine(backfill?: MetaBackfill | null): string | null {
  if (!backfill) return null;
  const leads = (count: number) => `${count} lead${count === 1 ? "" : "s"}`;
  const found = `${leads(backfill.seen)} read: ${backfill.created} new, ${alreadyHere(backfill)} already in your leads`;
  if (backfill.state === "running")
    return `Bringing in older leads… ${found} so far`;
  if (backfill.state === "blocked") return "Older leads stopped: see below";
  return backfill.seen
    ? `Older leads, last 90 days: ${found}`
    : "Older leads: Meta has none from the last 90 days";
}

/** A run of older leads as a chip: what it found, in a few words. */
export function backfillChip(backfill?: MetaBackfill | null): string | null {
  if (!backfill) return null;
  if (backfill.state === "running") return `Old leads: ${backfill.seen} read`;
  if (backfill.state === "blocked") return "Old leads stopped";
  return backfill.seen
    ? `Old leads: ${backfill.created} new, ${alreadyHere(backfill)} already here`
    : "No old leads on Meta";
}

type MetaStatus = { configured: boolean; pages: MetaPage[] };
const META = "/v1/lead-desk/meta";
const RETURNED: Record<string, string> = {
  connected: "Connected. Turn on the Pages you want leads from.",
  nopages: "No Pages were shared. Connect again and tick your Page.",
  cancelled: "Connecting was cancelled.",
  failed: "That didn't finish. Try connecting again.",
};

async function connectorCall<T>(
  url: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(url, {
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

const metaCall = <T,>(path: string, init: RequestInit = {}) =>
  connectorCall<T>(`${META}${path}`, init);

/** A signal that gives up after ``ms``, so a read never spins forever. */
function timeLimit(ms: number): AbortSignal {
  const controller = new AbortController();
  setTimeout(() => controller.abort(), ms);
  return controller.signal;
}

/* ---------- Google Ads connector API (lead_desk/connectors) ---------- */

export type GoogleAccount = {
  customerId: string;
  name: string;
  active: boolean;
  test: boolean;
  received: number;
  lastPulledAt?: string | null;
  /** Lead forms in the account, and how many post each new lead here now. */
  forms?: number | null;
  sending?: number | null;
  /** Forms that keep someone else's webhook: the 10-minute check still reads them. */
  other?: number | null;
};
type GoogleStatus = { configured: boolean; accounts: GoogleAccount[] };
type GooglePull = { account: GoogleAccount; created: number; repeat: number };
const GOOGLE = "/v1/lead-desk/google";
const GOOGLE_RETURNED: Record<string, string> = {
  connected: "Connected. Turn on the accounts you want leads from.",
  noaccounts:
    "That Google account has no Google Ads accounts. Sign in with the one that runs your ads.",
  cancelled: "Connecting was cancelled.",
  failed: "That didn't finish. Try connecting again.",
};

/** One line under an account: leads so far, and where its forms send them. */
export function googleLine(account: GoogleAccount): string {
  if (!account.active) return "Switched off: no new leads come in";
  const parts = [
    `${account.received} lead${account.received === 1 ? "" : "s"}`,
  ];
  if (account.forms != null) {
    if (account.forms === 0) parts.push("no lead forms yet");
    else if (account.sending === account.forms)
      parts.push(
        `${account.forms} form${account.forms === 1 ? "" : "s"} send here instantly`,
      );
    else
      parts.push(
        `${account.sending ?? 0} of ${account.forms} forms send here instantly`,
      );
  }
  if (account.lastPulledAt) parts.push(`checked ${ago(account.lastPulledAt)}`);
  return parts.join(" · ");
}

function GoogleTile() {
  const params = useSearchParams();
  const [status, setStatus] = useState<GoogleStatus | null>(null);
  const [note, setNote] = useState<string | null>(
    GOOGLE_RETURNED[params.get("google") ?? ""] ?? null,
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const load = () =>
    connectorCall<GoogleStatus>(`${GOOGLE}/status`, {
      signal: timeLimit(15000),
    })
      .then((next) => {
        setFailed(false);
        setStatus({
          ...next,
          accounts: Array.isArray(next?.accounts) ? next.accounts : [],
        });
      })
      .catch(() => {
        setFailed(true);
        setStatus((current) => current ?? { configured: true, accounts: [] });
      });
  useEffect(() => {
    void load();
  }, []);
  // In the Sales Xray app, Continue with Google opens in the phone's browser.
  const connect = useAppConnect("google", ({ result, message }) => {
    setNote(message ?? GOOGLE_RETURNED[result] ?? GOOGLE_RETURNED.failed);
    if (result === "connected") void load();
  });

  const run = async (account: GoogleAccount, work: () => Promise<string>) => {
    setBusy(account.customerId);
    setNote(null);
    try {
      setNote(await work());
      await load();
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(null);
    }
  };
  const path = (account: GoogleAccount, tail = "") =>
    `${GOOGLE}/accounts/${encodeURIComponent(account.customerId)}${tail}`;

  const toggle = (account: GoogleAccount) =>
    run(account, async () => {
      if (account.active) {
        await connectorCall(path(account, "/disconnect"), { method: "POST" });
        return `${account.name} is switched off.`;
      }
      const result = await connectorCall<{ imported: number }>(path(account), {
        method: "POST",
      });
      return result.imported
        ? `${result.imported} lead${result.imported === 1 ? "" : "s"} from the last 30 days came in.`
        : `${account.name} is on. New leads arrive here.`;
    });

  // Google's webhook can be late or missing, so Sales Xray also asks every
  // 10 minutes; this asks now and points any new lead forms here.
  const pull = (account: GoogleAccount) =>
    run(account, async () => {
      const result = await connectorCall<GooglePull>(path(account, "/pull"), {
        method: "POST",
      });
      return checkedLine(account.name, result.created, result.repeat);
    });

  const live = status?.accounts.filter((account) => account.active).length ?? 0;
  return (
    <SourceRow
      kind="google"
      title="Google Ads"
      text="Leads from your lead form ads, without copying anything."
      loading={status === null}
      status={
        !status ? null : failed ? (
          <StatusPill tone="warn">Didn&apos;t load</StatusPill>
        ) : !status.configured ? (
          <StatusPill>Coming soon</StatusPill>
        ) : live ? (
          <StatusPill tone="good">
            {live} account{live === 1 ? "" : "s"} on
          </StatusPill>
        ) : status.accounts.length ? (
          <StatusPill tone="warn">Switched off</StatusPill>
        ) : (
          <StatusPill>Not connected</StatusPill>
        )
      }
      action={
        failed ? (
          <Button variant="ghost" onClick={() => void load()}>
            <RefreshCw size={14} aria-hidden="true" />
            Try again
          </Button>
        ) : status?.configured ? (
          <a
            className={
              status.accounts.length ? cardStyles.secondary : cardStyles.primary
            }
            href={`${GOOGLE}/connect`}
            onClick={connect}
          >
            {status.accounts.length ? (
              <>
                <Plus size={14} aria-hidden="true" />
                Add an account
              </>
            ) : (
              "Connect"
            )}
          </a>
        ) : null
      }
    >
      {status?.configured && status.accounts.length ? (
        <ul className={styles.pageList} aria-label="Google Ads accounts">
          {status.accounts.map((account) => (
            <li
              key={account.customerId}
              className={styles.pageRow}
              data-off={account.active ? undefined : ""}
            >
              <span className={styles.pageName}>
                <strong>
                  {account.name}
                  {account.test ? <Badge>Test account</Badge> : null}
                </strong>
                <small>{googleLine(account)}</small>
              </span>
              <span className={styles.pageActions}>
                {account.active ? (
                  <Button
                    variant="ghost"
                    disabled={busy === account.customerId}
                    onClick={() => pull(account)}
                  >
                    <RefreshCw size={14} aria-hidden="true" />
                    Check now
                  </Button>
                ) : null}
                <Button
                  variant={account.active ? "ghost" : "primary"}
                  disabled={busy === account.customerId}
                  onClick={() => toggle(account)}
                >
                  {account.active ? "Switch off" : "Turn on"}
                </Button>
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {status?.configured &&
      status.accounts.some((account) => account.active && account.other) ? (
        <p className={styles.hint}>
          Some forms already send leads to another tool, so they keep it. Sales
          X-Ray still checks them every 10 minutes.
        </p>
      ) : null}
      {note ? (
        <p className={styles.hint} role="status">
          {note}
        </p>
      ) : null}
    </SourceRow>
  );
}

/* ---------- One card per source ---------- */

const LOGOS: Record<"meta" | "google" | "linkedin", string[]> = {
  // Instagram rides on the Facebook mark: one source, both apps.
  meta: ["facebook", "instagram"],
  google: ["googleads"],
  linkedin: ["linkedin"],
};

function SourceRow({
  kind,
  title,
  text,
  status,
  action,
  loading,
  children,
}: {
  kind: "meta" | "google" | "linkedin";
  title: string;
  text: string;
  status?: ReactNode;
  action?: ReactNode;
  /** The status is still loading: the same card, drawn in its final size. */
  loading?: boolean;
  children?: ReactNode;
}) {
  const logo = <AppLogo brands={LOGOS[kind]} />;
  return (
    <div data-brand={kind}>
      {loading ? (
        <AppCardSkeleton title={title} logo={logo} />
      ) : (
        <AppCard
          logo={logo}
          title={title}
          status={status}
          summary={text}
          action={action}
        >
          {children}
        </AppCard>
      )}
    </div>
  );
}

/**
 * Meta's Leads Access Manager: a business can choose which CRMs read its Pages'
 * leads. Once it is in use, Sales Xray must be on that list.
 */
/**
 * Another Facebook account, or a Page someone else manages (bug reports #7 and #8,
 * 25 Oct 2026: a second account got "App not active" or "page not existing").
 */
export function OtherAccountSteps() {
  return (
    <details className={styles.metaHelp}>
      <summary>Connecting another Facebook account or Page?</summary>
      <ul>
        <li>
          Facebook connects the account signed in on this phone or browser. To
          use another one, press{" "}
          <a href={`${META}/connect?switch=1`}>Use another Facebook account</a>:
          Facebook asks you to sign in again, and you can choose the account
          that runs the Page. Each Page shows the account it came through.
        </li>
        <li>
          While Meta reviews Sales Xray, Facebook lets only accounts we have
          added connect. If it says &ldquo;App not active&rdquo;, report it with
          the account&apos;s name and we add it the same day.
        </li>
        <li>
          A Page someone else runs: ask them to give your Facebook account
          access in the Page&apos;s settings, then press Add a Page again.
        </li>
      </ul>
    </details>
  );
}

export function LeadAccessSteps({ open }: { open?: boolean }) {
  return (
    <details className={styles.metaHelp} open={open}>
      <summary>Does your business use Leads Access Manager?</summary>
      <p>
        If your business chooses which apps can read leads, allow Sales Xray
        there, or leads won&apos;t arrive:
      </p>
      <ol>
        <li>
          Open{" "}
          <a
            href="https://business.facebook.com/settings/leads-accesses"
            target="_blank"
            rel="noreferrer"
          >
            Meta Business settings → Integrations → Leads access
          </a>
          .
        </li>
        <li>Pick the Page your lead ads run on.</li>
        <li>
          On the CRMs tab, press Assign CRMs and choose Sales Xray Leads, then
          save.
        </li>
        <li>Come back here and press Check now on the Page.</li>
      </ol>
    </details>
  );
}

function MetaTile() {
  const params = useSearchParams();
  const [status, setStatus] = useState<MetaStatus | null>(null);
  const [note, setNote] = useState<string | null>(
    RETURNED[params.get("meta") ?? ""] ?? null,
  );
  // Bug report #14 (25 Oct 2026: "this loading takes forever"): a read that
  // hangs stops after 15 seconds and says so, with Try again.
  const [failed, setFailed] = useState(false);

  const load = () =>
    metaCall<MetaStatus>("/status", { signal: timeLimit(15000) })
      .then((next) => {
        setFailed(false);
        setStatus({
          ...next,
          pages: Array.isArray(next?.pages) ? next.pages : [],
        });
      })
      .catch(() => {
        setFailed(true);
        setStatus((current) => current ?? { configured: true, pages: [] });
      });
  useEffect(() => {
    void load();
  }, []);
  // In the Sales Xray app, Continue with Meta opens in the phone's browser
  // (Facebook refuses sign-in inside the app) and finishes back here.
  const [appConnected, setAppConnected] = useState(0);
  const connect = useAppConnect("meta", ({ result, message }) => {
    setNote(message ?? RETURNED[result] ?? RETURNED.failed);
    if (result !== "connected") return;
    setAppConnected((times) => times + 1);
    void load();
  });
  // While older leads come in (a slice a minute), keep the count moving.
  const filling = status?.pages.some(
    (page) => page.active && page.backfill?.state === "running",
  );
  useEffect(() => {
    if (!filling) return;
    const timer = setInterval(() => void load(), 20000);
    return () => clearInterval(timer);
  }, [filling]);

  const live = status?.pages.filter((page) => page.active).length ?? 0;
  const blocked = status?.pages.some(
    (page) =>
      page.active &&
      (page.problem?.kind === "lead_access" ||
        page.backfill?.error?.includes("Leads Access Manager")),
  );
  return (
    <SourceRow
      kind="meta"
      title="Facebook & Instagram"
      text="Leads from your Instant Form ads arrive here in seconds."
      loading={status === null}
      status={
        !status ? null : failed ? (
          <StatusPill tone="warn">Didn&apos;t load</StatusPill>
        ) : !status.configured ? (
          <StatusPill>Coming soon</StatusPill>
        ) : live ? (
          <StatusPill tone="good">
            {live} Page{live === 1 ? "" : "s"} on
          </StatusPill>
        ) : status.pages.length ? (
          <StatusPill tone="warn">Switched off</StatusPill>
        ) : (
          <StatusPill>Not connected</StatusPill>
        )
      }
      action={
        failed ? (
          <Button variant="ghost" onClick={() => void load()}>
            <RefreshCw size={14} aria-hidden="true" />
            Try again
          </Button>
        ) : status?.configured ? (
          <span className={formStyles.actions}>
            <a
              className={
                status.pages.length ? cardStyles.secondary : cardStyles.primary
              }
              href={`${META}/connect`}
              onClick={connect}
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
            {status.pages.length ? (
              <a
                className={cardStyles.chip}
                href={`${META}/connect?switch=1`}
                onClick={connect}
                aria-label="Use another Facebook account"
              >
                Another account
              </a>
            ) : null}
          </span>
        ) : null
      }
    >
      {/* Pages, forms and older leads are managed in one place, Leads setup →
          Sources (owner, 2 Nov 2026); here, what is connected and working. */}
      {status?.configured && status.pages.length ? (
        <p className={styles.hint}>
          {topLine(status.pages)} ·{" "}
          <Link href="/organisation?tab=leads&part=sources">Manage Pages</Link>
        </p>
      ) : null}
      {note ? (
        <p className={styles.hint} role="status">
          {note}
        </p>
      ) : null}
      {status?.configured && status.pages.length ? <SpendSummary /> : null}
      {status?.configured ? <LeadAccessSteps open={blocked} /> : null}
      {status?.configured ? <OtherAccountSteps /> : null}
      {status?.configured && status.pages.length ? (
        <JourneyStrip key={appConnected} />
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
  onImportGoogle,
}: {
  sandbox: boolean;
  onChanged: () => void;
  onImport: () => void;
  onImportGoogle?: () => void;
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
          {onImportGoogle ? (
            <Button onClick={onImportGoogle}>
              <FileSpreadsheet size={14} aria-hidden="true" />
              Import from Google Sheet
            </Button>
          ) : null}
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
  withoutMeta = false,
  onChanged,
  onImport,
  onImportGoogle,
}: {
  sandbox: boolean;
  /** Leads setup → Sources has Facebook & Instagram as its own card above. */
  withoutMeta?: boolean;
  onChanged: () => void;
  onImport: () => void;
  /** Import a Sheet picked in Google's Picker (Lead OS, 27 Oct 2026). */
  onImportGoogle?: () => void;
}) {
  return (
    <div className={styles.sourcesGrid}>
      <section
        className={styles.sourceCards}
        aria-label="Connect where your leads come from"
      >
        <WebsitesCard />
        {withoutMeta ? null : <MetaTile />}
        <GoogleTile />
        <SourceRow
          kind="linkedin"
          title="LinkedIn"
          text="Leads from your Lead Gen Form ads."
          status={<StatusPill>Coming soon</StatusPill>}
        />
      </section>
      <OtherWays
        sandbox={sandbox}
        onChanged={onChanged}
        onImport={onImport}
        onImportGoogle={onImportGoogle}
      />
    </div>
  );
}
