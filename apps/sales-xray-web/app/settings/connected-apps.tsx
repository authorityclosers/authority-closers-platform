"use client";

/**
 * Settings -> Connected apps (owner, 20 Oct): "one clean grid. Each app is one
 * card with a logo, a one-line status, one primary action (Connect / Manage),
 * and a Test button with the result inline. No long forms on the page; details
 * open in a sheet." Health and tests come from /v1/lead-desk/integrations
 * (connected-apps-client.ts); sign-in providers from /v1/me/sign-in-methods.
 */
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  CheckCircle2,
  Loader2,
  Lock,
  PhoneCall,
  PlugZap,
  RefreshCw,
  Sparkles,
  Webhook,
  X,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import { notify } from "../notice-center";
import { IntegrationsPanel } from "../organisation/integrations/integrations-panel";
import { goToProvider } from "../sign-in-connect";
import { parseSignInMethods, type ConnectOption } from "../sign-in-methods";
import { Badge, Button, Empty, Skeleton, type Tone } from "../ui/kit";
import { BrandTile } from "../ui/brand-tile";
import {
  AppsError,
  disconnect,
  followTest,
  readForms,
  readHealth,
  startTest,
  type AppHealth,
  type AppKey,
  type AppState,
  type Connection,
  type MetaForm,
  type TestOffer,
  type TestResult,
} from "./connected-apps-client";
import { Sheet } from "./sheet";
import styles from "./connected-apps.module.css";

const LOGOS: Record<AppKey, { brands?: string[]; icon?: LucideIcon }> = {
  meta_leads: { brands: ["facebook", "instagram"] },
  whatsapp: { brands: ["whatsapp"] },
  messenger: { brands: ["messenger"] },
  instagram: { brands: ["instagram"] },
  google_ads: { brands: ["googleads"] },
  phone_calls: { icon: PhoneCall },
  webhook_sources: { icon: Webhook },
  ai_replies: { icon: Sparkles },
};

const STATUS: Record<AppState, { label: string; tone: Tone }> = {
  ready: { label: "Connected", tone: "good" },
  problem: { label: "Needs attention", tone: "warn" },
  not_connected: { label: "Not connected", tone: "neutral" },
  not_set_up: { label: "Not available here", tone: "neutral" },
  off: { label: "Off", tone: "neutral" },
};

// Where an app's full settings live, for what the sheet doesn't hold itself.
const MORE: Partial<Record<AppKey, { href: string; label: string }>> = {
  meta_leads: { href: "/leads?tab=sources", label: "Forms and lead sources" },
  google_ads: { href: "/leads?tab=sources", label: "Forms and lead sources" },
  webhook_sources: { href: "/leads?tab=sources", label: "Webhooks and sheets" },
  phone_calls: {
    href: "/settings/devices",
    label: "Phone app and call recording",
  },
  ai_replies: { href: "/settings/ai-replies", label: "AI replies settings" },
};

const NEED_LABELS: Record<string, string> = {
  pageId: "Page",
  formId: "Form",
  to: "Send the test to",
  message: "A message a lead might send",
};

const POLL_MS = 2000;
const POLL_LIMIT = 45;

function ago(value: string | null): string | null {
  if (!value) return null;
  const at = new Date(value).getTime();
  if (Number.isNaN(at)) return null;
  const seconds = Math.round((Date.now() - at) / 1000);
  const ahead = seconds < 0;
  const size = Math.abs(seconds);
  const words =
    size < 60
      ? "a moment"
      : size < 3600
        ? `${Math.round(size / 60)} min`
        : size < 86_400
          ? `${Math.round(size / 3600)} h`
          : `${Math.round(size / 86_400)} d`;
  if (size < 60) return ahead ? "in a moment" : "just now";
  return ahead ? `in ${words}` : `${words} ago`;
}

type Loaded =
  | { state: "loading" }
  | { state: "failed"; message: string }
  | { state: "members" }
  | { state: "ready"; apps: AppHealth[]; checkedAt: string | null };
type Running = TestResult & { polls?: number };
type SheetState = {
  app: AppKey;
  mode: "manage" | "test";
  offer?: TestOffer;
} | null;

