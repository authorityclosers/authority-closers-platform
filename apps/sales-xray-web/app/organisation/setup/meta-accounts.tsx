"use client";

/**
 * Leads setup → Sources → Facebook & Instagram, by Facebook account (owner, 2 Nov
 * 2026: he couldn't tell which account connected which Pages or which Pages bring
 * leads, and couldn't remove a wrong account or old Pages). One line says what is
 * connected and working; each account says who and since when, with Disconnect;
 * the Pages that bring leads come first and the rest fold away; a Page shows its
 * active forms, archived ones behind a fold. Older leads come in only when asked:
 * 7, 30 or 90 days, counted first, and they wait on Cold as older enquiries.
 */

import { History, Plus } from "lucide-react";
import { Fragment, useEffect, useRef, useState, type MouseEvent } from "react";

import { sellersOf } from "../../leads/bulk-upload";
import { ago, readTeam, type RepView } from "../../leads/leads-client";
import { displayName } from "../../display-name";
import type {
  MetaBackfill,
  MetaForm,
  MetaPage,
} from "../../leads/sources-view";
import { notify } from "../../notice-center";
import { metaFormStatus, metaRequest } from "./meta-client";
import styles from "./setup.module.css";

const plural = (value: number, word: string) =>
  `${value} ${word}${value === 1 ? "" : "s"}`;
const day = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
  });
const LAST_FORM =
  "A Page needs at least one form; Remove Page turns it off instead";
const failed = (error: unknown) =>
  error instanceof Error ? error.message : "Try again.";

export type AccountGroup = {
  id: string;
  name: string;
  connectedAt: string | null;
  /** Pages bringing leads, then the account's other Pages, then removed ones. */
  on: MetaPage[];
  other: MetaPage[];
  removed: MetaPage[];
};

/** The Pages under the Facebook account that shared each; accounts bringing
 *  leads first. */
export function byAccount(pages: MetaPage[]): AccountGroup[] {
  const groups = new Map<string, AccountGroup>();
  for (const page of pages) {
    const id = page.account?.id ?? "none";
    const group = groups.get(id) ?? {
      id,
      name: page.account?.name ?? "Facebook account",
      connectedAt: page.account?.connectedAt ?? null,
      on: [],
      other: [],
      removed: [],
    };
    if (page.removed) group.removed.push(page);
    else if (page.active) group.on.push(page);
    else group.other.push(page);
    groups.set(id, group);
  }
  return [...groups.values()].sort(
    (a, b) => b.on.length - a.on.length || a.name.localeCompare(b.name),
  );
}

