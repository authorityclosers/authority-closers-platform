"use client";

/**
 * The team's Home (owner and Dipak, 31 Oct 2026): every figure Dipak's
 * handoff asks of an owner's Home, one lead type at a time, Inbound or Cold,
 * never mixed.
 *
 * - The side's leads: New leads (Inbound) or Unworked (Cold), Open leads,
 *   late follow-ups and leads with no owner, each the count of the exact list
 *   it opens.
 * - Today's calls on that side: tried, connected, not connected, talk time;
 *   then speed: first call (Inbound) or coverage (Cold), Open → Interested,
 *   leads reached, calls without a recording.
 * - Needs you now: what is waiting, worst first, each one tap into its list.
 * - Each seller's day (owners and admins only; sellers never see a ranking):
 *   tries, connects, talk time, the longest break (red when nobody set it)
 *   and the last call.
 *
 * On a phone one column, the figures in a slider; from 1024 px a full-width
 * grid: the work on the left, what needs you on the right.
 */

import {
  ArrowRight,
  ChevronDown,
  ChevronRight,
  Phone,
  RefreshCw,
  RotateCcw,
  Snowflake,
  Target,
  Users,
  CircleCheck,
  Hourglass,
} from "lucide-react";
import Link from "next/link";
import { createAvatar } from "@dicebear/core";
import { micah } from "@dicebear/collection";
import {
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type ReactNode,
} from "react";

import { deskRequest, type LeadPage } from "../leads/leads-client";
import {
  readEffort,
  type Effort,
  type SellerEffort,
  type SideEffort,
} from "../performance/performance-client";
import { Sheet } from "../ui/sheet";
import { SideSelector, type Side } from "../ui/side-selector";
import { breakLength } from "./home-today";
import {
  Count,
  MetricPager,
  MoreFigures,
  minutes,
  share,
  type More,
} from "./metric-pager";
import { leadsHref } from "./seller-home";
import { useHomeRead } from "./home-load";
import { dayName, useHomeDay } from "./home-day";
import styles from "./team-floor.module.css";
import { talkOrDash } from "./talk-time";

const everyHalfMinute = (onChange: () => void) => {
  const timer = window.setInterval(onChange, 30_000);
  return () => window.clearInterval(timer);
};
const nowMinute = () => Math.floor(Date.now() / 60_000);
const noMinute = () => 0;

/** How fresh today's numbers are (critique 01): "just now" for a minute, then
 *  "4 min ago", then the time. It changes when the numbers are read again. */
function Freshness({ at }: { at: number }) {
  const minute = useSyncExternalStore(everyHalfMinute, nowMinute, noMinute);
  const ago = minute ? minute - Math.floor(at / 60_000) : null;
  const words =
    ago === null || ago >= 60
      ? CLOCK.format(at)
      : ago < 1
        ? "just now"
        : `${ago} min ago`;
  return (
    <span className={styles.updated} title={`Read at ${CLOCK.format(at)}`}>
      {/* Turns once when new numbers land (top bar v2, from v4). */}
      <RefreshCw
        key={at}
        className={styles.syncGlyph}
        size={14}
        strokeWidth={2}
        aria-hidden="true"
      />
      <span className={styles.updatedWord}>Updated </span>
      {words}
    </span>
  );
}

/** Today's figures from the Performance engine; the last good ones if a read
 *  fails; null until the first arrives. */
function useEffort(day: string | null) {
  // Today keeps its own key, which other parts of Home share.
  return useHomeRead(day ? `effort:1:${day}` : "effort:1", (signal) =>
    readEffort(1, signal, false, day ?? undefined),
  );
}

/** The stages the New and Open leads cards open, found by meaning on the server (the
 *  desk's new_key and open_key); null where the organisation's stages have none. An
 *  organisation on older stages has no "open_leads" (phone personas, 31 Oct 2026). */
export type StageKeys = { newKey: string | null; openKey: string | null };

type SideCounts = {
  fresh: number | null;
  open: number | null;
  unowned: number;
};

/** The side's three lead counts, each the total of the list its card opens; none
 *  until the stage keys are known, and none for a stage the organisation lacks. */
function useSideCounts(side: Side, stages: StageKeys | undefined) {
  const which = stages
    ? `${stages.newKey ?? "-"}:${stages.openKey ?? "-"}`
    : "wait";
  return useHomeRead<SideCounts | null>(
    `counts:${side}:${which}`,
    async (signal) => {
      if (!stages) return null;
      const total = (query: string) =>
        deskRequest<LeadPage>(`/leads?${query}`, { signal }).then(
          (page) => page.total,
        );
      const step = (key: string) => encodeURIComponent(key);
      const [fresh, open, unowned] = await Promise.all([
        stages.newKey
          ? total(
              `scope=team&side=${side}&view=to_call&step=${step(stages.newKey)}`,
            )
          : null,
        stages.openKey
          ? // All Leads at that stage, both sides: the list the card opens.
            total(
              `scope=team&side=${side}&view=all&step=${step(stages.openKey)}`,
            )
          : null,
        total(`scope=unassigned&side=${side}`),
      ]);
      return { fresh, open, unowned };
    },
  );
}

const count = (value: number | undefined | null) =>
  value === undefined || value === null ? null : String(value);

const LATE = (side: Side) =>
  `/leads?tab=all&due=late${side === "cold" ? "&side=cold" : ""}`;

/** An unexplained gap of an hour or more: red. */
const longGap = (seller: SellerEffort) =>
  seller.breaks.some((gap) => !gap.planned && gap.minutes >= 60);

