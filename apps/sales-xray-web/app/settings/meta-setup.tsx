"use client";

/**
 * Settings -> Connected apps -> Facebook and Instagram lead ads, as one guided
 * setup (owner, 22 Oct 2026: "massive update to Meta connect and review UX"):
 * connect Facebook, turn on a Page and pick its forms, send a test lead, then
 * see what comes in. Above the steps, where Meta's review of Sales Xray stands
 * and what works before it approves, in plain words
 * (lead_desk/connected_apps.meta_review).
 */
import {
  Check,
  Hourglass,
  PlugZap,
  Plus,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useState, type ReactNode } from "react";

import { notify } from "../notice-center";
import { Button } from "../ui/kit";
import {
  ago,
  AppsError,
  checkPage,
  disconnect,
  readForms,
  readMetaPages,
  turnOnPage,
  type AppHealth,
  type Blocker,
  type MetaForm,
  type MetaPage,
  type Review,
} from "./connected-apps-client";
import styles from "./meta-setup.module.css";

type StepState = "done" | "now" | "later";

const failed = (error: unknown) =>
  error instanceof AppsError
    ? error.message
    : "Check your connection and try again.";

const leads = (count: number) => `${count} lead${count === 1 ? "" : "s"}`;

/** "19 Oct" from 2026-10-19. */
export function day(value: string): string {
  const at = new Date(`${value}T00:00:00`);
  return Number.isNaN(at.getTime())
    ? value
    : at.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

/** Which forms bring a Page's leads in, in a few words. */
export function formsWords(page: MetaPage): string {
  if (page.forms === "all") return "All forms, new ones too";
  const names = page.formsCovered.map((form) => form.name);
  if (names.length) return `Forms: ${names.join(", ")}`;
  const count = page.forms.length;
  return `${count} form${count === 1 ? "" : "s"} picked`;
}

/** The Pages as the health read has them, while /meta/status is on its way or can't be read. */
function pagesFrom(app: AppHealth): MetaPage[] {
  return app.connections.map((item) => ({
    pageId: item.id,
    name: item.label,
    active: item.state !== "off",
    received: 0,
    lastPulledAt: null,
    forms: "all",
    formsCovered: [],
    problem:
      item.state === "problem" && item.words
        ? { kind: "other", text: item.words }
        : null,
  }));
}

/** Where Meta's review of Sales Xray stands, and what works meanwhile; with the
 * link that brings ad leads in some other way until Meta approves, when there is one. */
export function ReviewNote({
  review,
  fix = null,
}: {
  review: Review;
  fix?: Blocker | null;
}) {
  const pending = review.state === "pending";
  const Icon = pending ? Hourglass : ShieldCheck;
  return (
    <section
      className={styles.review}
      data-state={review.state}
      aria-label="Meta approval"
    >
      <Icon size={18} aria-hidden="true" className={styles.reviewIcon} />
      <div className={styles.reviewText}>
        <strong>
          {pending ? "Waiting for Meta’s approval" : "Approved by Meta"}
        </strong>
        <small>
          {pending
            ? `Sent for review ${day(review.since)}`
            : `Approved ${day(review.since)}`}
        </small>
        <p>{review.worksNow}</p>
        {review.after ? <p>{review.after}</p> : null}
        {pending && fix?.page && fix.action ? (
          <Link href={fix.page} className={styles.reviewFix}>
            {fix.action} ›
          </Link>
        ) : null}
      </div>
    </section>
  );
}

function Step({
  number,
  title,
  state,
  children,
}: {
  number: number;
  title: string;
  state: StepState;
  children: ReactNode;
}) {
  return (
    <li className={styles.step} data-state={state}>
      <span className={styles.mark} aria-hidden="true">
        {state === "done" ? <Check size={14} strokeWidth={3} /> : number}
      </span>
      <div className={styles.stepBody}>
        <h3>
          {title}
          {state === "done" ? (
            <span className={styles.hidden}> (done)</span>
          ) : null}
        </h3>
        {children}
      </div>
    </li>
  );
}

/** All forms, or only the ones ticked; saving turns the Page on. */
function FormPicker({
  page,
  onCancel,
  onSaved,
}: {
  page: MetaPage;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [forms, setForms] = useState<MetaForm[] | null>(null);
  const [all, setAll] = useState(page.forms === "all");
  const [picked, setPicked] = useState<string[]>(
    page.forms === "all" ? [] : page.forms,
  );
  const [saving, setSaving] = useState(false);
  const group = useId();
  useEffect(() => {
    const controller = new AbortController();
    readForms(page.pageId, controller.signal).then(setForms, () => {
      if (!controller.signal.aborted) setForms([]);
    });
    return () => controller.abort();
  }, [page.pageId]);
  const ready = all || picked.length > 0;

  async function save() {
    setSaving(true);
    try {
      const imported = await turnOnPage(page.pageId, all ? "all" : picked);
      notify({
        id: "meta-setup",
        tone: "success",
        title: page.active
          ? `Forms saved for ${page.name}`
          : `${page.name} is on`,
        message: imported
          ? `${leads(imported)} from the last week came in. Older ones, up to 90 days, follow in a few minutes.`
          : "New leads from its forms now come into Leads by themselves.",
        timeout: 6000,
      });
      onSaved();
    } catch (error) {
      notify({
        id: "meta-setup",
        tone: "error",
        title: page.active
          ? "The forms weren’t saved"
          : `${page.name} wasn’t turned on`,
        message: failed(error),
      });
      setSaving(false);
    }
  }

  return (
    <fieldset className={styles.picker} disabled={saving}>
      <legend>Which forms bring leads in?</legend>
      <label className={styles.choice}>
        <input
          type="radio"
          name={group}
          checked={all}
          onChange={() => setAll(true)}
        />
        <span>All forms, new ones too</span>
      </label>
      <label className={styles.choice}>
        <input
          type="radio"
          name={group}
          checked={!all}
          onChange={() => setAll(false)}
        />
        <span>Only the forms I tick</span>
      </label>
      {all ? null : forms === null ? (
        <p className={styles.quiet}>Loading the Page’s forms…</p>
      ) : forms.length ? (
        <ul className={styles.forms} aria-label="Forms">
          {forms.map((form) => (
            <li key={form.id}>
              <label className={styles.choice}>
                <input
                  type="checkbox"
                  checked={picked.includes(form.id)}
                  onChange={(event) => {
                    const on = event.target.checked;
                    setPicked((current) =>
                      on
                        ? [...current, form.id]
                        : current.filter((id) => id !== form.id),
                    );
                  }}
                />
                <span>
                  {form.name}
                  {form.status && form.status !== "ACTIVE" ? (
                    <em> · {form.status.toLowerCase()}</em>
                  ) : null}
                </span>
              </label>
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.quiet}>
          This Page has no lead forms yet. Pick All forms and the first one you
          make comes in by itself.
        </p>
      )}
      <div className={styles.row}>
        <Button
          variant="primary"
          disabled={!ready || saving}
          onClick={() => void save()}
        >
          {saving
            ? "Saving…"
            : page.active
              ? "Save forms"
              : "Turn on this Page"}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </fieldset>
  );
}

function PageRow({
  page,
  line,
  picking,
  onPick,
  onCancel,
  onSaved,
  onSwitchOff,
}: {
  page: MetaPage;
  line: string;
  picking: boolean;
  onPick: () => void;
  onCancel: () => void;
  onSaved: () => void;
  onSwitchOff: (page: MetaPage) => Promise<void>;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <li className={styles.page} data-on={page.active ? "" : undefined}>
      <div className={styles.pageHead}>
        <div className={styles.pageText}>
          <strong>{page.name}</strong>
          <span>{line}</span>
          {page.active && page.problem ? (
            <span className={styles.pageProblem}>{page.problem.text}</span>
          ) : null}
        </div>
        {picking ? null : (
          <div className={styles.pageActions}>
            {page.active ? (
              <>
                <Button variant="ghost" onClick={onPick}>
                  Forms
                </Button>
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={async () => {
                    if (!confirming) {
                      setConfirming(true);
                      return;
                    }
                    setBusy(true);
                    await onSwitchOff(page);
                    setBusy(false);
                    setConfirming(false);
                  }}
                >
                  {busy
                    ? "Switching off…"
                    : confirming
                      ? `Switch off ${page.name}?`
                      : "Switch off"}
                </Button>
              </>
            ) : (
              <Button
                variant="secondary"
                className={styles.tinted}
                onClick={onPick}
              >
                Turn on
              </Button>
            )}
          </div>
        )}
      </div>
      {picking ? (
        <FormPicker page={page} onCancel={onCancel} onSaved={onSaved} />
      ) : null}
    </li>
  );
}

/** Meta's Leads Access Manager: once a business uses it, Sales Xray must be on its list. */
function LeadAccessHelp() {
  return (
    <details className={styles.help} open>
      <summary>Allow Sales Xray in Leads Access Manager</summary>
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
          On the CRMs tab, press Assign CRMs, choose Sales Xray Leads and save.
        </li>
        <li>Come back here and press Check for new leads now.</li>
      </ol>
    </details>
  );
}

export function MetaSetup({
  app,
  passed,
  test,
  onConnect,
  onChanged,
}: {
  app: AppHealth;
  /** The test lead passed in this sheet. */
  passed: boolean;
  /** The test lead's fields and its result, drawn by the sheet. */
  test: ReactNode;
  onConnect: () => void;
  onChanged: () => void;
}) {
  const [read, setRead] = useState<MetaPage[] | null>(null);
  const [picking, setPicking] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    readMetaPages(controller.signal).then(setRead, () => {
      if (!controller.signal.aborted) setRead(null);
    });
    return () => controller.abort();
    // Read again whenever the sheet's app is read again (onChanged).
  }, [app]);

  // Until the Pages' own read arrives (or if it can't), the health read's.
  const pages = read ?? pagesFrom(app);
  const details = new Map(app.connections.map((item) => [item.id, item]));
  const lineOf = (page: MetaPage) =>
    !page.active
      ? "Off: no new leads come in"
      : read
        ? `${leads(page.received)} · ${formsWords(page)}`
        : (details.get(page.pageId)?.detail ?? "On");
  const on = pages.filter((page) => page.active);
  const received = on.reduce((sum, page) => sum + page.received, 0);
  const accessProblem = on.some((page) => page.problem?.kind === "lead_access");

  const changed = () => {
    setPicking(null);
    onChanged();
  };

  async function switchOff(page: MetaPage) {
    const link = details.get(page.pageId)?.disconnect ?? {
      method: "POST" as const,
      path: `/v1/lead-desk/meta/pages/${encodeURIComponent(page.pageId)}/disconnect`,
    };
    try {
      await disconnect(link);
      notify({
        id: "meta-setup",
        tone: "success",
        title: `${page.name} switched off`,
        message: "New leads from it stop coming in. Turn it on again any time.",
        timeout: 6000,
      });
      changed();
    } catch (error) {
      notify({
        id: "meta-setup",
        tone: "error",
        title: `${page.name} wasn’t switched off`,
        message: failed(error),
      });
    }
  }

  async function checkNow() {
    setChecking(true);
    try {
      let count = 0;
      for (const page of on) count += await checkPage(page.pageId);
      notify({
        id: "meta-setup",
        tone: "success",
        title: count ? `${leads(count)} came in` : "No new leads yet",
        message: count
          ? "They’re in Leads now."
          : "Sales X-Ray also checks by itself every 10 minutes.",
        timeout: 6000,
      });
      changed();
    } catch (error) {
      notify({
        id: "meta-setup",
        tone: "error",
        title: "Couldn’t check for new leads",
        message: failed(error),
      });
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className={styles.setup}>
      {app.review ? (
        <ReviewNote
          review={app.review}
          fix={app.blockers.find((item) => item.page) ?? null}
        />
      ) : null}
      <ol className={styles.steps} aria-label="Set up lead ads">
        <Step
          number={1}
          title="Connect Facebook"
          state={pages.length ? "done" : "now"}
        >
          <p>
            {pages.length
              ? `${pages.length} Page${pages.length === 1 ? "" : "s"} shared with Sales X-Ray. Add more the same way.`
              : "Sign in with Facebook and tick every Page your lead ads run on."}
          </p>
          {app.connect ? (
            <div className={styles.row}>
              <Button
                variant={pages.length ? "ghost" : "primary"}
                onClick={onConnect}
              >
                {pages.length ? (
                  <Plus size={15} aria-hidden="true" />
                ) : (
                  <PlugZap size={15} aria-hidden="true" />
                )}
                {pages.length ? "Add a Page" : "Connect Facebook"}
              </Button>
            </div>
          ) : null}
        </Step>
        <Step
          number={2}
          title="Turn on a Page and pick its forms"
          state={on.length ? "done" : pages.length ? "now" : "later"}
        >
          {pages.length ? (
            <ul className={styles.pages} aria-label="Facebook Pages">
              {pages.map((page) => (
                <PageRow
                  key={page.pageId}
                  page={page}
                  line={lineOf(page)}
                  picking={picking === page.pageId}
                  onPick={() => setPicking(page.pageId)}
                  onCancel={() => setPicking(null)}
                  onSaved={changed}
                  onSwitchOff={switchOff}
                />
              ))}
            </ul>
          ) : (
            <p>Your Pages show here once Facebook is connected.</p>
          )}
        </Step>
        <Step
          number={3}
          title="Send a test lead"
          state={passed ? "done" : on.length ? "now" : "later"}
        >
          <p>
            Meta makes a sample lead on your form. It lands in Leads marked as a
            test and stays out of your reports.
          </p>
          {on.length ? test : null}
        </Step>
      </ol>
      {on.length ? (
        <section className={styles.status} aria-label="What’s coming in">
          <h3>What’s coming in</h3>
          <dl className={styles.facts}>
            <div>
              <dt>Last lead</dt>
              <dd>{app.lastEvent ? ago(app.lastEvent.at) : "None yet"}</dd>
            </div>
            <div>
              <dt>Leads so far</dt>
              <dd>{read ? leads(received) : "—"}</dd>
            </div>
            <div>
              <dt>Next check</dt>
              <dd>{ago(app.nextPullAt) ?? "Every 10 minutes"}</dd>
            </div>
          </dl>
          {app.lastError ? (
            <p className={styles.problem}>{app.lastError.words}</p>
          ) : null}
          {accessProblem ? <LeadAccessHelp /> : null}
          <div className={styles.row}>
            <Button
              variant="ghost"
              disabled={checking}
              onClick={() => void checkNow()}
            >
              <RefreshCw
                size={15}
                aria-hidden="true"
                className={checking ? styles.spin : undefined}
              />
              {checking ? "Checking…" : "Check for new leads now"}
            </Button>
          </div>
        </section>
      ) : null}
    </div>
  );
}