/** What is connected and working, in one sentence. */
export function topLine(pages: MetaPage[], now: Date = new Date()): string {
  const accounts = byAccount(pages);
  const on = accounts.flatMap((group) => group.on);
  const last = on
    .map((page) => page.lastReceivedAt)
    .filter((value): value is string => !!value)
    .sort()
    .at(-1);
  return [
    plural(accounts.length, "Facebook account"),
    on.length
      ? `${plural(on.length, "Page")} bringing leads`
      : "No Page bringing leads yet",
    last ? `last lead ${ago(last, now)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Only Meta's testing tool has sent leads so far (the owner's "Test leads only"). */
export function testOnly(pages: MetaPage[]): boolean {
  const on = pages.filter((page) => page.active && !page.removed);
  return on.length > 0 && !on.some((page) => page.realLeads);
}

const formsOn = (page: MetaPage) =>
  page.forms === "all" || !page.forms
    ? "All forms"
    : plural(page.forms.length, "form");

/** A Page's line: on or off, its forms, its last lead and how many. */
export function pageLine(page: MetaPage, now: Date = new Date()): string {
  if (!page.active)
    return ["Off", plural((page.formsOnPage ?? []).length, "form")].join(" · ");
  return [
    "On",
    formsOn(page),
    page.lastReceivedAt
      ? `last lead ${ago(page.lastReceivedAt, now)}`
      : "no lead yet",
    plural(page.received, "lead"),
  ].join(" · ");
}

/** Where a run of older leads got to. With none new, it says how many were
 *  already here, never "0 brought in · on Cold" (orchestrator, 2 Nov 2026). */
export function runLine(run: MetaBackfill): string {
  if (run.state === "running")
    return `Bringing in older leads… ${run.created} so far`;
  if (run.state === "blocked") return "Older leads stopped: see above";
  if (run.created)
    return `${plural(run.created, "older lead")} brought in · on Cold`;
  const here = (run.linked ?? 0) + (run.repeat ?? 0) + (run.known ?? 0);
  return here
    ? `${plural(here, "older lead")} already here`
    : "No older leads in those days";
}

/** What disconnecting an account stops, said before it does. */
export function stopWords(group: AccountGroup): string {
  const pages = group.on.length + group.other.length + group.removed.length;
  const forms = group.on.reduce(
    (sum, page) => sum + (page.formsCovered ?? []).length,
    0,
  );
  const one = pages === 1 && !forms;
  return `${plural(pages, "Page")}${forms ? ` and ${plural(forms, "form")}` : ""} ${
    one ? "stops" : "stop"
  } bringing leads. Leads already here stay.`;
}

/** Meta's sign-in, started in place (the Sales Xray app hands it to the phone's browser). */
type Connect = (event: MouseEvent<HTMLAnchorElement>) => void;

export function MetaAccounts({
  pages,
  onChanged,
  onAdd,
  onAnother,
}: {
  pages: MetaPage[];
  onChanged: () => void;
  /** Add Pages: Meta's dialog for the account signed in now. */
  onAdd: Connect;
  /** Another Facebook account: Meta asks who signs in. */
  onAnother: Connect;
}) {
  const groups = byAccount(pages);
  // The sellers, for each Page's "Who gets these leads?" (owner, 2 Nov 2026).
  const [sellers, setSellers] = useState<RepView[]>([]);
  const any = pages.length > 0;
  useEffect(() => {
    if (!any) return;
    const controller = new AbortController();
    readTeam(controller.signal).then(
      (team) => setSellers(sellersOf(team.reps)),
      () => undefined,
    );
    return () => controller.abort();
  }, [any]);
  return (
    <>
      {groups.map((group) => (
        <AccountCard
          key={group.id}
          group={group}
          sellers={sellers}
          onChanged={onChanged}
          onAdd={onAdd}
        />
      ))}
      {groups.length ? (
        <a
          className={styles.quietRow}
          href="/v1/lead-desk/meta/connect-another"
          onClick={onAnother}
        >
          <Plus size={18} aria-hidden="true" />
          Connect another Facebook account
        </a>
      ) : null}
    </>
  );
}

function AccountCard({
  group,
  sellers,
  onChanged,
  onAdd,
}: {
  group: AccountGroup;
  sellers: RepView[];
  onChanged: () => void;
  onAdd: Connect;
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const pages = group.on.length + group.other.length;
  const disconnect = async () => {
    setBusy(true);
    try {
      await metaRequest(
        `/accounts/${encodeURIComponent(group.id)}/disconnect`,
        {},
      );
      notify({
        id: "meta-account",
        tone: "success",
        title: `${group.name} disconnected`,
        message: "Leads already here stay.",
      });
      onChanged();
    } catch (error) {
      notify({
        id: "meta-account",
        tone: "error",
        title: "Not disconnected",
        message: failed(error),
      });
    } finally {
      setBusy(false);
      setAsking(false);
    }
  };
  return (
    <section
      className={styles.group}
      aria-label={`Facebook account ${group.name}`}
    >
      <header className={styles.groupHead}>
        <div className={styles.groupTitle}>
          <h3>{group.name}</h3>
          <small>
            {[
              group.connectedAt ? `Connected ${day(group.connectedAt)}` : null,
              plural(pages, "Page"),
            ]
              .filter(Boolean)
              .join(" · ")}
          </small>
        </div>
        {asking ? null : (
          // Plain ink, never the accent: it isn't the account's main action (ux-audit).
          <button
            className={styles.quietButton}
            disabled={busy}
            onClick={() => setAsking(true)}
          >
            Disconnect
          </button>
        )}
      </header>
      {asking ? (
        <div className={styles.confirm} role="alertdialog" aria-live="polite">
          <p>
            Disconnect {group.name}? {stopWords(group)}
          </p>
          <div className={styles.chips}>
            <button
              className={styles.danger}
              disabled={busy}
              onClick={() => void disconnect()}
            >
              {busy ? "Disconnecting…" : "Disconnect"}
            </button>
            <button
              className={styles.chip}
              disabled={busy}
              onClick={() => setAsking(false)}
            >
              Keep
            </button>
          </div>
        </div>
      ) : null}
      {group.on.map((page) => (
        <PageCard
          key={page.pageId}
          page={page}
          sellers={sellers}
          onChanged={onChanged}
        />
      ))}
      {group.other.length ? (
        <details className={styles.details}>
          <summary>
            Other Pages from this account ({group.other.length})
          </summary>
          <ul className={styles.rows}>
            {group.other.map((page) => (
              <OtherPage key={page.pageId} page={page} onChanged={onChanged} />
            ))}
          </ul>
        </details>
      ) : null}
      {group.removed.length ? (
        <details className={styles.details}>
          <summary>Removed Pages ({group.removed.length})</summary>
          <ul className={styles.rows}>
            {group.removed.map((page) => (
              <li key={page.pageId} className={styles.pageRow}>
                <span className={styles.pickCopy}>
                  <strong>{page.name}</strong>
                </span>
                <PageAction
                  page={page}
                  path="restore"
                  label="Put back"
                  done={`${page.name} is back, off`}
                  onChanged={onChanged}
                />
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <a
        className={styles.quietRow}
        href="/v1/lead-desk/meta/connect-sources"
        onClick={onAdd}
      >
        <Plus size={18} aria-hidden="true" />
        Add Pages
      </a>
    </section>
  );
}

/** One button that posts to the Page and reads the list again. */
function PageAction({
  page,
  path,
  label,
  done,
  body = {},
  quiet = false,
  onChanged,
}: {
  page: MetaPage;
  path: string;
  label: string;
  done: string;
  body?: unknown;
  /** Plain ink for a destructive action, never the accent (ux-audit). */
  quiet?: boolean;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      await metaRequest(
        `/pages/${encodeURIComponent(page.pageId)}${path ? `/${path}` : ""}`,
        body,
      );
      notify({ id: "meta-page", tone: "success", title: done });
      onChanged();
    } catch (error) {
      notify({
        id: "meta-page",
        tone: "error",
        title: `${label}: that didn't work`,
        message: failed(error),
      });
    } finally {
      setBusy(false);
    }
  };
  return (
    <button
      className={quiet ? styles.quietButton : styles.textButton}
      disabled={busy}
      onClick={() => void run()}
    >
      {label}
    </button>
  );
}