type Need = {
  key: string;
  count: number;
  label: string;
  href: string;
  /** The count's colour by meaning (design-research piece 07): missed calls
   *  rose; late, no owner and breaks orange; waiting sky; recordings neutral. */
  tone: "emerald" | "orange" | "rose" | "violet" | "sky" | "slate";
  /** A second line, where the alert counts something other than the side shown. */
  note?: string;
};

/** What is waiting on the owner, worst first; only what is above zero. */
function needs(
  side: Side,
  counts: SideCounts | null,
  effort: Effort | null,
  stages: StageKeys | undefined,
): Need[] {
  const day = effort?.[side];
  // Most urgent first (design-research piece 07): a customer who called and
  // wasn't called back, then promises already late, then new leads waiting.
  const list: Need[] = [
    side === "inbound" && effort
      ? {
          key: "missed",
          count: effort.inbound.not_called_back,
          label: "Missed calls not called back",
          tone: "rose",
          href: leadsHref("inbound", { view: "to_call" }),
        }
      : null,
    day
      ? {
          key: "late",
          count: day.late,
          label: "Overdue follow-ups",
          tone: "orange",
          href: LATE(side),
        }
      : null,
    side === "inbound" && counts?.fresh != null && stages?.newKey
      ? {
          key: "fresh",
          count: counts.fresh,
          label: "New leads waiting for a first call",
          tone: "sky",
          href: leadsHref("inbound", { view: "to_call", step: stages.newKey }),
        }
      : null,
    counts
      ? {
          key: "unowned",
          count: counts.unowned,
          label: "Leads with no owner",
          tone: "orange",
          href: `/leads?tab=all&stage=open&who=unassigned${side === "cold" ? "&side=cold" : ""}`,
        }
      : null,
    effort
      ? {
          key: "gaps",
          count: effort.sellers.filter(longGap).length,
          label: "Sellers with a 1h+ break",
          note: "Unexplained · All lead types",
          tone: "orange",
          href: "/growth",
        }
      : null,
    effort
      ? {
          key: "recordings",
          // The side shown's own (owner, 4 Nov 2026, #174 #175: Inbound said 0
          // tried beside 11 without a recording, all on Cold); an older
          // server's total otherwise.
          count: day?.missing_recordings ?? effort.missing_recordings,
          label: "Calls missing a recording",
          tone: "slate",
          href: "/analysis/calls",
        }
      : null,
  ].filter((need): need is Need => !!need && need.count > 0);
  return list;
}

function pages(
  side: Side,
  counts: SideCounts | null,
  day: SideEffort | null,
  stages: StageKeys | undefined,
): { leads: More[]; calls: More[]; speed: More[] } {
  const cold = side === "cold";
  // Calls whose outcome the phone never told us are neither connected nor
  // not; each number opens the calls it counts (owner and Dipak, 2 Nov 2026).
  const unknown = day?.unknown ?? 0;
  const calls = `/analysis/calls?day=today&team=1&side=${side}`;
  // A card whose stage the organisation doesn't have is left out, never "0".
  const has = (key: string | null | undefined) => !stages || !!key;
  return {
    leads: [
      ...(has(stages?.newKey)
        ? [
            {
              key: "new",
              label: cold ? "Unworked" : "New leads",
              value: count(counts?.fresh),
              red: (counts?.fresh ?? 0) > 0,
              href: leadsHref(side, {
                view: "to_call",
                step: stages?.newKey ?? "new",
              }),
              help: cold
                ? "Cold leads nobody has called yet"
                : "Enquiries waiting for their first call",
            },
          ]
        : []),
      ...(has(stages?.openKey)
        ? [
            {
              key: "open",
              label: "Open leads",
              value: count(counts?.open),
              href: leadsHref(side, {
                view: "all",
                step: stages?.openKey ?? "open_leads",
              }),
              help: "Leads called and still in discussion",
            },
          ]
        : []),
      {
        key: "late",
        label: "Follow-ups late",
        value: count(day?.late),
        red: (day?.late ?? 0) > 0,
        href: LATE(side),
        help: "Follow-ups more than an hour past their time",
      },
      {
        key: "unowned",
        label: "No owner",
        value: count(counts?.unowned),
        red: (counts?.unowned ?? 0) > 0,
        href: `/leads?tab=all&stage=open&who=unassigned${cold ? "&side=cold" : ""}`,
        help: "Leads no seller has been given",
      },
    ],
    calls: [
      {
        key: "tried",
        label: "Tried",
        value: count(day?.attempted),
        href: calls,
        help: "Calls made today",
      },
      unknown && day
        ? {
            key: "known",
            label: "Outcome known",
            value: String(day.attempted - unknown),
            note: `${day.connected} connected · ${day.attempted - unknown - day.connected} not`,
            href: `${calls}&outcome=known`,
            help: "Calls whose outcome the phone told us today, and how many connected",
          }
        : {
            key: "connected",
            label: "Connected",
            value: count(day?.connected),
            note:
              day && day.attempted
                ? share(day.connected, day.attempted)
                : undefined,
            href: `${calls}&outcome=connected`,
            help: "Calls answered today, and their share of the calls made",
          },
      {
        key: "not_connected",
        label: "Not connected",
        value: day ? String(day.attempted - day.connected - unknown) : null,
        href: `${calls}&outcome=not_connected`,
        help: "Calls nobody answered today",
      },
      {
        key: "talk",
        label: "Talk time",
        value: day
          ? talkOrDash(day.talk_seconds, day.talk_estimated_seconds, minutes)
          : null,
        href: `${calls}&outcome=connected`,
        help: "Time spent on answered calls today",
      },
    ],
    speed: [
      cold
        ? {
            key: "coverage",
            label: "Coverage",
            value: day ? share(day.leads_attempted, day.eligible) : null,
            help: "Of the leads open or called today, the share called at least once",
          }
        : {
            key: "first_call",
            label: "First call in",
            value: day
              ? day.first_call_minutes === null
                ? "–"
                : `${day.first_call_minutes} min`
              : null,
            help: "Typical minutes from an enquiry arriving to its first call",
          },
      {
        key: "interested",
        label: "Open → Interested",
        value: day ? share(day.worked_interested, day.leads_attempted) : null,
        help: "Of the leads called today, the share moved to Interested or Won",
      },
      {
        key: "reached",
        label: "Leads reached",
        value: count(day?.reached),
        help: "Different leads spoken to today",
      },
      {
        key: "meetings",
        label: "Meetings",
        value: count(day?.meetings),
        help: "Leads given a meeting today",
      },
    ],
  };
}

