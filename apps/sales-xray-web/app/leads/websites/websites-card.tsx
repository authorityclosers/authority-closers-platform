"use client";

/**
 * Websites and landing pages (owner, 30 Oct 2026: "connecting websites matters a lot to
 * customers… today's way of adding websites and landing pages is a frustrating
 * experience"). For owners and admins, on Leads → Sources: one card that says how many
 * sites are live, and one action, Add website.
 *
 * Add website is one sheet: copy the line, paste it where the site's builder takes it (or
 * email it to whoever runs the site), open the site, and the sheet says "We saw your
 * site at 10:42" by itself. Each site opens its own sheet with its pages: visits, lead
 * forms, leads and how many visits filled a form, plus Send test lead, Pause and Remove.
 */

import {
  Check,
  Copy,
  ExternalLink,
  Globe,
  Mail,
  Pause,
  Play,
  RefreshCw,
  Send,
  Trash2,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { notify } from "../../notice-center";
import { Button } from "../../ui/kit";
import { Sheet } from "../../ui/sheet";
import { AppCard, AppCardSkeleton, AppLogo, StatusPill } from "../app-card";
import { LeadsError } from "../leads-client";
import {
  addWebsite,
  emailForWebPerson,
  newWebsiteKey,
  PASTE_STEPS,
  percent,
  PLATFORM_NAMES,
  readWebsites,
  removeWebsite,
  seenAt,
  sendWebsiteTestLead,
  setWebsiteStatus,
  siteLine,
  startWebsites,
  type Website,
  type Websites,
} from "./websites-client";
import styles from "./websites.module.css";

const POLL_MS = 3000;
const TITLE = "Websites and landing pages";

function trouble(id: string, title: string, reason: unknown) {
  notify({
    id,
    tone: "error",
    title,
    message:
      reason instanceof LeadsError
        ? reason.message
        : "Sales X-Ray isn't answering. Try again.",
  });
}

function plural(count: number, one: string, many: string): string {
  return `${count.toLocaleString("en-IN")} ${count === 1 ? one : many}`;
}

/** A site's address as typed ("fictionalclinic.in/offer") to open it with the check. */
export function checkAddress(typed: string): string | null {
  const text = typed.trim();
  if (!text) return null;
  try {
    const url = new URL(/^https?:\/\//i.test(text) ? text : `https://${text}`);
    if (!url.hostname.includes(".") && url.hostname !== "localhost")
      return null;
    url.searchParams.set("sx_check", "1");
    return url.toString();
  } catch {
    return null;
  }
}

function CopyChip({
  value,
  label = "Copy line",
  primary,
}: {
  value: string;
  label?: string;
  primary?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const copy = () =>
    navigator.clipboard
      .writeText(value)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1800);
      })
      .catch(() =>
        notify({
          id: "website-copy",
          tone: "info",
          title: "Copy didn't work here",
          message: "Press and hold the line to select it, then copy.",
        }),
      );
  return (
    <Button
      variant={primary ? "primary" : "secondary"}
      className={primary ? styles.wide : styles.chip}
      onClick={() => void copy()}
    >
      {copied ? (
        <Check size={15} aria-hidden="true" />
      ) : (
        <Copy size={15} aria-hidden="true" />
      )}
      {copied ? "Copied" : label}
    </Button>
  );
}

function Step({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className={styles.step} aria-label={title}>
      <h4 className={styles.stepHead}>
        <span className={styles.stepNumber} aria-hidden="true">
          {n}
        </span>
        {title}
      </h4>
      {children}
    </section>
  );
}

/** The newest site seen since ``since``: the sheet's "We saw your site". */
export function seenSince(
  sites: Website[],
  since: number,
): Website | undefined {
  return sites
    .filter(
      (site) =>
        site.last_seen_at && new Date(site.last_seen_at).getTime() >= since,
    )
    .sort(
      (a, b) =>
        new Date(b.last_seen_at ?? 0).getTime() -
        new Date(a.last_seen_at ?? 0).getTime(),
    )[0];
}

