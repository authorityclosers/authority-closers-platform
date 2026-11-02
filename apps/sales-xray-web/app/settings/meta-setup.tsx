"use client";

/**
 * Settings -> Connected apps -> Facebook and Instagram lead ads, as one guided
 * setup (owner, 22 Oct 2026: "massive update to Meta connect and review UX"):
 * connect Facebook, then choose the Pages that bring leads in Leads setup ->
 * Sources, the one place for Pages, forms and older leads (owner, 2 Nov 2026),
 * and, if wanted, send a test lead; then see what comes in. The test lead
 * never holds anything up. Above the steps, where Meta's review of Sales Xray stands
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
import { useEffect, useState, type ReactNode } from "react";

import { notify } from "../notice-center";
import { Button } from "../ui/kit";
import {
  ago,
  AppsError,
  checkPage,
  readMetaPages,
  type AppHealth,
  type Blocker,
  type MetaPage,
  type MetaRun,
  type Review,
} from "./connected-apps-client";
import styles from "./meta-setup.module.css";

type StepState = "done" | "now" | "later";

const failed = (error: unknown) =>
  error instanceof AppsError
    ? error.message
    : "Check your connection and try again.";

const leads = (count: number) => `${count} lead${count === 1 ? "" : "s"}`;

/** Where a Page's older leads have got to: what was read, new, and already here. */
export function runWords(run: MetaRun | null | undefined): string | null {
  if (!run) return null;
  if (run.state === "blocked")
    return "Older leads stopped: see the Page's problem";
  const found = `${leads(run.seen)} read: ${run.created} new, ${run.here} already in your leads`;
  return run.state === "running"
    ? `Bringing in older leads… ${found} so far`
    : run.seen
      ? `Older leads, last 90 days: ${found}`
      : "Older leads: Meta has none from the last 90 days";
}

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
  const on = pages.filter((page) => page.active);
  const received = on.reduce((sum, page) => sum + page.received, 0);
  const accessProblem = on.some((page) => page.problem?.kind === "lead_access");

  const changed = () => onChanged();

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
        {/* Pages, forms and older leads are managed in one place, Leads setup →
            Sources (owner, 2 Nov 2026); older leads only if asked, none by default. */}
        <Step
          number={2}
          title="Choose the Pages that bring leads"
          state={on.length ? "done" : pages.length ? "now" : "later"}
        >
          <p>
            {on.length
              ? `${on.length} Page${on.length === 1 ? "" : "s"} bringing leads. New leads come in from when each was turned on.`
              : "Turn on Pages and pick their forms in Leads setup → Sources."}
          </p>
          {pages.length ? (
            <div className={styles.row}>
              <Link
                className={styles.reviewFix}
                href="/organisation?tab=leads&part=sources"
              >
                Open Leads setup → Sources
              </Link>
            </div>
          ) : null}
        </Step>
        <Step
          number={3}
          title="Send a test lead (optional)"
          state={passed ? "done" : "later"}
        >
          <p>
            Meta makes a sample lead on your form. It lands in Leads marked as a
            test and stays out of your reports. If the test doesn’t pass, your
            leads still come in: nothing waits for it.
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