const CLOCK = new Intl.DateTimeFormat("en-IN", {
  hour: "numeric",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
});

/** How many working sellers Home lists; the rest are a tap away (piece 03). */
const SELLERS_ON_HOME = 5;

/** One seller's row: face, name and one quiet line, then their numbers in the
 *  table's columns. A zero is muted, never faded as if switched off. */
function SellerRow({
  seller,
  side,
  me,
  tone,
}: {
  seller: SellerEffort;
  side: Side;
  me: string | null;
  tone: number | undefined;
}) {
  const day = seller[side];
  const other: Side = side === "cold" ? "inbound" : "cold";
  // A break is time between calls inside the working day: worth a line only when
  // it was an hour or more and not a set break.
  const gap =
    seller.inbound.attempted + seller.cold.attempted
      ? seller.breaks[0]
      : undefined;
  const long = gap && !gap.planned && gap.minutes >= 60 ? gap : undefined;
  const line = long
    ? `Break ${breakLength(long.minutes)}`
    : day.attempted && seller.last_call_at
      ? `Last call ${CLOCK.format(new Date(seller.last_call_at))}`
      : seller[other].attempted
        ? `${seller[other].attempted} on ${other === "cold" ? "Cold" : "Inbound"}`
        : "No calls yet";
  return (
    <li>
      <Link className={styles.sellerRow} href="/growth">
        <span className={styles.rowWho}>
          <span className={styles.rowFace} aria-hidden="true">
            <Face seller={seller} tone={tone} />
          </span>
          <span className={styles.rowName}>
            <strong>{seller.person_id === me ? "You" : seller.name}</strong>
            <small data-warn={long ? "" : undefined}>{line}</small>
          </span>
        </span>
        <b data-zero={!day.attempted || undefined}>{day.attempted}</b>
        <b data-zero={!day.connected || undefined}>{day.connected}</b>
        <b data-zero={!day.talk_seconds || undefined}>
          {minutes(day.talk_seconds)}
        </b>
      </Link>
    </li>
  );
}

function Sellers({
  effort,
  side,
  me,
  chosenDay = null,
}: {
  effort: Effort | null;
  side: Side;
  /** The viewer: their own row reads You. */
  me: string | null;
  /** A chosen past day: the day's own numbers, no Updated time. */
  chosenDay?: string | null;
}) {
  // The sellers with no calls on this side: one row until opened.
  const [idleOpen, setIdleOpen] = useState(false);
  if (!effort) return <div className={styles.loading} aria-busy="true" />;
  const sellers = [...effort.sellers].sort(
    (a, b) => b[side].attempted - a[side].attempted,
  );
  if (!sellers.length)
    return <p className={styles.quiet}>No sellers on this side yet.</p>;
  const tones = faceTones(sellers);
  const sideName = side === "cold" ? "Cold" : "Inbound";
  const working = sellers.filter((seller) => seller[side].attempted > 0);
  const idle = sellers.filter((seller) => !seller[side].attempted);
  const shown = working.slice(0, SELLERS_ON_HOME);
  return (
    <>
      <p className={styles.sellersNote}>
        <span>
          {sideName} · {chosenDay ? dayName(chosenDay) : "Today"} ·{" "}
          {chosenDay
            ? "the whole day"
            : `Updated ${CLOCK.format(new Date(effort.end))}`}
        </span>
      </p>
      <div className={styles.sellerTable}>
        <div className={styles.sellerHead} aria-hidden="true">
          <span>Seller</span>
          <span>Tried</span>
          <span>Connected</span>
          <span>Talk</span>
        </div>
        {shown.length ? (
          <ul className={styles.sellerRows} aria-label="Each seller today">
            {shown.map((seller) => (
              <SellerRow
                key={seller.person_id}
                seller={seller}
                side={side}
                me={me}
                tone={tones.get(seller.person_id)}
              />
            ))}
          </ul>
        ) : null}
        {idle.length ? (
          <div className={styles.idleGroup} data-open={idleOpen || undefined}>
            <button
              type="button"
              className={styles.idleRow}
              aria-expanded={idleOpen}
              onClick={() => setIdleOpen((open) => !open)}
            >
              <span className={styles.idleFaces} aria-hidden="true">
                {idle.slice(0, 5).map((seller) => (
                  <span key={seller.person_id}>
                    <Face seller={seller} tone={tones.get(seller.person_id)} />
                  </span>
                ))}
              </span>
              <span className={styles.idleWords}>
                {idle.length} {idle.length === 1 ? "seller" : "sellers"} with no{" "}
                {sideName.toLowerCase()} calls {chosenDay ? "that day" : "yet"}
              </span>
              <ChevronDown size={18} strokeWidth={2.25} aria-hidden="true" />
            </button>
            <div className={styles.idleMore}>
              <ul aria-label={`No ${sideName.toLowerCase()} calls`}>
                {idle.map((seller) => (
                  <SellerRow
                    key={seller.person_id}
                    seller={seller}
                    side={side}
                    me={me}
                    tone={tones.get(seller.person_id)}
                  />
                ))}
              </ul>
            </div>
          </div>
        ) : null}
        {working.length > SELLERS_ON_HOME ? (
          <Link className={styles.viewAll} href="/growth">
            View all {sellers.length} sellers
            <ChevronRight size={16} strokeWidth={2.25} aria-hidden="true" />
          </Link>
        ) : null}
      </div>
    </>
  );
}