function AddSheet({
  since,
  data,
  onData,
  poll,
  onClose,
}: {
  /** When it opened, less a minute (a line pasted a moment ago counts); null: closed. */
  since: number | null;
  data: Websites;
  onData: (next: Websites) => void;
  /** Reads the card again; an answer older than the last change is dropped. */
  poll: () => Promise<void>;
  onClose: () => void;
}) {
  const [builder, setBuilder] = useState(PASTE_STEPS[0].id);
  const [address, setAddress] = useState("");
  const [busy, setBusy] = useState(false);
  const [renewing, setRenewing] = useState(false);
  const open = since !== null;
  useEffect(() => {
    if (!open) return;
    const timer = setInterval(() => {
      poll().catch(() => undefined); // the next read tries again
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [open, poll]);

  const seen = since === null ? undefined : seenSince(data.sites, since);
  const steps =
    PASTE_STEPS.find((item) => item.id === builder) ?? PASTE_STEPS[0];
  const snippet = data.snippet ?? "";
  const target = checkAddress(address);

  const openSite = async () => {
    if (!target) return;
    // Opened at once, inside the tap, so no pop-up blocker stops it.
    window.open(target, "_blank", "noopener");
    setBusy(true);
    try {
      onData(await addWebsite(new URL(target).hostname));
    } catch (reason) {
      trouble("website-add", "The site wasn't added", reason);
    } finally {
      setBusy(false);
    }
  };

  const renew = async () => {
    setBusy(true);
    try {
      onData(await newWebsiteKey());
      setRenewing(false);
      notify({
        id: "website-key",
        tone: "success",
        title: "New line made. Paste it on your sites again.",
        timeout: 5000,
      });
    } catch (reason) {
      trouble("website-key", "The line wasn't changed", reason);
    } finally {
      setBusy(false);
    }
  };

  const live = (
    <div
      className={styles.live}
      data-seen={seen ? "" : undefined}
      role="status"
      aria-live="polite"
    >
      {seen ? (
        <>
          <Check size={18} aria-hidden="true" />
          <span>
            <strong>
              We saw {seen.host} at{" "}
              {seenAt(seen.last_seen_at ?? data.now, new Date(data.now))}
            </strong>
            <small>
              {seen.forms
                ? `${plural(seen.forms, "lead form", "lead forms")} found. Its enquiries now come to Leads.`
                : "No lead form on that page. Open the page with your form."}
            </small>
          </span>
        </>
      ) : (
        <>
          <span className={styles.dot} aria-hidden="true" />
          <span>
            <strong>Waiting for your site…</strong>
            <small>Open any page with the line. This updates by itself.</small>
          </span>
        </>
      )}
    </div>
  );

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Add your website"
      description="Every form on it becomes a lead, with the page and the ad it came from."
      lead={<AppLogo icon={Globe} size={36} />}
      className={styles.sheet}
      footer={
        seen ? (
          <Button variant="primary" className={styles.wide} onClick={onClose}>
            <Check size={16} aria-hidden="true" />
            Done
          </Button>
        ) : (
          <CopyChip value={snippet} primary />
        )
      }
    >
      <div className={styles.flow}>
        {/* Once the site said hello, that comes first: it's what the owner waits for. */}
        {seen ? live : null}
        <Step n={1} title="Copy this line">
          <pre className={styles.code} data-sheet-no-drag>
            <code>{snippet}</code>
          </pre>
          <div className={styles.chips}>
            <a className={styles.chip} href={emailForWebPerson(snippet)}>
              <Mail size={15} aria-hidden="true" />
              Email it to your web person
            </a>
          </div>
        </Step>

        <Step n={2} title="Paste it on your site">
          <div
            className={styles.builders}
            role="radiogroup"
            aria-label="Your site's builder"
          >
            {PASTE_STEPS.map((item) => (
              <button
                key={item.id}
                type="button"
                role="radio"
                aria-checked={builder === item.id}
                className={styles.builder}
                onClick={() => setBuilder(item.id)}
              >
                {item.name}
              </button>
            ))}
          </div>
          <ol className={styles.howto}>
            {steps.steps.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ol>
        </Step>

        <Step n={3} title="Open your site">
          <div className={styles.openRow}>
            <input
              className={styles.input}
              value={address}
              inputMode="url"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              enterKeyHint="go"
              placeholder="yourbusiness.com"
              aria-label="Your site's address"
              maxLength={300}
              onChange={(event) => setAddress(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void openSite();
              }}
            />
            <Button
              className={styles.chip}
              disabled={!target || busy}
              onClick={() => void openSite()}
            >
              <ExternalLink size={15} aria-hidden="true" />
              Open site
            </Button>
          </div>
          {seen ? null : live}
        </Step>

        {renewing ? (
          <div className={styles.confirm} role="group" aria-label="New line">
            <p>
              The old line stops at once on every site. Paste the new one
              everywhere.
            </p>
            <div className={styles.chips}>
              <Button
                className={styles.chip}
                onClick={() => setRenewing(false)}
              >
                Keep this line
              </Button>
              <Button
                className={styles.chip}
                data-danger=""
                disabled={busy}
                onClick={() => void renew()}
              >
                <RefreshCw size={15} aria-hidden="true" />
                Make a new line
              </Button>
            </div>
          </div>
        ) : data.sites.length ? (
          <button
            type="button"
            className={styles.quiet}
            onClick={() => setRenewing(true)}
          >
            Someone else has your line? Make a new one
          </button>
        ) : null}
      </div>
    </Sheet>
  );
}

function SiteSheet({
  site,
  now,
  onData,
  onClose,
}: {
  site: Website | null;
  now: Date;
  onData: (next: Websites) => void;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  // Which site's Remove is being confirmed: another site opens without it.
  const [removingId, setRemovingId] = useState<string | null>(null);
  // The site stays drawn while its sheet slides away.
  const [shown, setShown] = useState<Website | null>(site);
  if (site && site !== shown) setShown(site);
  const current = site ?? shown;
  if (!current) return null;
  const removing = removingId === current.site_id;
  const setRemoving = (on: boolean) =>
    setRemovingId(on ? current.site_id : null);

  const act = async (work: () => Promise<void>, title: string) => {
    setBusy(true);
    try {
      await work();
    } catch (reason) {
      trouble("website-site", title, reason);
    } finally {
      setBusy(false);
    }
  };

  const paused = current.status === "paused";
  return (
    <Sheet
      open={!!site}
      onClose={onClose}
      title={current.host}
      description={siteLine(current, now)}
      lead={<AppLogo icon={Globe} size={36} />}
      className={styles.sheet}
    >
      <div className={styles.flow}>
        <div className={styles.stats} aria-label="Last 30 days">
          <div className={styles.stat}>
            <strong>{current.views.toLocaleString("en-IN")}</strong>
            <span>Visits</span>
          </div>
          <div className={styles.stat}>
            <strong>{current.leads.toLocaleString("en-IN")}</strong>
            <span>New leads</span>
          </div>
          <div className={styles.stat}>
            <strong>{percent(current.rate)}</strong>
            <span>Filled a form</span>
          </div>
        </div>
        <p className={styles.hint}>
          Last 30 days
          {current.platform && PLATFORM_NAMES[current.platform]
            ? ` · built with ${PLATFORM_NAMES[current.platform]}`
            : ""}
          {current.blocked
            ? ` · ${plural(current.blocked, "bot fill", "bot fills")} turned away`
            : ""}
          {current.test ? " · a test address: its leads are test data" : ""}
        </p>

        <section aria-label="Pages">
          <h4 className={styles.listHead}>Pages</h4>
          {current.pages.length ? (
            <ul className={styles.pages}>
              {current.pages.map((page) => (
                <li key={page.path} className={styles.page}>
                  <span className={styles.pageText}>
                    <strong>{page.title || page.path}</strong>
                    <small>
                      {page.title ? `${page.path} · ` : ""}
                      {plural(page.views, "visit", "visits")} ·{" "}
                      {page.forms
                        ? plural(page.forms, "form", "forms")
                        : "no form"}
                    </small>
                  </span>
                  <span className={styles.pageNumbers}>
                    <strong>{plural(page.leads, "lead", "leads")}</strong>
                    <small>{percent(page.rate)}</small>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.empty}>
              No visits counted yet. Open a page of this site with the line on
              it.
            </p>
          )}
        </section>

        <div className={styles.chips}>
          <Button
            className={styles.chip}
            disabled={busy || paused}
            onClick={() =>
              void act(async () => {
                await sendWebsiteTestLead(current.site_id);
                notify({
                  id: "website-test",
                  tone: "success",
                  title: "Test lead sent. It's under Leads → Test leads.",
                  timeout: 5000,
                });
              }, "The test lead wasn't sent")
            }
          >
            <Send size={15} aria-hidden="true" />
            Send test lead
          </Button>
          <a
            className={styles.chip}
            href={`https://${current.host}/?sx_check=1`}
            target="_blank"
            rel="noopener noreferrer"
          >
            <ExternalLink size={15} aria-hidden="true" />
            Open site
          </a>
          <Button
            className={styles.chip}
            disabled={busy}
            onClick={() =>
              void act(
                async () =>
                  onData(
                    await setWebsiteStatus(
                      current.site_id,
                      paused ? "active" : "paused",
                    ),
                  ),
                paused ? "The site wasn't resumed" : "The site wasn't paused",
              )
            }
          >
            {paused ? (
              <Play size={15} aria-hidden="true" />
            ) : (
              <Pause size={15} aria-hidden="true" />
            )}
            {paused ? "Resume" : "Pause"}
          </Button>
        </div>

        {removing ? (
          <div className={styles.confirm} role="group" aria-label="Remove site">
            <p>
              Remove {current.host}? Its forms stop adding leads. Leads already
              here stay.
            </p>
            <div className={styles.chips}>
              <Button
                className={styles.chip}
                onClick={() => setRemoving(false)}
              >
                Keep it
              </Button>
              <Button
                className={styles.chip}
                data-danger=""
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    onData(await removeWebsite(current.site_id));
                    onClose();
                  }, "The site wasn't removed")
                }
              >
                <Trash2 size={15} aria-hidden="true" />
                Remove
              </Button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            className={styles.quietDanger}
            onClick={() => setRemoving(true)}
          >
            <Trash2 size={14} aria-hidden="true" />
            Remove this site
          </button>
        )}
      </div>
    </Sheet>
  );
}

function SiteRow({
  site,
  now,
  onOpen,
}: {
  site: Website;
  now: Date;
  onOpen: () => void;
}) {
  const tone =
    site.status === "paused" ? "off" : site.last_seen_at ? "live" : "waiting";
  return (
    <li>
      <button type="button" className={styles.site} onClick={onOpen}>
        <span className={styles.siteIcon} data-tone={tone} aria-hidden="true">
          <Globe size={18} />
        </span>
        <span className={styles.siteText}>
          <strong>{site.host}</strong>
          <small>{siteLine(site, now)}</small>
        </span>
        <span className={styles.siteNumbers}>
          <strong>{plural(site.leads, "lead", "leads")}</strong>
          <small>{percent(site.rate)} filled</small>
        </span>
      </button>
    </li>
  );
}

export function WebsitesCard({
  openAdd = null,
  openSite = null,
}: {
  /** Review fixtures only: Add website open, counting sites seen since then. */
  openAdd?: number | null;
  /** Review fixtures only: this site's sheet open. */
  openSite?: string | null;
} = {}) {
  const [data, setData] = useState<Websites | null>(null);
  // "error": the read failed (try again); "hidden": not an owner or admin here.
  const [failed, setFailed] = useState<false | "error" | "hidden">(false);
  const [addingSince, setAddingSince] = useState<number | null>(openAdd);
  const [openId, setOpenId] = useState<string | null>(openSite);
  const [busy, setBusy] = useState(false);
  // Counts changes made here: a read that began before one would bring back what it
  // replaced (a line just renewed), so it is dropped.
  const changes = useRef(0);
  const change = useCallback((next: Websites) => {
    changes.current += 1;
    setData(next);
  }, []);
  const poll = useCallback(() => {
    const at = changes.current;
    return readWebsites().then((next) => {
      if (changes.current === at) setData(next);
    });
  }, []);

  const load = useCallback(
    () =>
      readWebsites()
        .then((next) => {
          setData(next);
          setFailed(false);
        })
        .catch((reason) => {
          if (reason instanceof LeadsError && reason.status === 403) {
            setFailed("hidden");
            return;
          }
          setFailed("error");
          trouble("websites-read", "Websites didn't load", reason);
        }),
    [],
  );
  useEffect(() => {
    void load();
  }, [load]);

  const add = async () => {
    if (!data) return;
    const since = Date.now() - 60_000;
    if (data.key) {
      setAddingSince(since);
      return;
    }
    setBusy(true);
    try {
      change(await startWebsites());
      setAddingSince(since);
    } catch (reason) {
      trouble("websites-start", "Your website line wasn't made", reason);
    } finally {
      setBusy(false);
    }
  };

  const logo = <AppLogo icon={Globe} />;
  if (!data) {
    if (failed === "hidden") return null;
    if (!failed) return <AppCardSkeleton title={TITLE} logo={logo} />;
    return (
      <AppCard
        logo={logo}
        title={TITLE}
        summary="Websites didn't load."
        action={
          <Button onClick={() => void load()}>
            <RefreshCw size={15} aria-hidden="true" />
            Try again
          </Button>
        }
      />
    );
  }

  const now = new Date(data.now);
  const live = data.sites.filter(
    (site) => site.status === "active" && site.last_seen_at,
  ).length;
  const status = live ? (
    <StatusPill tone="good">{live} live</StatusPill>
  ) : data.sites.length ? (
    <StatusPill tone="warn">Waiting</StatusPill>
  ) : (
    <StatusPill>Not connected</StatusPill>
  );
  const open = data.sites.find((site) => site.site_id === openId) ?? null;

  return (
    <div data-brand="website">
      <AppCard
        logo={logo}
        title={TITLE}
        status={status}
        summary="Every form on your site becomes a lead, with the page and the ad it came from."
        action={
          <Button variant="primary" disabled={busy} onClick={() => void add()}>
            Add website
          </Button>
        }
      >
        {data.sites.length ? (
          <>
            <ul className={styles.sites} aria-label="Your websites">
              {data.sites.map((site) => (
                <SiteRow
                  key={site.site_id}
                  site={site}
                  now={now}
                  onOpen={() => setOpenId(site.site_id)}
                />
              ))}
            </ul>
            <p className={styles.hint}>
              Last {data.period_days} days:{" "}
              {plural(data.views, "visit", "visits")} ·{" "}
              {plural(data.leads, "new lead", "new leads")} ·{" "}
              {percent(data.rate)} filled a form
            </p>
          </>
        ) : null}
      </AppCard>
      <AddSheet
        since={addingSince}
        data={data}
        onData={change}
        poll={poll}
        onClose={() => setAddingSince(null)}
      />
      <SiteSheet
        site={open}
        now={now}
        onData={change}
        onClose={() => setOpenId(null)}
      />
    </div>
  );
}
