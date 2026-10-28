"use client";
import {
  AlertTriangle,
  Check,
  History,
  Link2,
  RefreshCw,
  Search,
  ShieldCheck,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { notify } from "../../notice-center";
import { useAppConnect } from "../../leads/app-connect";
import {
  SourcesView,
  alreadyHere,
  backfillLine,
  type MetaForm,
  type MetaPage,
} from "../../leads/sources-view";
import { BrandTile } from "../../ui/brand-tile";
import { Skeleton } from "../../ui/kit";
import {
  formKey,
  metaFormStatus,
  metaRequest,
  refreshForms,
  type MetaCatalogue,
} from "./meta-client";
import { MicrophoneAccess } from "./microphone";
import styles from "./setup.module.css";

const outcomes: Record<string, string> = {
  connected: "Facebook connected. Choose the forms you want below.",
  nopages:
    "No Pages shared. Sign in with the account that manages the Page and allow access.",
  cancelled: "Facebook sign-in cancelled. Your connections are unchanged.",
  failed: "Facebook sign-in did not finish. Connect again.",
};
const selectedOn = (page: MetaPage, form: MetaForm) =>
  page.active &&
  (!page.forms || page.forms === "all" || page.forms.includes(form.id));
const plural = (value: number, word: string) =>
  `${value} ${word}${value === 1 ? "" : "s"}`;
/** A no-break space, so a count never ends a line apart from its word. */
const NBSP = String.fromCharCode(160);
/** Search only earns its place once there are more forms than fit a screen. */
const SEARCH_FROM = 7;

/**
 * Leads setup → Sources (owner bugs #75 and #76, 29 Oct 2026: "clutter … make
 * it psychologically appealing"; "selecting is nice but could be cleaner").
 * One summary card, then each Page as a grouped list with a check on the
 * right. Selection is a draft until Save; the save bar shows only while
 * there is something to save. Help and other sources sit in one list of
 * folded rows at the end.
 */
export function OrganisationSources() {
  const params = useSearchParams();
  const router = useRouter();
  const [showOther, setShowOther] = useState(false);
  const [catalogue, setCatalogue] = useState<MetaCatalogue | null>(null);
  const [forms, setForms] = useState<Record<string, MetaForm[] | null>>({});
  const [loadingForms, setLoadingForms] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const request = useRef<AbortController | null>(null);
  const actionLock = useRef(false);
  const dirtyRef = useRef(false);
  const load = useCallback(async () => {
    request.current?.abort();
    const control = new AbortController();
    request.current = control;
    try {
      const next = await metaRequest<MetaCatalogue>(
        "/status",
        undefined,
        AbortSignal.any([control.signal, AbortSignal.timeout(12000)]),
      );
      if (control.signal.aborted) return;
      if (!Array.isArray(next.pages)) throw new Error("No catalogue");
      setCatalogue(next);
      setFailed(false);
      setLoadingForms(true);
      // Show cached forms at once, while each Page refreshes independently.
      setForms(
        Object.fromEntries(
          next.pages.map((page) => [
            page.pageId,
            page.formsOnPage ?? page.formsCovered ?? [],
          ]),
        ),
      );
      if (!dirtyRef.current)
        setPicked(
          new Set(
            next.pages.flatMap((page) =>
              (page.formsOnPage ?? page.formsCovered ?? [])
                .filter((form) => selectedOn(page, form))
                .map((form) => formKey(page.pageId, form.id)),
            ),
          ),
        );
      await refreshForms(
        next.pages,
        (id, listed) => {
          setForms((current) => ({ ...current, [id]: listed }));
          const page = next.pages.find((item) => item.pageId === id);
          if (page && listed && !dirtyRef.current)
            setPicked((current) => {
              const updated = new Set(
                [...current].filter((key) => !key.startsWith(`${id}:`)),
              );
              for (const form of listed)
                if (selectedOn(page, form)) updated.add(formKey(id, form.id));
              return updated;
            });
        },
        control.signal,
      );
    } catch {
      if (control.signal.aborted) return;
      setFailed(true);
      notify({
        id: "meta-catalogue",
        tone: "error",
        title: "Facebook forms didn't load",
        message: "Your saved connections are kept.",
        action: {
          label: "Try again",
          run: () => setAttempt((value) => value + 1),
        },
      });
    } finally {
      if (!control.signal.aborted) setLoadingForms(false);
    }
  }, []);
  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => {
      clearTimeout(timer);
      request.current?.abort();
    };
  }, [load, attempt]);
  useEffect(() => {
    const result = params.get("meta");
    if (result && outcomes[result])
      notify({
        id: "meta-return",
        tone: result === "connected" ? "success" : "info",
        title: outcomes[result],
      });
  }, [params]);
  const complete = ({
    result,
    message,
  }: {
    result: string;
    message?: string;
  }) => {
    notify({
      id: "meta-connect",
      tone: result === "connected" ? "success" : "info",
      title: message ?? outcomes[result] ?? outcomes.failed,
    });
    if (result === "connected") void load();
  };
  // The exact start preserves re-authentication in the Android system-browser handoff too.
  const add = useAppConnect(
    "meta",
    complete,
    "/v1/lead-desk/meta/connect-sources",
  );
  const another = useAppConnect(
    "meta",
    complete,
    "/v1/lead-desk/meta/connect-another",
  );
  const pages = catalogue?.pages ?? [];
  const running = pages.some((page) => page.backfill?.state === "running");
  useEffect(() => {
    if (!running || dirty || busy) return;
    const timer = setInterval(() => void load(), 20000);
    return () => clearInterval(timer);
  }, [running, dirty, busy, load]);
  const change = (next: Set<string>) => {
    dirtyRef.current = true;
    setDirty(true);
    setPicked(next);
  };
  const entries = pages.flatMap((page) =>
    (forms[page.pageId] ?? []).map((form) => ({
      page,
      form,
      key: formKey(page.pageId, form.id),
    })),
  );
  /** What is saved now: Discard puts the checks back to it. */
  const saved = () =>
    new Set(
      entries
        .filter(({ page, form }) => selectedOn(page, form))
        .map(({ key }) => key),
    );
  const discard = () => {
    dirtyRef.current = false;
    setDirty(false);
    setPicked(saved());
  };
  const changes = dirty
    ? (() => {
        const before = saved();
        return entries.filter(({ key }) => before.has(key) !== picked.has(key))
          .length;
      })()
    : 0;
  const visible = entries.filter(({ page, form }) =>
    `${page.name} ${page.account?.name ?? ""} ${form.name}`
      .toLocaleLowerCase()
      .includes(search.toLocaleLowerCase()),
  );
  const act = async (kind: "save" | "older") => {
    if (actionLock.current) return;
    actionLock.current = true;
    setBusy(true);
    setNotice("");
    let done = 0;
    const errors: string[] = [];
    for (const page of pages) {
      const listed = forms[page.pageId];
      // Never infer "turn off" when a Page's form read failed or is still loading.
      if (!listed || !listed.length) continue;
      const ids = listed
        .filter((form) => picked.has(formKey(page.pageId, form.id)))
        .map((form) => form.id);
      const path = `/pages/${encodeURIComponent(page.pageId)}`;
      try {
        if (kind === "older") {
          if (!ids.length) continue;
          if (!page.active) {
            errors.push(
              `${page.name}: save your forms to turn this Page on first.`,
            );
            continue;
          }
          const result = await metaRequest<{ page: MetaPage }>(
            `${path}/backfill`,
            { forms: ids },
          );
          done += 1;
          setNotice((current) =>
            [
              current,
              `${page.name}: ${backfillLine(result.page.backfill) ?? "Older leads requested"}`,
            ]
              .filter(Boolean)
              .join("\n"),
          );
        } else {
          const current =
            page.forms === "all" || !page.forms
              ? listed.map((form) => form.id)
              : page.forms;
          if (!ids.length) {
            if (page.active) await metaRequest(`${path}/disconnect`, {});
          } else if (
            !page.active ||
            current.length !== ids.length ||
            ids.some((id) => !current.includes(id))
          ) {
            await metaRequest(path, {
              forms: ids.length === listed.length ? "all" : ids,
            });
          }
          done += 1;
        }
      } catch (error) {
        errors.push(
          `${page.name}: ${error instanceof Error ? error.message : "Try again."}`,
        );
      }
    }
    if (errors.length)
      notify({
        id: "meta-action",
        tone: "error",
        title: `${errors.length} Page${errors.length === 1 ? " needs" : "s need"} attention`,
        message: errors.join(" "),
      });
    else if (kind === "save") {
      dirtyRef.current = false;
      setDirty(false);
      notify({ id: "meta-action", tone: "success", title: "Lead forms saved" });
    }
    if (done) await load();
    actionLock.current = false;
    setBusy(false);
  };

  const configured = catalogue?.configured === true;
  const total = entries.length;
  const summary = failed
    ? "Forms didn't load. Your saved connections are kept."
    : !catalogue
      ? "Checking your connected Pages…"
      : !configured
        ? "Facebook connections are not set up in this environment."
        : !pages.length
          ? "Connect an account to choose lead forms."
          : `${picked.size} of ${plural(total, "form").replace(" ", NBSP)} bring in leads · ${plural(pages.length, "Page").replace(" ", NBSP)}`;
  return (
    <div className={styles.stack}>
      <section className={styles.hero} aria-label="Facebook accounts">
        <div className={styles.heroHead}>
          <BrandTile brands={["facebook", "instagram"]} size={44} />
          <div className={styles.heroCopy}>
            <h2>Facebook &amp; Instagram</h2>
            <p>{summary}</p>
          </div>
          <button
            className={styles.iconButton}
            aria-label="Refresh Facebook forms"
            title="Refresh"
            disabled={busy || loadingForms}
            onClick={() => void load()}
          >
            <RefreshCw
              size={18}
              aria-hidden="true"
              className={loadingForms ? styles.spin : undefined}
            />
          </button>
        </div>
        {configured && pages.length ? (
          <div className={styles.chips}>
            <a
              className={styles.chip}
              href="/v1/lead-desk/meta/connect-sources"
              onClick={add}
            >
              <Link2 size={16} aria-hidden="true" />
              Add Pages
            </a>
            <button
              className={styles.chip}
              disabled={busy || dirty || !picked.size || loadingForms}
              onClick={() => void act("older")}
            >
              <History size={16} aria-hidden="true" />
              {busy ? "Working…" : "Fetch old leads"}
            </button>
            <span
              className={styles.status}
              data-tone="warn"
              title="Meta is still reviewing the app"
            >
              Test leads only
            </span>
          </div>
        ) : configured && catalogue ? (
          <div className={styles.chips}>
            <a
              className={styles.primary}
              href="/v1/lead-desk/meta/connect-sources"
              onClick={add}
            >
              <Link2 size={16} aria-hidden="true" />
              Add Pages
            </a>
            <a
              className={styles.chip}
              href="/v1/lead-desk/meta/connect-another"
              onClick={another}
            >
              Another account
            </a>
          </div>
        ) : failed ? (
          <div className={styles.chips}>
            <button className={styles.chip} onClick={() => void load()}>
              <RefreshCw size={16} aria-hidden="true" />
              Try again
            </button>
          </div>
        ) : !catalogue ? (
          <Skeleton height={36} />
        ) : null}
      </section>
      {!catalogue && !failed ? (
        <div
          className={styles.stack}
          aria-label="Loading forms"
          aria-busy="true"
        >
          <Skeleton height={148} />
          <Skeleton height={148} />
        </div>
      ) : null}
      {total >= SEARCH_FROM ? (
        <label className={styles.searchField}>
          <Search size={18} aria-hidden="true" />
          <input
            type="search"
            aria-label="Search accounts, Pages and forms"
            placeholder="Find a Page or form"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
      ) : null}
      {pages.map((page) => {
        const items = visible.filter(
          (item) => item.page.pageId === page.pageId,
        );
        const listed = forms[page.pageId];
        if (search && !items.length) return null;
        const on = items.filter((item) => picked.has(item.key)).length;
        const all = items.length > 0 && on === items.length;
        return (
          <section
            key={page.pageId}
            className={styles.group}
            aria-label={`Forms on ${page.name}`}
          >
            <header className={styles.groupHead}>
              <div className={styles.groupTitle}>
                <h3>{page.name}</h3>
                <small>
                  {page.account?.name ?? "Facebook account"} ·{" "}
                  {listed ? plural(listed.length, "form") : "Forms unknown"}
                </small>
              </div>
              <span
                className={styles.status}
                data-tone={page.active ? "good" : "off"}
              >
                {page.active ? "On" : "Off"}
              </span>
              {items.length > 1 ? (
                <button
                  className={styles.textButton}
                  disabled={busy}
                  onClick={() => {
                    const next = new Set(picked);
                    items.forEach((item) =>
                      all ? next.delete(item.key) : next.add(item.key),
                    );
                    change(next);
                  }}
                >
                  {all ? "Clear" : "Select all"}
                </button>
              ) : null}
            </header>
            <ul className={styles.rows}>
              {page.problem || listed === null ? (
                <li className={styles.problem}>
                  <AlertTriangle size={18} aria-hidden="true" />
                  <span>
                    {page.problem?.kind === "token"
                      ? "Sign in again to restore access."
                      : (page.problem?.text ??
                        "Forms could not refresh. Reconnect or try again.")}
                  </span>
                  <a
                    href="/v1/lead-desk/meta/connect-another"
                    onClick={another}
                    className={styles.chip}
                  >
                    Sign in again
                  </a>
                </li>
              ) : null}
              {!items.length && listed !== null ? (
                <li className={styles.rowNote}>
                  {loadingForms
                    ? "Checking this Page’s forms…"
                    : "No forms shared by Meta. Check Page access, then refresh."}
                </li>
              ) : null}
              {items.map(({ form, key }) => (
                <li key={key}>
                  <button
                    className={styles.pick}
                    aria-pressed={picked.has(key)}
                    disabled={busy}
                    onClick={() => {
                      const next = new Set(picked);
                      if (next.has(key)) next.delete(key);
                      else next.add(key);
                      change(next);
                    }}
                  >
                    <span className={styles.pickCopy}>
                      <strong>{form.name}</strong>
                      <small data-status={form.status}>
                        {metaFormStatus(form.status)}
                        {form.leads == null
                          ? ""
                          : ` · ${plural(form.leads, "lead")}`}
                      </small>
                    </span>
                    <span className={styles.tick} aria-hidden="true">
                      {picked.has(key) ? (
                        <Check size={15} strokeWidth={3} />
                      ) : null}
                    </span>
                  </button>
                </li>
              ))}
              {page.backfill ? (
                <li className={styles.rowNote} role="status">
                  <History size={14} aria-hidden="true" />
                  <span>
                    {page.backfill.state === "running"
                      ? "Reading older leads"
                      : page.backfill.state === "blocked"
                        ? "Import needs attention"
                        : "Last import"}{" "}
                    · {page.backfill.seen} read · {page.backfill.created} new ·{" "}
                    {alreadyHere(page.backfill)} already here
                  </span>
                </li>
              ) : null}
            </ul>
          </section>
        );
      })}
      {pages.length && !visible.length && search ? (
        <p className={styles.help}>No matching forms. Clear your search.</p>
      ) : null}
      {notice ? (
        <p role="status" className={styles.notice}>
          {notice}
        </p>
      ) : null}
      {dirty && pages.length ? (
        <div
          className={styles.saveBar}
          role="region"
          aria-label="Unsaved forms"
        >
          <span className={styles.saveCount}>
            {changes ? plural(changes, "change") : "Unsaved"}
          </span>
          <button
            className={styles.textButton}
            disabled={busy}
            onClick={discard}
          >
            Discard
          </button>
          <button
            className={styles.primary}
            disabled={busy || loadingForms}
            onClick={() => void act("save")}
          >
            {busy ? "Saving…" : "Save forms"}
          </button>
        </div>
      ) : null}
      <div className={styles.more}>
        <details
          className={styles.details}
          onToggle={(event) => setShowOther(event.currentTarget.open)}
        >
          <summary>Other lead sources</summary>
          {showOther ? (
            <div className={styles.otherProviders}>
              <SourcesView
                sandbox={false}
                onChanged={() => undefined}
                onImport={() => router.push("/leads?import=file")}
                onImportGoogle={() => router.push("/leads?import=google")}
              />
            </div>
          ) : null}
        </details>
        {configured && pages.length ? (
          <details className={styles.details}>
            <summary>Page missing or wrong account?</summary>
            <div className={styles.detailBody}>
              <p className={styles.help}>
                Sign in as the Page’s manager and allow its Pages. Your other
                connected accounts stay. If Meta asks to edit previous access,
                select every Page you want.
              </p>
              <a
                className={styles.chip}
                href="/v1/lead-desk/meta/connect-another"
                onClick={another}
              >
                <Link2 size={16} aria-hidden="true" />
                Another account
              </a>
            </div>
          </details>
        ) : null}
        <details className={styles.details}>
          <summary>Duplicates and older leads</summary>
          <div className={styles.detailBody}>
            <p className={styles.help}>
              <ShieldCheck size={16} aria-hidden="true" /> Imports use your
              existing duplicate checks: certain matches merge; uncertain
              matches wait for review. Paused forms can supply older leads.
            </p>
          </div>
        </details>
        <MicrophoneAccess />
      </div>
    </div>
  );
}