function Split({ effort }: { effort: Effort | null }) {
  const column = (side: Side, day: SideEffort | undefined) => {
    const Icon = side === "inbound" ? ArrowRight : Snowflake;
    return (
      <div className={styles.splitSide} data-side={side}>
        <span className={styles.splitName}>
          <span className={styles.splitIcon} aria-hidden="true">
            <Icon size={18} strokeWidth={2.25} />
          </span>
          {side === "inbound" ? "Inbound" : "Cold"}
        </span>
        <dl>
          <div>
            <dt>Tried</dt>
            <dd>{day ? day.attempted.toLocaleString("en-IN") : "–"}</dd>
          </div>
          <div>
            <dt>Connected</dt>
            <dd>{day ? day.connected.toLocaleString("en-IN") : "–"}</dd>
          </div>
          <div>
            <dt>Talk time</dt>
            <dd>{day ? minutes(day.talk_seconds) : "–"}</dd>
          </div>
        </dl>
        {/* Calls whose outcome the phone never told us: their own count. */}
        <p className={styles.splitFoot}>
          <span>Unknown outcomes</span>
          <b>{day ? (day.unknown ?? 0).toLocaleString("en-IN") : "–"}</b>
        </p>
      </div>
    );
  };
  return (
    <div className={styles.split}>
      {column("inbound", effort?.inbound)}
      {column("cold", effort?.cold)}
    </div>
  );
}

const RING = 2 * Math.PI * 52;

/** Each seller's own colour on the floor: their place in the team by id, so no two of up
 *  to eight share one and a person keeps theirs every day (owner on the Note 8, 14 Nov 2026:
 *  "make the AJ, AC, DV... more colorful"). */
const FACE_TONES = 5;
const faceTones = (sellers: SellerEffort[]) =>
  new Map(
    sellers
      .map((seller) => seller.person_id)
      .sort()
      .map((id, index) => [id, index % FACE_TONES] as const),
  );

/** When nobody has called on the side shown but the team has on the other,
 *  where today's calls are (owner, 4 Nov 2026, #174 #175: "Swamini called and
 *  this panel says zero"; all her calls were on Cold). */
export function elsewhere(side: Side, effort: Effort | null): string {
  const other: Side = side === "cold" ? "inbound" : "cold";
  const here = effort?.[side]?.attempted ?? 0;
  const there = effort?.[other]?.attempted ?? 0;
  if (here || !there) return "";
  return ` · ${there} tried on ${other === "cold" ? "Cold" : "Inbound"}`;
}

const FACES_KEY = "sx:home-floor-faces";
const subscribeNothing = () => () => {};
const readKeptFaces = (): string | null => {
  try {
    return window.localStorage.getItem(FACES_KEY);
  } catch {
    return null;
  }
};

/** How many faces the floor drew last on this device: seven, the most it
 *  draws, until it has drawn once. */
function useKeptFaces(drawn: number | null): number {
  const kept = useSyncExternalStore(
    subscribeNothing,
    readKeptFaces,
    () => null,
  );
  useEffect(() => {
    if (drawn === null) return;
    try {
      window.localStorage.setItem(FACES_KEY, String(drawn));
    } catch {
      // Not kept this time; the next visit holds room for seven.
    }
  }, [drawn]);
  return kept !== null && /^[0-7]$/.test(kept) ? Number(kept) : 7;
}

/** Called today, on either lead type (17_18_Hero_Spec.md: participation spans
 *  both; the hero's call figures keep the side shown). */
const worked = (seller: SellerEffort) =>
  seller.inbound.attempted + seller.cold.attempted > 0;

/** A seller's face: their own photo (owner, 15 Nov 2026: so he can see who has
 *  worked), else their initials in their colour; a photo that fails falls back. */
function Face({ seller }: { seller: SellerEffort; tone: number | undefined }) {
  const [broken, setBroken] = useState<string | null>(null);
  const photo = seller.photo_url ?? null;
  return photo && broken !== photo ? (
    // eslint-disable-next-line @next/next/no-img-element -- A private photo read with the signed-in session, as the account's own.
    <img
      src={photo}
      alt=""
      referrerPolicy="no-referrer"
      decoding="async"
      loading="lazy"
      onError={() => setBroken(photo)}
    />
  ) : (
    <Character id={seller.person_id} name={seller.name} />
  );
}

/** owner 15 Nov: anyone without a photo gets an illustrated character (DiceBear
 *  "Micah" by Micah Lanier, CC BY 4.0), the same one every time for that person. */
const CHARACTER_BG = [
  "d7f5e9",
  "e7e2ff",
  "ffe8cc",
  "dff1ff",
  "ffe0e6",
  "eef7d6",
];
function Character({ id, name }: { id: string; name: string }) {
  const src = useMemo(
    () =>
      createAvatar(micah, {
        seed: id,
        backgroundColor: CHARACTER_BG,
        radius: 50,
        mouth: ["smile", "laughing", "smirk"],
      }).toDataUri(),
    [id],
  );
  // eslint-disable-next-line @next/next/no-img-element -- an inline SVG drawn here, not a file
  return <img src={src} alt="" aria-label={name} data-character="" />;
}

