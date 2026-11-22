"use client";

/**
 * Outreach, "what the owner sent" (v1.95, owner 22 Nov 2026: "every message
 * we send is tracked, so we never feel spammy"; he wants to see what HE
 * sent). One hero with the period's words, the filters as pills (By,
 * Channel, Period, Replied, Past a limit), then By lead (each lead with what
 * it received) or By message. The filters live in the address. A seller's
 * view is their own: the By filter is locked to them.
 */
import {
  ChevronDown,
  Handshake,
  Lock,
  Mail,
  MessageCircle,
  MessageSquareText,
  MessagesSquare,
  Phone,
  Send,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { readTeam } from "../leads/leads-client";
import { PillSwitch } from "../organisation/family";
import family from "../organisation/family.module.css";
import { Skeleton } from "../ui/kit";
import {
  OutreachError,
  outreachSearch,
  readOutreach,
  readSenders,
  type OutreachLeadRow,
  type OutreachPage,
  type OutreachQuery,
  type TouchView,
} from "./outreach-client";
import {
  agoWords,
  CHANNEL_NAMES,
  pastLimit,
  statusWords,
  teamDay,
  whatWords,
  whenWords,
} from "./outreach-words";
import styles from "./outreach.module.css";

const ICONS: Record<string, ReactNode> = {
  whatsapp: <MessageCircle aria-hidden="true" />,
  sms: <MessageSquareText aria-hidden="true" />,
  email: <Mail aria-hidden="true" />,
  call: <Phone aria-hidden="true" />,
  messenger: <MessagesSquare aria-hidden="true" />,
  instagram: <MessagesSquare aria-hidden="true" />,
  in_person: <Handshake aria-hidden="true" />,
  other: <Send aria-hidden="true" />,
};

type Period = "today" | "week" | "month";

/** The filter the address says. */
export function queryFrom(search: URLSearchParams): OutreachQuery {
  const replied = search.get("replied");
  return {
    view: search.get("view") === "touches" ? "touches" : "leads",
    by: search.get("by"),
    channel: search.get("channel"),
    from: search.get("from"),
    to: search.get("to"),
    replied: replied === "replied" || replied === "no_reply" ? replied : "any",
    over: search.get("over") === "true",
  };
}

/** Which period pill a from/to pair is (none for a custom range). */
export function periodOf(
  query: OutreachQuery,
  now = Date.now(),
): Period | null {
  if (!query.from && !query.to) return "week";
  const today = teamDay(now);
  if (query.from === today && (query.to ?? today) === today) return "today";
  if (query.from === teamDay(now, 29) && (query.to ?? today) === today)
    return "month";
  if (query.from === teamDay(now, 6) && (query.to ?? today) === today)
    return "week";
  return null;
}

const periodRange = (period: Period, now = Date.now()) =>
  period === "today"
    ? { from: teamDay(now), to: teamDay(now) }
    : period === "month"
      ? { from: teamDay(now, 29), to: teamDay(now) }
      : { from: null, to: null };

function ChannelTile({ channel }: { channel: string }) {
  return (
    <span className={styles.channelTile} title={CHANNEL_NAMES[channel]}>
      {ICONS[channel] ?? ICONS.other}
    </span>
  );
}

function TouchChips({ touch }: { touch: TouchView }) {
  return (
    <>
      <span
        className={styles.chip}
        data-tone={touch.status === "failed" ? "red" : undefined}
      >
        {statusWords(touch.status)}
      </span>
      {touch.replied_at ? (
        <span className={styles.chip} data-tone="good">
          Replied
        </span>
      ) : null}
      {pastLimit(touch) ? (
        <span className={styles.chip} data-tone="amber">
          {touch.override_by_name
            ? `Sent anyway by ${touch.override_by_name}`
            : "Past a limit"}
        </span>
      ) : null}
      {!touch.counted && touch.initiated === "reply" ? (
        <span className={styles.chip}>Reply, not counted</span>
      ) : null}
    </>
  );
}

/** One touch as a compact line: channel, what, who and when, its state. */
function TouchLine({
  touch,
  withLead = false,
}: {
  touch: TouchView;
  withLead?: boolean;
}) {
  return (
    <li className={styles.touch}>
      <ChannelTile channel={touch.channel} />
      <span className={styles.touchText}>
        <span className={styles.touchWhat}>{whatWords(touch)}</span>
        <span className={styles.touchMeta}>
          {touch.by_name} · {whenWords(touch.sent_at)}
        </span>
        <span className={styles.chips}>
          <TouchChips touch={touch} />
          {withLead ? (
            <Link
              className={styles.leadLink}
              href={`/leads?lead=${encodeURIComponent(touch.lead_id)}`}
            >
              {touch.lead_name || "Open lead"}
            </Link>
          ) : null}
        </span>
      </span>
    </li>
  );
}

function LeadCard({ row }: { row: OutreachLeadRow }) {
  return (
    <li className={styles.lead}>
      <details className={styles.leadDetails}>
        <summary>
          <span className={styles.leadText}>
            <span className={styles.leadName}>{row.name}</span>
            <span className={styles.leadMeta}>
              {row.added_by_name ? `Added by ${row.added_by_name} · ` : ""}
              {row.touches} {row.touches === 1 ? "message" : "messages"} · last{" "}
              {agoWords(row.last_touch_at)}
            </span>
          </span>
          <span className={styles.leadEnd}>
            {row.replied ? (
              <span className={styles.chip} data-tone="good">
                Replied
              </span>
            ) : (
              <span className={styles.chip}>No reply</span>
            )}
            <ChevronDown className={styles.chevron} aria-hidden="true" />
          </span>
        </summary>
        <div className={styles.received}>
          <p className={styles.receivedTitle}>
            What {row.name.split(" ")[0]} received
          </p>
          {row.received.length ? (
            <ol className={styles.touches}>
              {row.received.map((touch) => (
                <TouchLine key={touch.touch_id} touch={touch} />
              ))}
            </ol>
          ) : (
            <p className={styles.quiet}>Nothing sent in this period.</p>
          )}
          <Link
            className={styles.openLead}
            href={`/leads?lead=${encodeURIComponent(row.lead_id)}`}
          >
            Open lead
          </Link>
        </div>
      </details>
    </li>
  );
}

type Option = { value: string; label: string };

/** A pill that is a native select: the phone's own picker, labelled. */
function SelectPill({
  label,
  value,
  options,
  onChange,
  locked,
}: {
  label: string;
  value: string;
  options: readonly Option[];
  onChange: (value: string) => void;
  locked?: string;
}) {
  if (locked)
    return (
      <span className={styles.selectPill} data-locked="">
        <Lock aria-hidden="true" />
        <span>
          {label}: {locked}
        </span>
      </span>
    );
  const shown = options.find((option) => option.value === value);
  return (
    <label
      className={styles.selectPill}
      data-set={value && value !== options[0]?.value ? "" : undefined}
    >
      <span>
        {label}: {shown?.label ?? options[0]?.label}
      </span>
      <ChevronDown aria-hidden="true" />
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

const CHANNEL_OPTIONS: readonly Option[] = [
  { value: "", label: "All" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "sms", label: "SMS" },
  { value: "email", label: "Email" },
  { value: "call", label: "Calls" },
];

const REPLIED_OPTIONS: readonly Option[] = [
  { value: "any", label: "Any" },
  { value: "replied", label: "Replied" },
  { value: "no_reply", label: "No reply" },
];

export function OutreachView() {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const query = useMemo(
    () => queryFrom(new URLSearchParams(search?.toString() ?? "")),
    [search],
  );
  // The answer for one address (and attempt): a new address shows loading
  // until its own answer comes, with no state set inside the effect.
  const [answer, setAnswer] = useState<{
    key: string;
    page: OutreachPage | null;
    error: string | null;
  } | null>(null);
  const [more, setMore] = useState<{
    key: string;
    leads: OutreachLeadRow[];
    touches: TouchView[];
    cursor: string | null;
  } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [people, setPeople] = useState<Option[]>([]);
  const [senders, setSenders] = useState<Option[]>([]);

  const key = `${outreachSearch(query).toString()}#${attempt}`;
  useEffect(() => {
    const control = new AbortController();
    readOutreach(query, control.signal).then(
      (next) => {
        if (!control.signal.aborted)
          setAnswer({ key, page: next, error: null });
      },
      (reason: unknown) => {
        if (control.signal.aborted) return;
        setAnswer({
          key,
          page: null,
          error:
            reason instanceof OutreachError
              ? reason.message
              : "Outreach didn't load.",
        });
      },
    );
    return () => control.abort();
    // The query is the address; `key` names it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const page = answer?.key === key ? answer.page : null;
  const error = answer?.key === key ? answer.error : null;
  const extra =
    more?.key === key
      ? more
      : { key, leads: [], touches: [], cursor: page?.next_cursor ?? null };

  const locked = page?.filter.locked_to_self === true;
  // The By choices: the team and the outside senders, for whoever sees them.
  useEffect(() => {
    if (!page || locked) return;
    const control = new AbortController();
    readTeam(control.signal).then(
      (team) =>
        setPeople(
          team.reps.map((rep) => ({
            value: `person:${rep.person_id}`,
            label: rep.name,
          })),
        ),
      () => undefined,
    );
    readSenders(control.signal).then(
      (found) =>
        setSenders(
          found.map((sender) => ({
            value: `sender:${sender.sender_id}`,
            label: sender.label,
          })),
        ),
      () => undefined,
    );
    return () => control.abort();
  }, [page, locked]);

  const go = (change: Partial<OutreachQuery>) => {
    const next = outreachSearch({ ...query, ...change, cursor: null });
    const text = next.toString();
    router.replace(text ? `${pathname}?${text}` : (pathname ?? "/outreach"), {
      scroll: false,
    });
  };

  const loadMore = async () => {
    if (!extra.cursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const next = await readOutreach({ ...query, cursor: extra.cursor });
      setMore({
        key,
        leads: [...extra.leads, ...next.leads],
        touches: [...extra.touches, ...next.touches],
        cursor: next.next_cursor,
      });
    } catch {
      // The button stays; a tap tries again.
    } finally {
      setLoadingMore(false);
    }
  };

  const period = periodOf(query);
  const byOptions: Option[] = [
    { value: "", label: "Everyone" },
    { value: "person:me", label: "Me" },
    ...people,
    ...senders,
  ];
  if (query.by && !byOptions.some((option) => option.value === query.by))
    byOptions.push({ value: query.by, label: "Chosen" });

  const leads = page ? [...page.leads, ...extra.leads] : [];
  const touches = page ? [...page.touches, ...extra.touches] : [];

  return (
    <div className={styles.page}>
      <section className={styles.hero} aria-label="Outreach in this period">
        {page ? (
          <>
            <p className={styles.period}>{page.hero.period}</p>
            <h2 className={styles.heroWords}>{page.hero.words}</h2>
            <p className={styles.sentence}>
              {page.hero.leads_added !== null &&
              page.hero.leads_added !== undefined
                ? `${page.hero.leads_added} ${page.hero.leads_added === 1 ? "lead" : "leads"} added. `
                : ""}
              {page.hero.sentence}
            </p>
          </>
        ) : error ? (
          <>
            <h2 className={styles.heroWords}>Outreach didn&apos;t load</h2>
            <p className={styles.sentence}>{error}</p>
            <button
              type="button"
              className={styles.retry}
              onClick={() => setAttempt((value) => value + 1)}
            >
              Try again
            </button>
          </>
        ) : (
          <div aria-busy="true" aria-label="Loading outreach">
            <Skeleton height={86} />
          </div>
        )}
      </section>

      <div className={styles.filters} aria-label="Filters" role="group">
        <PillSwitch
          label="Period"
          value={period ?? "week"}
          options={[
            { key: "today", label: "Today" },
            { key: "week", label: "7 days" },
            { key: "month", label: "30 days" },
          ]}
          onChange={(next) => go(periodRange(next))}
        />
        <div className={styles.selects}>
          <SelectPill
            label="By"
            value={query.by ?? ""}
            options={byOptions}
            locked={locked ? "You" : undefined}
            onChange={(by) => go({ by: by || null })}
          />
          <SelectPill
            label="Channel"
            value={query.channel ?? ""}
            options={CHANNEL_OPTIONS}
            onChange={(channel) => go({ channel: channel || null })}
          />
          <SelectPill
            label="Replied"
            value={query.replied ?? "any"}
            options={REPLIED_OPTIONS}
            onChange={(replied) =>
              go({ replied: replied as OutreachQuery["replied"] })
            }
          />
          <button
            type="button"
            className={styles.togglePill}
            aria-pressed={!!query.over}
            onClick={() => go({ over: !query.over })}
          >
            Past a limit
          </button>
        </div>
      </div>

      <div className={styles.viewRow}>
        <PillSwitch
          label="Show"
          value={query.view === "touches" ? "touches" : "leads"}
          options={[
            { key: "leads", label: "By lead" },
            { key: "touches", label: "By message" },
          ]}
          onChange={(view) => go({ view })}
        />
      </div>

      {page ? (
        query.view === "touches" ? (
          touches.length ? (
            <ol className={`${family.card} ${styles.list}`}>
              {touches.map((touch) => (
                <TouchLine key={touch.touch_id} touch={touch} withLead />
              ))}
            </ol>
          ) : (
            <Empty />
          )
        ) : leads.length ? (
          <ul className={`${family.card} ${styles.list}`}>
            {leads.map((row) => (
              <LeadCard key={row.lead_id} row={row} />
            ))}
          </ul>
        ) : (
          <Empty />
        )
      ) : null}

      {page && extra.cursor ? (
        <button
          type="button"
          className={styles.more}
          disabled={loadingMore}
          onClick={() => void loadMore()}
        >
          {loadingMore ? "Loading…" : "Show more"}
        </button>
      ) : null}
    </div>
  );
}

function Empty() {
  return (
    <div className={`${family.card} ${styles.empty}`}>
      <p className={styles.emptyTitle}>Nothing sent in this period</p>
      <p className={styles.quiet}>
        Messages, calls and files sent to leads show here, with who sent them.
      </p>
    </div>
  );
}