function OtherPage({
  page,
  onChanged,
}: {
  page: MetaPage;
  onChanged: () => void;
}) {
  return (
    <li className={styles.pageRow}>
      <span className={styles.pickCopy}>
        <strong>{page.name}</strong>
        <small>{pageLine(page)}</small>
      </span>
      <PageAction
        page={page}
        path=""
        label="Turn on"
        body={{ forms: "all" }}
        done={`${page.name} is on: new leads come in from now on`}
        onChanged={onChanged}
      />
      <PageAction
        page={page}
        path="remove"
        label="Remove"
        done={`${page.name} removed`}
        quiet
        onChanged={onChanged}
      />
    </li>
  );
}

function PageCard({
  page,
  sellers,
  onChanged,
}: {
  page: MetaPage;
  sellers: RepView[];
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [older, setOlder] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const all = page.forms === "all" || !page.forms;
  const picked = new Set(
    all
      ? (page.formsOnPage ?? []).map((form) => form.id)
      : (page.forms as string[]),
  );
  const forms = page.formsOnPage ?? [];
  const live = forms.filter((form) => form.status !== "ARCHIVED");
  const archived = forms.filter((form) => form.status === "ARCHIVED");
  const save = async (next: "all" | string[]) => {
    setBusy(true);
    try {
      await metaRequest(`/pages/${encodeURIComponent(page.pageId)}`, {
        forms: next,
      });
      onChanged();
    } catch (error) {
      notify({
        id: "meta-page",
        tone: "error",
        title: "Forms not saved",
        message: failed(error),
      });
    } finally {
      setBusy(false);
    }
  };
  const toggle = (form: MetaForm) => {
    const next = new Set(picked);
    if (next.has(form.id)) next.delete(form.id);
    else next.add(form.id);
    if (next.size) void save([...next]);
    // The last form stays on, teal, and says why (ux-audit): Remove turns the Page off.
    else
      notify({
        id: "meta-page",
        tone: "info",
        title: LAST_FORM,
      });
  };
  // A square box beside each form's name, like All forms: several can be on
  // (ux-audit, 2 Nov 2026: round checks read as pick one).
  const row = (form: MetaForm) => (
    <li key={form.id}>
      <label className={styles.formRow}>
        <input
          type="checkbox"
          checked={picked.has(form.id)}
          disabled={busy || all}
          aria-description={
            picked.has(form.id) && picked.size === 1 ? LAST_FORM : undefined
          }
          onChange={() => toggle(form)}
        />
        <span className={styles.pickCopy}>
          <strong>{form.name}</strong>
          <small data-status={form.status}>
            {metaFormStatus(form.status)}
            {form.leads == null ? "" : ` · ${plural(form.leads, "lead")}`}
          </small>
        </span>
      </label>
    </li>
  );
  const run = page.backfill;
  return (
    <div className={styles.pageCard} aria-label={`Page ${page.name}`}>
      <div className={styles.groupTitle}>
        <h4>{page.name}</h4>
        <small>{pageLine(page)}</small>
      </div>
      {page.problem ? (
        <p className={styles.rowNote} role="status">
          {page.problem.kind === "token"
            ? "Sign in again to restore access."
            : page.problem.text}
        </p>
      ) : null}
      <label className={styles.allForms}>
        <input
          type="checkbox"
          checked={all}
          disabled={busy}
          onChange={(event) =>
            void save(
              event.target.checked
                ? "all"
                : live.map((form) => form.id).slice(0, 100),
            )
          }
        />
        All forms, new ones too
      </label>
      {all ? null : <ul className={styles.rows}>{live.map(row)}</ul>}
      {!all && archived.length ? (
        <details className={styles.details}>
          <summary>Show archived ({archived.length})</summary>
          <ul className={styles.rows}>{archived.map(row)}</ul>
        </details>
      ) : null}
      {choosing ? (
        <WhoGets
          page={page}
          sellers={sellers}
          onClose={() => setChoosing(false)}
          onChanged={onChanged}
        />
      ) : (
        <p className={styles.whoLine}>
          <span>New leads: {whoWords(page, sellers)}</span>
          <button
            className={styles.textButton}
            onClick={() => setChoosing(true)}
          >
            Change
          </button>
        </p>
      )}
      {run ? (
        <p className={styles.rowNote} role="status">
          <History size={14} aria-hidden="true" />
          {runLine(run)}
        </p>
      ) : null}
      {older ? (
        <OlderLeads
          page={page}
          onClose={() => setOlder(false)}
          onChanged={onChanged}
        />
      ) : (
        <div className={styles.pageActions}>
          <button
            className={styles.chip}
            disabled={busy || run?.state === "running"}
            onClick={() => setOlder(true)}
          >
            <History size={16} aria-hidden="true" />
            Bring in older leads
          </button>
          {/* Last, apart and in plain ink: the frequent action stays alone. */}
          <PageAction
            page={page}
            path="remove"
            label="Remove Page"
            done={`${page.name} removed: no more leads from it`}
            quiet
            onChanged={onChanged}
          />
        </div>
      )}
    </div>
  );
}

/** Who gets a Page's new leads, in a few words. */
export function whoWords(page: MetaPage, sellers: RepView[]): string {
  const mode = page.assign?.mode ?? "share";
  if (mode === "none") return "left for you to assign";
  if (mode === "one") {
    const seller = sellers.find(
      (rep) => rep.person_id === page.assign?.personId,
    );
    return seller ? `all to ${displayName(seller.name)}` : "all to one seller";
  }
  return "shared between your sellers";
}

const WHO: { key: "share" | "one" | "none"; label: string }[] = [
  { key: "share", label: "Share between my sellers" },
  { key: "one", label: "One seller" },
  { key: "none", label: "Leave them for me to assign" },
];

/** "Who gets these leads?" for one Page: one question, three answers (owner, 2 Nov 2026). */
function WhoGets({
  page,
  sellers,
  onClose,
  onChanged,
}: {
  page: MetaPage;
  sellers: RepView[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const [mode, setMode] = useState(page.assign?.mode ?? "share");
  const [person, setPerson] = useState<string | null>(
    page.assign?.personId ?? null,
  );
  const [busy, setBusy] = useState(false);
  const ready = mode !== "one" || !!person;
  const save = async () => {
    setBusy(true);
    try {
      await metaRequest(`/pages/${encodeURIComponent(page.pageId)}/assign`, {
        mode,
        ...(mode === "one" ? { personId: person } : {}),
      });
      onChanged();
      onClose();
    } catch (error) {
      notify({
        id: "meta-who",
        tone: "error",
        title: "Not saved",
        message: failed(error),
      });
    } finally {
      setBusy(false);
    }
  };
  return (
    <fieldset className={styles.olderChoice}>
      <legend>Who gets these leads?</legend>
      {WHO.map((item) => (
        <Fragment key={item.key}>
          <label>
            <input
              type="radio"
              name={`who-${page.pageId}`}
              checked={mode === item.key}
              onChange={() => setMode(item.key)}
            />
            {item.label}
          </label>
          {/* The sellers sit under "One seller", not after the last answer
              (ux-audit, 2 Nov 2026). */}
          {item.key === "one" && mode === "one" ? (
            sellers.length ? (
              <ul className={styles.rows} aria-label="Sellers">
                {sellers.map((rep) => (
                  <li key={rep.person_id}>
                    <label className={styles.formRow}>
                      <input
                        type="radio"
                        name={`who-one-${page.pageId}`}
                        checked={person === rep.person_id}
                        onChange={() => setPerson(rep.person_id)}
                      />
                      {displayName(rep.name)}
                    </label>
                  </li>
                ))}
              </ul>
            ) : (
              <small>No sellers yet: invite one in Team.</small>
            )
          ) : null}
        </Fragment>
      ))}
      <div className={styles.chips}>
        <button
          className={styles.primary}
          disabled={busy || !ready}
          onClick={() => void save()}
        >
          {busy ? "Saving…" : "Save"}
        </button>
        <button className={styles.chip} disabled={busy} onClick={onClose}>
          Not now
        </button>
      </div>
    </fieldset>
  );
}

type Counts = { counts: { days: number; leads: number }[]; capped?: boolean };

/** 7, 30 or 90 days before the Page went on, each counted at Meta first. */
function OlderLeads({
  page,
  onClose,
  onChanged,
}: {
  page: MetaPage;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [counts, setCounts] = useState<Counts | null>(null);
  const [days, setDays] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const pageId = page.pageId;
  const closing = useRef(onClose);
  useEffect(() => {
    closing.current = onClose;
  });
  useEffect(() => {
    const controller = new AbortController();
    metaRequest<Counts>(
      `/pages/${encodeURIComponent(pageId)}/older`,
      undefined,
      AbortSignal.any([controller.signal, AbortSignal.timeout(20000)]),
    ).then(setCounts, (error: unknown) => {
      if (controller.signal.aborted) return;
      notify({
        id: "meta-older",
        tone: "error",
        title: "Meta didn't say how many",
        message: failed(error),
      });
      closing.current();
    });
    return () => controller.abort();
  }, [pageId]);
  const chosen = counts?.counts.find((item) => item.days === days);
  const bring = async () => {
    if (!days) return;
    setBusy(true);
    try {
      await metaRequest(`/pages/${encodeURIComponent(page.pageId)}/backfill`, {
        days,
      });
      notify({
        id: "meta-older",
        tone: "success",
        title: `Bringing in ${page.name}’s older leads`,
        message: "They wait on Cold as older enquiries.",
      });
      onChanged();
      onClose();
    } catch (error) {
      notify({
        id: "meta-older",
        tone: "error",
        title: "Older leads didn't start",
        message: failed(error),
      });
    } finally {
      setBusy(false);
    }
  };
  return (
    <fieldset className={styles.olderChoice} aria-busy={!counts || undefined}>
      <legend>Also bring in leads sent before {page.name} went on</legend>
      {(counts?.counts ?? []).map((item) => (
        <label key={item.days}>
          <input
            type="radio"
            name={`older-${page.pageId}`}
            checked={days === item.days}
            onChange={() => setDays(item.days)}
          />
          Last {item.days} days · {item.leads}
          {counts?.capped && item.days === 90 ? "+" : ""}{" "}
          {item.leads === 1 ? "lead" : "leads"}
        </label>
      ))}
      {counts ? null : <small>Asking Meta how many…</small>}
      <div className={styles.chips}>
        <button
          className={styles.primary}
          disabled={busy || !chosen || !chosen.leads}
          onClick={() => void bring()}
        >
          {busy
            ? "Starting…"
            : chosen
              ? `Bring in ${plural(chosen.leads, "lead")}`
              : "Bring in"}
        </button>
        <button className={styles.chip} disabled={busy} onClick={onClose}>
          Not now
        </button>
      </div>
    </fieldset>
  );
}