/** A value still on its way: a quiet bar, shown only if the read takes more than
 *  150 ms (critique 02); never a zero or a dash that could be read as one. */
const Wait = () => <i className={styles.wait} aria-hidden="true" />;

/** How many faces the team's row shows at once on a phone (four 44 px cells). */
const FACES_IN_VIEW = 4;

/** The floor at a glance (owner's chosen Home, 01_Home.png; faces from
 *  17_Hero_Team_Faces; critique 02, 15 Nov 2026). Left: the connected ring, whose
 *  count and share are the same thing. Right: Total calls and Connection rate, each
 *  number under its name, then the team. Under both: the two outcomes the ring
 *  doesn't show, Not connected and Unknown. Each part opens what it counts. */
/** owner 15 Nov: a tiny ring that shows this outcome's share of all calls, drawn in. */
function ShareRing({
  value,
  total,
  tone,
}: {
  value: number;
  total: number;
  tone: "on" | "off";
}) {
  const c = 2 * Math.PI * 8;
  const share = total > 0 ? Math.min(1, value / total) : 0;
  return (
    <svg
      className={styles.shareRing}
      data-tone={tone}
      viewBox="0 0 20 20"
      aria-hidden="true"
    >
      <circle className={styles.shareTrack} cx="10" cy="10" r="8" />
      <circle
        className={styles.shareArc}
        cx="10"
        cy="10"
        r="8"
        style={{ strokeDasharray: c, strokeDashoffset: c * (1 - share) }}
      />
    </svg>
  );
}

type Explaining = "ring" | "calls" | "rate" | "sellers" | "worked" | "notyet";

/** owner 15 Nov: a calm bottom sheet that says what a number means, with the detail
 *  behind it and "See all" for the full page. Slides up, fades the page behind. */
function ExplainSheet({
  what,
  onClose,
  day,
  notConnected,
  unknown,
  rate,
  sellers,
  worked: workedList,
  calls,
  tones,
}: {
  what: Explaining | null;
  onClose: () => void;
  day: { attempted: number; connected: number } | null;
  notConnected: number;
  unknown: number;
  rate: number;
  sellers: SellerEffort[];
  worked: SellerEffort[];
  calls: string;
  tones: ReturnType<typeof faceTones>;
}) {
  // The shared pop-up (owner, 15 Nov 2026: every pop-up the same): the kit
  // Sheet springs in, drags down and closes; the words stay while it slides away.
  const [shown, setShown] = useState<Explaining | null>(what);
  if (what && what !== shown) setShown(what);
  const k = what ?? shown;
  if (!k) return null;
  const total = day?.attempted ?? 0;
  const connected = day?.connected ?? 0;
  const pct = (n: number) => (total ? Math.round((n / total) * 100) : 0);
  const notYet = sellers.filter((x) => !workedList.includes(x));
  const people =
    k === "worked" ? workedList : k === "notyet" ? notYet : sellers;
  const head: Record<
    Explaining,
    { title: string; line: string; href: string; see: string }
  > = {
    ring: {
      title: "Connected calls",
      line: `${connected} of ${total} calls today were picked up.`,
      href: `${calls}&outcome=connected`,
      see: "See connected calls",
    },
    calls: {
      title: "Total calls",
      line: `Every call the team made today: ${total}.`,
      href: calls,
      see: "See all calls",
    },
    rate: {
      title: "Connection rate",
      line: `${Math.round(rate * 100)}% of calls were picked up (${connected} ÷ ${total}).`,
      href: `${calls}&outcome=connected`,
      see: "See connected calls",
    },
    sellers: {
      title: "Your team",
      line: `${sellers.length} sellers on this side today.`,
      href: "/growth",
      see: "See team performance",
    },
    worked: {
      title: "Worked today",
      line: `${workedList.length} sellers have made calls today.`,
      href: "/growth",
      see: "See team performance",
    },
    notyet: {
      title: "Not yet",
      line: `${notYet.length} sellers have not made a call yet today.`,
      href: "/growth",
      see: "See team performance",
    },
  };
  const h = head[k];
  const split = k === "ring" || k === "calls" || k === "rate";
  return (
    <Sheet
      open={what !== null}
      onClose={onClose}
      title={h.title}
      description={h.line}
      className={styles.explainKit}
    >
      {split ? (
        <>
          <div className={styles.explainBar} aria-hidden="true">
            <i data-k="on" style={{ width: `${pct(connected)}%` }} />
            <i data-k="off" style={{ width: `${pct(notConnected)}%` }} />
            {unknown ? (
              <i data-k="unknown" style={{ width: `${pct(unknown)}%` }} />
            ) : null}
          </div>
          <dl className={styles.explainRows}>
            <div>
              <dt>
                <i data-k="on" />
                Connected
              </dt>
              <dd>
                {connected}
                <small>{pct(connected)}%</small>
              </dd>
            </div>
            <div>
              <dt>
                <i data-k="off" />
                Not connected
              </dt>
              <dd>
                {notConnected}
                <small>{pct(notConnected)}%</small>
              </dd>
            </div>
            {unknown ? (
              <div>
                <dt>
                  <i data-k="unknown" />
                  Unknown
                </dt>
                <dd>
                  {unknown}
                  <small>{pct(unknown)}%</small>
                </dd>
              </div>
            ) : null}
          </dl>
        </>
      ) : (
        <ul className={styles.explainPeople}>
          {people.map((x, n) => (
            <li key={x.person_id} style={{ animationDelay: `${n * 35}ms` }}>
              <Face seller={x} tone={tones.get(x.person_id)} />
              <span>{x.name}</span>
              <small data-worked={workedList.includes(x) ? "" : undefined}>
                {workedList.includes(x) ? "Worked" : "Not yet"}
              </small>
            </li>
          ))}
        </ul>
      )}
      <Link className={styles.explainSee} href={h.href} onClick={onClose}>
        {h.see}
        <ChevronRight size={16} aria-hidden="true" />
      </Link>
    </Sheet>
  );
}

