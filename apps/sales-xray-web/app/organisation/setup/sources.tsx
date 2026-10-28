"use client";
import { Check, History, Link2, RefreshCw, ShieldCheck } from "lucide-react";
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
import { Skeleton } from "../../ui/kit";
import {
  formKey,
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

/** One catalogue: every connected Facebook account, Page and form. Selection is a draft until Save. */
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
  const visible = entries.filter(({ page, form }) =>
    `${page.name} ${page.account?.name ?? ""} ${form.name}`
      .toLocaleLowerCase()
      .includes(search.toLocaleLowerCase()),
  );
  const allVisible =
    visible.length > 0 && visible.every((item) => picked.has(item.key));
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
  return (
    <div className={styles.stack}>
      <section className={styles.card} aria-label="Facebook accounts">
        <header className={styles.head}>
          <div>
            <h2>Facebook & Instagram</h2>
            <p>{pages.length} Pages · Choose forms for new leads.</p>
          </div>
          <button
            className={styles.button}
            aria-label="Refresh Facebook forms"
            disabled={busy || loadingForms}
            onClick={() => void load()}
          >
            <RefreshCw size={18} />
          </button>
        </header>
        {catalogue?.configured ? (
          <>
            <div className={styles.tools}>
              <a
                className={pages.length ? styles.button : styles.primary}
                href="/v1/lead-desk/meta/connect-sources"
                onClick={add}
              >
                <Link2 size={16} />
                Add Pages
              </a>
              <a
                className={styles.button}
                href="/v1/lead-desk/meta/connect-another"
                onClick={another}
              >
                Another account
              </a>
            </div>
            <p className={styles.help}>
              Meta review pending · Test leads only.
            </p>
          </>
        ) : !catalogue && !failed ? (
          <Skeleton height={44} />
        ) : null}
      </section>
      {!catalogue && !failed ? (
        <div aria-label="Loading forms" aria-busy="true">
          <Skeleton height={160} />
          <Skeleton height={160} />
        </div>
      ) : null}
      {failed ? (
        <button className={styles.button} onClick={() => void load()}>
          Try loading forms again
        </button>
      ) : null}
      {catalogue && !catalogue.configured ? (
        <p className={styles.help}>
          Facebook connections are not set up in this environment.
        </p>
      ) : null}
      {pages.length ? (
        <>
          <input
            className={styles.search}
            type="search"
            aria-label="Search accounts, Pages and forms"
            placeholder="Find an account, Page or form"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <div className={styles.tools}>
            <button
              className={styles.button}
              disabled={busy || !visible.length}
              onClick={() => {
                const next = new Set(picked);
                visible.forEach((item) =>
                  allVisible ? next.delete(item.key) : next.add(item.key),
                );
                change(next);
              }}
            >
              {allVisible ? "Clear shown" : "Select all shown"}
            </button>
            <span className={styles.badge}>{picked.size} selected</span>
            {loadingForms ? (
              <span role="status" className={styles.help}>
                Checking forms…
              </span>
            ) : null}
          </div>
        </>
      ) : null}
      {pages.map((page) => {
        const items = visible.filter(
          (item) => item.page.pageId === page.pageId,
        );
        const listed = forms[page.pageId];
        if (search && !items.length) return null;
        return (
          <section
            key={page.pageId}
            className={styles.card}
            aria-label={`Forms on ${page.name}`}
          >
            <div className={styles.copy}>
              <h3>{page.name}</h3>
              <small>
                {page.account?.name ?? "Facebook account"} ·{" "}
                {page.active ? "On" : "Off"} · {listed?.length ?? "—"} forms
              </small>
            </div>
            {page.problem || listed === null ? (
              <div className={styles.tools}>
                <span className={styles.help}>
                  {page.problem?.kind === "token"
                    ? "Sign in again to restore access."
                    : (page.problem?.text ??
                      "Forms could not refresh. Reconnect or try again.")}
                </span>
                <a
                  href="/v1/lead-desk/meta/connect-another"
                  onClick={another}
                  className={styles.button}
                >
                  Sign in again
                </a>
              </div>
            ) : null}
            {!items.length && listed !== null ? (
              <p className={styles.help}>
                {loadingForms
                  ? "Checking this Page’s forms…"
                  : "No forms shared by Meta. Check Page access, then refresh."}
              </p>
            ) : null}
            <ul className={styles.list}>
              {items.map(({ form, key }) => (
                <li key={key}>
                  <button
                    className={styles.choice}
                    aria-pressed={picked.has(key)}
                    disabled={busy}
                    onClick={() => {
                      const next = new Set(picked);
                      if (next.has(key)) next.delete(key);
                      else next.add(key);
                      change(next);
                    }}
                  >
                    <span className={styles.check} aria-hidden="true">
                      {picked.has(key) ? <Check size={16} /> : null}
                    </span>
                    <span className={styles.copy}>
                      <strong>{form.name}</strong>
                      <small>
                        {form.status === "ACTIVE"
                          ? "Active"
                          : "Paused or archived"}
                        {form.leads == null
                          ? ""
                          : ` · ${form.leads} leads on Meta`}
                      </small>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            {page.backfill ? (
              <p className={styles.help} role="status">
                {page.backfill.state === "running"
                  ? "Reading older leads"
                  : page.backfill.state === "blocked"
                    ? "Import needs attention"
                    : "Last import"}{" "}
                · {page.backfill.seen} read · {page.backfill.created} new ·{" "}
                {alreadyHere(page.backfill)} already here
              </p>
            ) : null}
          </section>
        );
      })}
      {pages.length && !visible.length && search ? (
        <p className={styles.help}>No matching forms. Clear your search.</p>
      ) : null}
      {notice ? (
        <p role="status" className={styles.help}>
          {notice}
        </p>
      ) : null}
      {pages.length ? (
        <div className={styles.footer}>
          <button
            className={styles.button}
            disabled={busy || dirty || !picked.size || loadingForms}
            onClick={() => void act("older")}
          >
            <History size={16} />
            {busy ? "Working…" : "Fetch old leads"}
          </button>
          <button
            className={styles.primary}
            disabled={busy || !dirty || loadingForms}
            onClick={() => void act("save")}
          >
            {busy ? "Saving…" : "Save forms"}
          </button>
        </div>
      ) : null}
      <p className={styles.help}>
        <ShieldCheck size={16} aria-hidden="true" /> Imports use your existing
        duplicate checks: certain matches merge; uncertain matches wait for
        review. Paused forms can supply older leads.
      </p>
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
      <details className={styles.details}>
        <summary>Page missing or wrong account?</summary>
        <p className={styles.help}>
          Choose Another account, sign in as the Page’s manager and allow its
          Pages. Your other connected accounts stay. If Meta asks to edit
          previous access, select every Page you want.
        </p>
      </details>
      <MicrophoneAccess />
    </div>
  );
}