/** How a test went, inside its card (or the sheet), as it happens. */
function Outcome({
  result,
  onDismiss,
}: {
  result: Running;
  onDismiss?: () => void;
}) {
  const Icon =
    result.status === "waiting"
      ? Loader2
      : result.status === "passed"
        ? CheckCircle2
        : XCircle;
  return (
    <div
      className={styles.outcome}
      data-status={result.status}
      role="status"
      aria-live="polite"
    >
      <Icon size={18} aria-hidden="true" className={styles.outcomeIcon} />
      <div className={styles.outcomeText}>
        <strong>
          {result.status === "waiting"
            ? "Testing…"
            : result.status === "passed"
              ? "Test passed"
              : "Test didn’t pass"}
        </strong>
        {result.words ? <span>{result.words}</span> : null}
        {result.draft ? <q className={styles.draft}>{result.draft}</q> : null}
        {result.steps.length ? (
          <ol className={styles.steps}>
            {result.steps.map((step) => (
              <li key={step.label} data-state={step.state}>
                <span aria-hidden="true" />
                {step.label}
                {step.words ? <em> · {step.words}</em> : null}
              </li>
            ))}
          </ol>
        ) : null}
      </div>
      {onDismiss && result.status !== "waiting" ? (
        <button
          type="button"
          className={styles.dismiss}
          aria-label="Hide the result"
          onClick={onDismiss}
        >
          <X size={14} aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}

function AppCard({
  app,
  result,
  onManage,
  onTest,
  onDismiss,
}: {
  app: AppHealth;
  result: Running | undefined;
  onManage: () => void;
  onTest: (offer: TestOffer) => void;
  onDismiss: () => void;
}) {
  const titleId = useId();
  const status = STATUS[app.state];
  const offer = app.tests[0];
  const connected = app.state === "ready" || app.state === "problem";
  return (
    <article
      className={styles.card}
      data-app={app.app}
      data-state={app.state}
      aria-labelledby={titleId}
    >
      <div className={styles.cardHead}>
        <BrandTile {...LOGOS[app.app]} size={44} />
        <div className={styles.cardTitle}>
          <h3 id={titleId}>{app.name}</h3>
          <Badge tone={status.tone}>{status.label}</Badge>
        </div>
      </div>
      <p className={styles.words}>
        {app.state === "problem" && app.lastError
          ? app.lastError.words
          : app.words}
      </p>
      <div className={styles.actions}>
        {app.state === "not_set_up" ? null : !connected &&
          app.connect &&
          app.state !== "off" ? (
          <Button
            variant="primary"
            onClick={() => goToProvider(app.connect!.path)}
          >
            <PlugZap size={15} aria-hidden="true" />
            Connect
          </Button>
        ) : (
          <Button
            variant={connected ? "secondary" : "primary"}
            onClick={onManage}
          >
            Manage
          </Button>
        )}
        {offer ? (
          <Button
            variant="ghost"
            disabled={result?.status === "waiting"}
            onClick={() => onTest(offer)}
          >
            {result?.status === "waiting" ? "Testing…" : offer.label}
          </Button>
        ) : null}
      </div>
      {result ? <Outcome result={result} onDismiss={onDismiss} /> : null}
    </article>
  );
}

function SignInCard({ option }: { option: ConnectOption }) {
  const titleId = useId();
  return (
    <article
      className={styles.card}
      data-app={`sign-in-${option.kind}`}
      aria-labelledby={titleId}
    >
      <div className={styles.cardHead}>
        <BrandTile brands={[option.kind]} size={44} />
        <div className={styles.cardTitle}>
          <h3 id={titleId}>{option.label} sign-in</h3>
          <Badge tone={option.connected ? "good" : "neutral"}>
            {option.connected ? "Connected" : "Not connected"}
          </Badge>
        </div>
      </div>
      <p className={styles.words}>
        {option.connected
          ? `You can sign in to Sales Xray with ${option.label}.`
          : `Sign in to Sales Xray with your ${option.label} account too.`}
      </p>
      <div className={styles.actions}>
        <Link
          href="/settings/security"
          className={styles.linkButton}
          data-variant={option.connected ? "secondary" : "primary"}
        >
          {option.connected ? "Manage" : "Connect"}
        </Link>
      </div>
    </article>
  );
}

function CardSkeleton() {
  return (
    <div className={styles.card} aria-hidden="true">
      <div className={styles.cardHead}>
        <Skeleton width={44} height={44} />
        <div className={styles.cardTitle}>
          <Skeleton width="62%" height={14} />
          <Skeleton width={84} height={20} />
        </div>
      </div>
      <p className={styles.words}>
        <Skeleton width="90%" height={11} />
      </p>
      <div className={styles.actions}>
        <Skeleton width={92} height={34} />
        <Skeleton width={110} height={34} />
      </div>
    </div>
  );
}

/** The fields a test needs before it runs (a Page and form, a number, a message). */
function TestForm({
  app,
  offer,
  running,
  onRun,
}: {
  app: AppHealth;
  offer: TestOffer;
  running: boolean;
  onRun: (body: Record<string, unknown>) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(() => ({
    pageId: app.connections.length === 1 ? app.connections[0].id : "",
    numberId: app.connections.length === 1 ? app.connections[0].id : "",
  }));
  const [agreed, setAgreed] = useState(false);
  const [forms, setForms] = useState<{
    page: string;
    items: MetaForm[] | null;
  }>({
    page: "",
    items: null,
  });
  const needsForm = offer.needs.includes("formId");
  const pageId = values.pageId ?? "";
  useEffect(() => {
    if (!needsForm || !pageId) return;
    const controller = new AbortController();
    readForms(pageId, controller.signal).then(
      (items) => setForms({ page: pageId, items }),
      () => {
        if (!controller.signal.aborted) setForms({ page: pageId, items: [] });
      },
    );
    return () => controller.abort();
  }, [needsForm, pageId]);
  const set = (key: string, value: string) =>
    setValues((current) => ({ ...current, [key]: value }));
  const ready =
    offer.needs.every((need) => (values[need] ?? "").trim()) &&
    (!offer.confirm || agreed);
  const body: Record<string, unknown> = {};
  for (const need of offer.needs) body[need] = (values[need] ?? "").trim();
  if (app.app === "whatsapp" && values.numberId)
    body.numberId = values.numberId;
  if (offer.confirm) Object.assign(body, { sendReply: true, confirm: true });
  return (
    <form
      className={styles.testForm}
      onSubmit={(event) => {
        event.preventDefault();
        if (ready && !running) onRun(body);
      }}
    >
      {offer.needs.includes("pageId") ? (
        <label className={styles.field}>
          <span>{NEED_LABELS.pageId}</span>
          <select
            value={pageId}
            onChange={(event) => set("pageId", event.target.value)}
          >
            <option value="">Choose a Page</option>
            {app.connections.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {needsForm ? (
        <label className={styles.field}>
          <span>{NEED_LABELS.formId}</span>
          <select
            value={values.formId ?? ""}
            disabled={!pageId || forms.page !== pageId}
            onChange={(event) => set("formId", event.target.value)}
          >
            <option value="">
              {!pageId
                ? "Choose a Page first"
                : forms.page !== pageId
                  ? "Loading the Page’s forms…"
                  : forms.items?.length
                    ? "Choose a form"
                    : "This Page has no lead forms"}
            </option>
            {forms.page === pageId
              ? forms.items?.map((form) => (
                  <option key={form.id} value={form.id}>
                    {form.name}
                  </option>
                ))
              : null}
          </select>
        </label>
      ) : null}
      {app.app === "whatsapp" && app.connections.length > 1 ? (
        <label className={styles.field}>
          <span>Send from</span>
          <select
            value={values.numberId ?? ""}
            onChange={(event) => set("numberId", event.target.value)}
          >
            {app.connections.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {offer.needs.includes("to") ? (
        <label className={styles.field}>
          <span>{NEED_LABELS.to}</span>
          <input
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            placeholder="+91 98765 43210"
            value={values.to ?? ""}
            onChange={(event) => set("to", event.target.value)}
          />
          <small>Meta&rsquo;s hello_world message goes to this number.</small>
        </label>
      ) : null}
      {offer.needs.includes("message") ? (
        <label className={styles.field}>
          <span>{NEED_LABELS.message}</span>
          <textarea
            rows={3}
            maxLength={500}
            placeholder="Hi, what does the course cost and when does it start?"
            value={values.message ?? ""}
            onChange={(event) => set("message", event.target.value)}
          />
          <small>Nothing is sent: you see the reply it would write.</small>
        </label>
      ) : null}
      {offer.confirm ? (
        <label className={styles.check}>
          <input
            type="checkbox"
            checked={agreed}
            onChange={(event) => setAgreed(event.target.checked)}
          />
          <span>Send a short test message into the latest conversation.</span>
        </label>
      ) : null}
      <div>
        <Button type="submit" variant="primary" disabled={!ready || running}>
          {running ? "Testing…" : offer.label}
        </Button>
      </div>
    </form>
  );
}

function ConnectionRow({
  item,
  onDisconnect,
}: {
  item: Connection;
  onDisconnect: (item: Connection) => Promise<void>;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <li className={styles.connection} data-state={item.state}>
      <div className={styles.connectionText}>
        <strong>{item.label}</strong>
        {item.detail || item.words ? (
          <span>{[item.detail, item.words].filter(Boolean).join(" · ")}</span>
        ) : null}
      </div>
      {item.disconnect ? (
        <Button
          variant="ghost"
          disabled={busy}
          onClick={async () => {
            if (!confirming) {
              setConfirming(true);
              return;
            }
            setBusy(true);
            await onDisconnect(item);
            setBusy(false);
            setConfirming(false);
          }}
        >
          {busy
            ? "Disconnecting…"
            : confirming
              ? `Disconnect ${item.label}?`
              : "Disconnect"}
        </Button>
      ) : null}
    </li>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={styles.fact}>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function ManageSheet({
  app,
  mode,
  offer,
  result,
  onClose,
  onRun,
  onDismiss,
  onChanged,
}: {
  app: AppHealth;
  mode: "manage" | "test";
  offer?: TestOffer;
  result: Running | undefined;
  onClose: () => void;
  onRun: (offer: TestOffer, body: Record<string, unknown>) => void;
  onDismiss: () => void;
  onChanged: () => void;
}) {
  const status = STATUS[app.state];
  const more = MORE[app.app];
  const offers =
    mode === "test" && offer
      ? [offer]
      : app.tests.filter((item) => item.needs.length || item.confirm);
  async function drop(item: Connection) {
    try {
      await disconnect(item.disconnect!);
      notify({
        id: `connected-app-${app.app}`,
        tone: "success",
        title: `${item.label} disconnected`,
        message: `${app.name} no longer reaches Sales Xray from it.`,
        timeout: 6000,
      });
      onChanged();
    } catch (error) {
      notify({
        id: `connected-app-${app.app}`,
        tone: "error",
        title: `${item.label} wasn’t disconnected`,
        message:
          error instanceof AppsError
            ? error.message
            : "Check your connection and try again.",
      });
    }
  }
  return (
    <Sheet
      open
      title={
        mode === "test" && offer ? `${offer.label} · ${app.name}` : app.name
      }
      lead={<BrandTile {...LOGOS[app.app]} size={36} />}
      onClose={onClose}
    >
      {mode === "manage" ? (
        <>
          <div className={styles.sheetStatus}>
            <Badge tone={status.tone}>{status.label}</Badge>
            <span>{app.words}</span>
          </div>
          {app.lastError ? (
            <p className={styles.problem}>
              {app.lastError.words}
              {ago(app.lastError.at) ? (
                <em> · {ago(app.lastError.at)}</em>
              ) : null}
            </p>
          ) : null}
          <dl className={styles.facts}>
            {app.lastEvent ? (
              <Fact label="Last activity">
                {app.lastEvent.words} · {ago(app.lastEvent.at)}
              </Fact>
            ) : null}
            {app.lastDeliveryAt ? (
              <Fact label="Last delivery">{ago(app.lastDeliveryAt)}</Fact>
            ) : null}
            {app.nextPullAt ? (
              <Fact label="Next check">{ago(app.nextPullAt)}</Fact>
            ) : null}
          </dl>
          {app.connections.length ? (
            <section className={styles.sheetPart} aria-label="Connected">
              <h3>Connected</h3>
              <ul className={styles.connections}>
                {app.connections.map((item) => (
                  <ConnectionRow
                    key={item.id}
                    item={item}
                    onDisconnect={drop}
                  />
                ))}
              </ul>
            </section>
          ) : null}
          {app.connect ? (
            <div>
              <Button onClick={() => goToProvider(app.connect!.path)}>
                <PlugZap size={15} aria-hidden="true" />
                {app.connections.length ? "Connect another" : "Connect"}
              </Button>
            </div>
          ) : null}
        </>
      ) : null}
      {offers.map((item) => (
        <section
          key={item.kind}
          className={styles.sheetPart}
          aria-label={item.label}
        >
          {mode === "manage" ? <h3>{item.label}</h3> : null}
          <TestForm
            app={app}
            offer={item}
            running={result?.status === "waiting"}
            onRun={(body) => onRun(item, body)}
          />
        </section>
      ))}
      {result && (mode === "test" || offers.length) ? (
        <Outcome result={result} onDismiss={onDismiss} />
      ) : null}
      {mode === "manage" && app.app === "whatsapp" ? (
        <section className={styles.sheetPart} aria-label="WhatsApp settings">
          <IntegrationsPanel parts={["whatsapp"]} />
        </section>
      ) : null}
      {mode === "manage" &&
      (app.app === "messenger" || app.app === "instagram") ? (
        <section
          className={styles.sheetPart}
          aria-label="Messenger and Instagram settings"
        >
          <IntegrationsPanel parts={["social"]} />
        </section>
      ) : null}
      {mode === "manage" && more ? (
        <Link href={more.href} className={styles.more}>
          {more.label} ›
        </Link>
      ) : null}
    </Sheet>
  );
}

export function ConnectedApps() {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [signIn, setSignIn] = useState<ConnectOption[]>([]);
  const [tests, setTests] = useState<Partial<Record<AppKey, Running>>>({});
  const [sheet, setSheet] = useState<SheetState>(null);
  const lastRead = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    readHealth(controller.signal).then(
      (health) => {
        lastRead.current = Date.now();
        setLoaded({
          state: "ready",
          apps: health.apps,
          checkedAt: health.checkedAt,
        });
        setRefreshing(false);
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setRefreshing(false);
        if (error instanceof AppsError && error.status === 403) {
          setLoaded({ state: "members" });
          return;
        }
        const message =
          error instanceof AppsError
            ? error.message
            : "Check your connection and try again.";
        notify({
          id: "connected-apps",
          tone: "error",
          title: "Connected apps didn’t load",
          message,
        });
        setLoaded((current) =>
          current.state === "ready" ? current : { state: "failed", message },
        );
      },
    );
    return () => controller.abort();
  }, [attempt]);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/v1/me/sign-in-methods", {
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
      headers: { accept: "application/json" },
    })
      .then(async (response) =>
        response.ok ? parseSignInMethods(await response.json()) : null,
      )
      .then(
        (parsed) => setSignIn(parsed?.available ?? []),
        () => undefined,
      );
    return () => controller.abort();
  }, []);

  // Back from Meta or Google, or another tab: read again (at most every 30 s).
  useEffect(() => {
    const again = () => {
      if (
        document.visibilityState === "visible" &&
        Date.now() - lastRead.current > 30_000
      )
        setAttempt((value) => value + 1);
    };
    window.addEventListener("focus", again);
    document.addEventListener("visibilitychange", again);
    return () => {
      window.removeEventListener("focus", again);
      document.removeEventListener("visibilitychange", again);
    };
  }, []);

  // Tests that take a while are asked about every 2 s until they finish.
  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    const controller = new AbortController();
    for (const [key, result] of Object.entries(tests) as [AppKey, Running][]) {
      if (result.status !== "waiting" || !result.testId) continue;
      timers.push(
        setTimeout(() => {
          const polls = (result.polls ?? 0) + 1;
          followTest(result.testId!, controller.signal).then(
            (next) =>
              setTests((current) => ({
                ...current,
                [key]:
                  next.status === "waiting" && polls >= POLL_LIMIT
                    ? {
                        ...next,
                        status: "failed",
                        testId: null,
                        words:
                          "This is taking longer than usual. Check again in a few minutes.",
                      }
                    : { ...next, polls },
              })),
            () => {
              if (controller.signal.aborted) return;
              setTests((current) => ({
                ...current,
                [key]: {
                  ...result,
                  status: "failed",
                  testId: null,
                  words: "We lost track of this test. Try it again.",
                },
              }));
            },
          );
        }, POLL_MS),
      );
    }
    return () => {
      controller.abort();
      timers.forEach(clearTimeout);
    };
  }, [tests]);

  const run = useCallback(
    async (app: AppKey, body: Record<string, unknown>) => {
      setTests((current) => ({
        ...current,
        [app]: { testId: null, status: "waiting", words: "", steps: [] },
      }));
      try {
        const result = await startTest(app, body);
        setTests((current) => ({ ...current, [app]: { ...result, polls: 0 } }));
      } catch (error) {
        setTests((current) => ({
          ...current,
          [app]: {
            testId: null,
            status: "failed",
            words:
              error instanceof AppsError
                ? error.message
                : "Check your connection and try again.",
            steps: [],
          },
        }));
      }
    },
    [],
  );

  const dismiss = (app: AppKey) =>
    setTests((current) => {
      const next = { ...current };
      delete next[app];
      return next;
    });

  if (loaded.state === "members")
    return (
      <Empty
        icon={Lock}
        title="Owners and admins connect apps"
        text="Ask an owner or admin of your organisation to connect lead ads, WhatsApp and the rest."
      />
    );

  const apps = loaded.state === "ready" ? loaded.apps : [];
  const connected = apps.filter(
    (app) => app.state === "ready" || app.state === "problem",
  ).length;
  const attention = apps.filter((app) => app.state === "problem").length;
  const open = sheet ? apps.find((app) => app.app === sheet.app) : undefined;

  return (
    <div className={styles.page}>
      <div className={styles.summary}>
        {loaded.state === "ready" ? (
          <p>
            <strong>{connected} connected</strong>
            {attention ? (
              <span data-tone="warn"> · {attention} need attention</span>
            ) : null}
            {ago(loaded.checkedAt) ? (
              <span> · checked {ago(loaded.checkedAt)}</span>
            ) : null}
          </p>
        ) : loaded.state === "failed" ? (
          <p>Your apps couldn’t be checked.</p>
        ) : (
          <Skeleton width={220} height={14} />
        )}
        <Button
          variant="ghost"
          disabled={loaded.state === "loading" || refreshing}
          onClick={() => {
            setRefreshing(true);
            setAttempt((value) => value + 1);
          }}
        >
          <RefreshCw
            size={15}
            aria-hidden="true"
            className={refreshing ? styles.spin : undefined}
          />
          {loaded.state === "failed" ? "Try again" : "Check again"}
        </Button>
      </div>
      <div className={styles.grid} aria-busy={loaded.state === "loading"}>
        {loaded.state === "loading"
          ? Array.from({ length: 8 }, (_, index) => (
              <CardSkeleton key={index} />
            ))
          : apps.map((app) => (
              <AppCard
                key={app.app}
                app={app}
                result={tests[app.app]}
                onManage={() => setSheet({ app: app.app, mode: "manage" })}
                onTest={(offer) =>
                  offer.needs.length || offer.confirm
                    ? setSheet({ app: app.app, mode: "test", offer })
                    : void run(app.app, {})
                }
                onDismiss={() => dismiss(app.app)}
              />
            ))}
        {loaded.state !== "loading"
          ? signIn.map((option) => (
              <SignInCard key={option.kind} option={option} />
            ))
          : null}
      </div>
      {open && sheet ? (
        <ManageSheet
          app={open}
          mode={sheet.mode}
          offer={sheet.offer}
          result={tests[open.app]}
          onClose={() => setSheet(null)}
          onRun={(_, body) => void run(open.app, body)}
          onDismiss={() => dismiss(open.app)}
          onChanged={() => setAttempt((value) => value + 1)}
        />
      ) : null}
    </div>
  );
}