function FloorHero({
  effort,
  side,
  past = false,
}: {
  effort: Effort | null;
  side: Side;
  /** A chosen past day: "No calls that day". */
  past?: boolean;
}) {
  const day = effort?.[side] ?? null;
  // The counts' context: a new side or day fades its numbers in, a live update on
  // the same one counts on (motion-research-2.md section 4).
  const countFor = `${side}:${effort?.start ?? ""}`;
  const unknown = day?.unknown ?? 0;
  const notConnected = day
    ? Math.max(0, day.attempted - day.connected - unknown)
    : 0;
  const rate = day && day.attempted ? day.connected / day.attempted : 0;
  const none = day !== null && day.attempted === 0;
  const sellers = effort?.sellers ?? [];
  // Until the team's numbers land, the faces drawn last time hold their room unseen.
  const faces = useKeptFaces(effort ? sellers.length : null);
  const tones = faceTones(sellers);
  // Worked first, each group in the engine's own order.
  const done = sellers.filter(worked);
  const ordered = [...done, ...sellers.filter((seller) => !worked(seller))];
  const calls = `/analysis/calls?day=today&team=1&side=${side}`;
  // owner 15 Nov: a tap explains, in a sheet; "See all" opens the full page.
  const [explain, setExplain] = useState<Explaining | null>(null);
  return (
    <section
      className={styles.hero}
      aria-busy={effort ? undefined : true}
      aria-label={`Today's calls on ${side === "cold" ? "Cold" : "Inbound"}`}
    >
      <div className={styles.ringSide}>
        <button
          type="button"
          className={styles.ringCell}
          onClick={() => setExplain("ring")}
          aria-label={
            day
              ? `${day.connected} connected of ${day.attempted} calls`
              : "Connected calls"
          }
        >
          <span
            className={styles.dayRing}
            data-none={none || undefined}
            aria-hidden="true"
          >
            <svg viewBox="0 0 120 120">
              <circle className={styles.ringTrack} cx="60" cy="60" r="52" />
              <circle
                className={styles.ringDone}
                cx="60"
                cy="60"
                r="52"
                style={
                  {
                    "--ring": RING,
                    strokeDasharray: RING,
                    strokeDashoffset: RING * (1 - rate),
                  } as CSSProperties
                }
              />
            </svg>
            <span className={styles.ringText}>
              <strong>
                {day ? (
                  <Count
                    value={String(day.connected)}
                    reveal={!past}
                    context={countFor}
                  />
                ) : (
                  <Wait />
                )}
              </strong>
              <span>Connected</span>
              <small>
                {!day
                  ? " "
                  : none
                    ? past
                      ? "No calls that day"
                      : "No calls yet today"
                    : `of ${count(day.attempted)} calls`}
              </small>
            </span>
          </span>
        </button>
      </div>
      <div className={styles.stats}>
        <button
          type="button"
          className={styles.stat}
          onClick={() => setExplain("calls")}
        >
          <span className={styles.statName}>
            <Phone strokeWidth={1.8} aria-hidden="true" />
            Total calls
          </span>
          <strong>
            {day ? (
              <Count
                value={String(day.attempted)}
                reveal={!past}
                context={countFor}
              />
            ) : (
              <Wait />
            )}
          </strong>
        </button>
        <button
          type="button"
          className={styles.stat}
          onClick={() => setExplain("rate")}
        >
          <span className={styles.statName}>
            <Target strokeWidth={1.8} aria-hidden="true" />
            Connection rate
          </span>
          <strong>
            {!day ? (
              <Wait />
            ) : day.attempted ? (
              `${Math.round(rate * 100)}%`
            ) : (
              "—"
            )}
          </strong>
        </button>
        <div className={styles.team} role="group" aria-label="Team performance">
          <span className={styles.teamHead}>
            <Users strokeWidth={1.8} aria-hidden="true" />
            <span>Team performance</span>
            <ChevronRight size={16} aria-hidden="true" />
          </span>
          <span className={styles.workLine}>
            {effort && sellers.length ? (
              <>
                {/* owner 15 Nov: three quiet chips; a tap explains */}
                <button
                  type="button"
                  className={styles.chip}
                  onClick={() => setExplain("sellers")}
                >
                  <Users size={14} strokeWidth={2} aria-hidden="true" />
                  {sellers.length}
                  <span className={styles.chipWord}>
                    {sellers.length === 1 ? " seller" : " sellers"}
                  </span>
                </button>
                <button
                  type="button"
                  className={styles.chip}
                  data-tone="good"
                  data-none={done.length ? undefined : ""}
                  onClick={() => setExplain("worked")}
                >
                  <CircleCheck
                    size={14}
                    strokeWidth={2.25}
                    aria-hidden="true"
                  />
                  {done.length}
                  <span className={styles.chipWord}> worked</span>
                </button>
                <button
                  type="button"
                  className={styles.chip}
                  data-tone="wait"
                  onClick={() => setExplain("notyet")}
                >
                  <Hourglass size={14} strokeWidth={2} aria-hidden="true" />
                  {sellers.length - done.length}
                  <span className={styles.chipWord}> not yet</span>
                </button>
              </>
            ) : (
              " "
            )}
          </span>
          <ul className={styles.faces} aria-label={`${sellers.length} sellers`}>
            {effort
              ? null
              : Array.from({ length: faces }, (_, index) => (
                  <li key={index} data-wait="">
                    <span />
                  </li>
                ))}
            {ordered.map((seller) => {
              const called = worked(seller);
              return (
                <li
                  key={seller.person_id}
                  data-worked={called ? "" : undefined}
                  title={`${seller.name}: ${called ? "made calls today" : "no calls yet today"}`}
                >
                  <Face seller={seller} tone={tones.get(seller.person_id)} />
                </li>
              );
            })}
          </ul>
          {/* His passive scroll line (17_18_Hero_Spec.md): how much of the team
              is in view, and where. */}
          {ordered.length > FACES_IN_VIEW ? (
            <span
              className={styles.stripLine}
              aria-hidden="true"
              style={
                {
                  "--share": FACES_IN_VIEW / ordered.length,
                } as CSSProperties
              }
            />
          ) : null}
        </div>
      </div>
      {/* Connected | Not connected, as in his reference; Unknown beside them
          only when there is any, never folded into either. */}
      <div className={styles.foot}>
        <Link href={`${calls}&outcome=connected`}>
          <span className={styles.statName}>
            <ShareRing
              value={day ? day.connected : 0}
              total={day ? day.attempted : 0}
              tone="on"
            />
            Connected
          </span>
          <b>{day ? count(day.connected) : <Wait />}</b>
        </Link>
        <Link href={`${calls}&outcome=not_connected`}>
          <span className={styles.statName}>
            <ShareRing
              value={notConnected}
              total={day ? day.attempted : 0}
              tone="off"
            />
            Not connected
          </span>
          <b>{day ? count(notConnected) : <Wait />}</b>
        </Link>
        {unknown ? (
          <Link href={`${calls}&outcome=known`} data-unknown="">
            <i data-dot="unknown" aria-hidden="true" />
            <span>Unknown</span>
            <b>{count(unknown)}</b>
          </Link>
        ) : null}
      </div>
      <ExplainSheet
        what={explain}
        onClose={() => setExplain(null)}
        day={day}
        notConnected={notConnected}
        unknown={unknown}
        rate={rate}
        sellers={ordered}
        worked={done}
        calls={calls}
        tones={tones}
      />
    </section>
  );
}

type FloorProps = {
  side: Side;
  onSide: (side: Side) => void;
  /** Team controls, for those who manage leads. */
  controls: ReactNode;
  /** How sales are going (the period's outcomes). */
  outcomes: ReactNode;
  /** The ways on: Performance, the team, reports. */
  more: ReactNode;
  /** The owner's own tasks and follow-ups, for those who work leads. */
  mine?: ReactNode;
  /** The viewer's person id. */
  me?: string | null;
  /** The stages the lead cards open (undefined until the desk is read). */
  stages: StageKeys | undefined;
};

export function TeamFloor(props: FloorProps) {
  // Home's date: a chosen past day, or null for today (home-day.ts).
  const [day, setDay] = useHomeDay();
  const effortRead = useEffort(day);
  // While a newly chosen day's numbers are on the way, the last ones stay,
  // dimmed, rather than an empty outline (motion-research-2.md section 3).
  const [lastEffort, setLastEffort] = useState<Effort | null>(null);
  if (effortRead.value && effortRead.value !== lastEffort)
    setLastEffort(effortRead.value);
  const staleEffort =
    !effortRead.value && !effortRead.failed && lastEffort !== null;
  const countsRead = useSideCounts(props.side, props.stages);
  // Needs you now waits for both reads (or a failure), so it never reorders as they land.
  const settled =
    (effortRead.value !== null || effortRead.failed) &&
    (countsRead.value !== null || countsRead.failed);
  return (
    <FloorBody
      {...props}
      effort={staleEffort ? lastEffort : effortRead.value}
      stale={staleEffort}
      counts={countsRead.value}
      settled={settled}
      chosenDay={day}
      onToday={() => setDay(null)}
    />
  );
}

/** The floor before anything is read (Home's outline, home-outline.tsx): the
 *  same blocks in the same places as TeamFloor draws them while its reads are
 *  on the way, with no reads of its own. */
export function FloorOutline({
  outcomes,
  more,
}: {
  outcomes: ReactNode;
  more: ReactNode;
}) {
  return (
    <FloorBody
      side="inbound"
      onSide={() => {}}
      controls={null}
      outcomes={outcomes}
      more={more}
      stages={undefined}
      effort={null}
      counts={null}
      settled={false}
    />
  );
}

function FloorBody({
  side,
  onSide,
  controls,
  outcomes,
  more,
  mine = null,
  me = null,
  stages,
  effort,
  counts,
  settled,
  chosenDay = null,
  onToday,
  stale = false,
}: FloorProps & {
  effort: Effort | null;
  /** The numbers are the last day's, while the chosen day's are read. */
  stale?: boolean;
  counts: SideCounts | null;
  settled: boolean;
  /** A chosen past day, or null for today. */
  chosenDay?: string | null;
  onToday?: () => void;
}) {
  const day = effort?.[side] ?? null;
  const figures = pages(side, counts, day, stages);
  const waiting = needs(side, counts, effort, stages);
  // The server says when its numbers are as of (its end), so the time survives
  // any cache and changes whenever they are read again.
  const at = effort ? Date.parse(effort.end) : undefined;
  // Needs you now on a phone: the first three, the rest a tap away.
  const [allNeeds, setAllNeeds] = useState(false);
  return (
    <div className={styles.floor} data-stale={stale ? "" : undefined}>
      <div className={styles.main}>
        <section
          className={`${styles.block} ${styles.today}`}
          aria-labelledby="floor-title"
        >
          <div className={styles.head}>
            {/* Today, then when its numbers were read (owner's chosen
                Home, 01_Home.png, 14 Nov 2026). */}
            <div className={styles.todayTitle}>
              <h2 id="floor-title">
                {chosenDay ? dayName(chosenDay) : "Today"}
              </h2>
              {chosenDay ? (
                <button
                  type="button"
                  className={styles.backToday}
                  onClick={onToday}
                >
                  <RotateCcw size={14} strokeWidth={2.25} aria-hidden="true" />
                  Back to today
                </button>
              ) : at ? (
                <Freshness at={at} />
              ) : null}
            </div>
            {controls}
          </div>
          <SideSelector value={side} onChange={onSide} tone="home" />
          <FloorHero effort={effort} side={side} past={Boolean(chosenDay)} />
          <MetricPager
            label="The team's numbers"
            pages={[
              {
                key: "leads",
                label: "Leads",
                tab: "Leads",
                content: (
                  <>
                    {/* The lead queues are now's, whatever the day. */}
                    {chosenDay ? (
                      <p className={styles.nowNote}>
                        <i aria-hidden="true" />
                        Leads right now
                      </p>
                    ) : null}
                    <MoreFigures figures={figures.leads} />
                  </>
                ),
              },
              {
                key: "calls",
                label: "Calls today",
                tab: "Calls",
                content: <MoreFigures figures={figures.calls} />,
              },
              {
                key: "speed",
                label: side === "cold" ? "Coverage" : "Speed",
                content: <MoreFigures figures={figures.speed} />,
              },
            ]}
          />
        </section>
        <section
          className={`${styles.block} ${styles.sellers}`}
          aria-labelledby="sellers-title"
        >
          <div className={styles.head}>
            <h2 id="sellers-title">
              {chosenDay
                ? `Each seller · ${dayName(chosenDay)}`
                : "Each seller today"}
            </h2>
            <Link className={styles.seeAll} href="/growth">
              See details
              <ChevronRight size={16} aria-hidden="true" />
            </Link>
          </div>
          <Sellers effort={effort} side={side} me={me} chosenDay={chosenDay} />
        </section>
        <section
          className={`${styles.block} ${styles.sales}`}
          aria-labelledby="sales-title"
        >
          <div className={styles.head}>
            <h2 id="sales-title">How sales are going</h2>
          </div>
          {outcomes}
        </section>
      </div>
      <aside className={styles.side} aria-label="Needs you">
        <section
          className={`${styles.block} ${styles.needsBlock}`}
          aria-labelledby="needs-title"
        >
          {/* One card, worst first (owner's chosen lower Home, 05 and 15,
              14 Nov 2026). */}
          <div className={styles.needsCard}>
            <div className={styles.cardHead}>
              <h2 id="needs-title">Needs you now</h2>
              <span className={styles.scope}>
                Team · {side === "cold" ? "Cold" : "Inbound"} · Now
              </span>
            </div>
            {!settled ? (
              <ul className={styles.needs} aria-hidden="true">
                {[0, 1, 2].map((row) => (
                  <li key={row}>
                    <span className={styles.need} data-wait="">
                      <strong />
                      <span />
                    </span>
                  </li>
                ))}
              </ul>
            ) : waiting.length ? (
              <>
                <ul
                  id="needs-list"
                  className={styles.needs}
                  data-open={allNeeds || undefined}
                >
                  {waiting.map((need, index) => (
                    <li key={need.key} data-extra={index >= 3 || undefined}>
                      <Link
                        className={styles.need}
                        href={need.href}
                        data-need={need.key}
                        data-tone={need.tone}
                      >
                        <strong>{need.count.toLocaleString("en-IN")}</strong>
                        <span>
                          {need.label}
                          {need.note ? <small>{need.note}</small> : null}
                        </span>
                        <ChevronRight size={18} aria-hidden="true" />
                      </Link>
                    </li>
                  ))}
                </ul>
                {waiting.length > 3 ? (
                  <button
                    type="button"
                    className={styles.showMore}
                    aria-expanded={allNeeds}
                    aria-controls="needs-list"
                    onClick={() => setAllNeeds((open) => !open)}
                  >
                    {allNeeds ? "Show less" : `Show ${waiting.length - 3} more`}
                    <ChevronDown
                      size={18}
                      aria-hidden="true"
                      data-open={allNeeds || undefined}
                    />
                  </button>
                ) : null}
              </>
            ) : (
              <p className={styles.quiet}>
                {effort && counts ? "Nothing waiting. All clear." : " "}
              </p>
            )}
          </div>
        </section>
        {mine ? <div className={styles.mineBlock}>{mine}</div> : null}
        <section
          className={`${styles.block} ${styles.splitBlock}`}
          aria-labelledby="split-title"
        >
          <div className={styles.head}>
            <h2 id="split-title">
              {chosenDay
                ? `Inbound and Cold · ${dayName(chosenDay)}`
                : "Inbound and Cold today"}
            </h2>
          </div>
          {chosenDay ? (
            <p className={styles.sellersNote}>
              <span>
                {dayName(chosenDay)} · Both lead types · the whole day
              </span>
            </p>
          ) : at ? (
            <p className={styles.sellersNote}>
              <span>Today · Both lead types · As of {CLOCK.format(at)}</span>
            </p>
          ) : null}
          <Split effort={effort} />
        </section>
        {more}
      </aside>
    </div>
  );
}
