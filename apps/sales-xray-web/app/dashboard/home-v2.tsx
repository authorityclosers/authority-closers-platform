"use client";

/**
 * Home that is worth opening (owner, 27 Oct 2026: Home is "an ugly screen"
 * for an existing user and for a new one; a returning user should see data
 * they recognise, a new user "something very interesting").
 *
 * A returning seller sees, before Today: where they left off (the lead or
 * Report they last opened on this phone) and their last calls, phone and
 * saved, each one tap to open; after Today, their recent activity on leads
 * (notes, stage moves, outcomes, meetings, messages). A brand-new workspace
 * sees a short start: three steps with progress, a sample report to open and
 * one clear first action. Every number shown is real; the sample is labelled.
 */

import {
  ArrowRightLeft,
  AudioLines,
  CalendarClock,
  Check,
  ChevronRight,
  Clock,
  FileUp,
  MessageCircle,
  NotebookPen,
  Phone,
  PhoneCall,
  Sparkles,
  UserPlus,
  UserRound,
  UsersRound,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";

import { callHref, type LibrarySubmission } from "../acquisition-client";
import {
  CallRows,
  mergeCalls,
  rowFromActivity,
  rowFromSaved,
  shortWhen,
  weekCalls,
  type WeekActivity,
} from "../calls/call-rows";
import { CallRowsSkeleton } from "../calls/phone-calls";
import { displayName } from "../display-name";
import { eventText } from "../leads/lead-sheet";
import { handOverLead } from "../leads/lead-handoff";
import { ago, type ActivityItem } from "../leads/leads-client";
import { callLogStatus, inPhoneApp } from "../leads/native-phone";
import { useWorkspaceAccess } from "../workspace-access";
import styles from "./home-v2.module.css";
import homeStyles from "./sales-home.module.css";

/* ---------- Pick up where you left off ---------- */

const PICK_UP_KEY = "sx-pick-up";
const PICK_UP_DAYS = 3;
const PICK_UP_EVENT = "sx:pick-up";

export type Opened = {
  kind: "lead" | "call";
  id: string;
  name: string;
  at: string;
  person: string;
  tenant: string;
};

/** The lead or Report this person last opened here, kept on this device only. */
export function rememberOpened(
  item: Omit<Opened, "at">,
  now: Date = new Date(),
): void {
  try {
    localStorage.setItem(
      PICK_UP_KEY,
      JSON.stringify({ ...item, at: now.toISOString() }),
    );
    window.dispatchEvent(new Event(PICK_UP_EVENT));
  } catch {
    // Storage blocked: nothing to pick up next time.
  }
}

/** The thing to pick up, if it is this person's, here, and recent. */
export function pickUpFrom(
  raw: string | null,
  who: { person: string; tenant: string } | null,
  now: Date = new Date(),
): Opened | null {
  if (!raw || !who) return null;
  try {
    const value = JSON.parse(raw) as Partial<Opened>;
    if (
      (value.kind !== "lead" && value.kind !== "call") ||
      typeof value.id !== "string" ||
      typeof value.name !== "string" ||
      typeof value.at !== "string" ||
      value.person !== who.person ||
      value.tenant !== who.tenant
    )
      return null;
    const age = now.getTime() - Date.parse(value.at);
    if (!(age >= 0 && age < PICK_UP_DAYS * 86_400_000)) return null;
    return value as Opened;
  } catch {
    return null;
  }
}

const readPickUp = () => {
  try {
    return localStorage.getItem(PICK_UP_KEY);
  } catch {
    return null;
  }
};

const onPickUp = (change: () => void) => {
  window.addEventListener(PICK_UP_EVENT, change);
  window.addEventListener("storage", change);
  return () => {
    window.removeEventListener(PICK_UP_EVENT, change);
    window.removeEventListener("storage", change);
  };
};

export function PickUp() {
  const router = useRouter();
  const access = useWorkspaceAccess();
  const raw = useSyncExternalStore(onPickUp, readPickUp, () => null);
  const who = access?.context
    ? { person: access.context.personId, tenant: access.context.tenantId }
    : null;
  const item = pickUpFrom(raw, who);
  if (!item) return null;
  const lead = item.kind === "lead";
  const Icon = lead ? UserRound : AudioLines;
  return (
    <section className={styles.pickUp} aria-label="Pick up where you left off">
      <Link
        className={styles.pickUpRow}
        href={lead ? "/leads" : callHref(item.id)}
        data-sx-action={lead ? "lead_open" : "report_open"}
        onClick={(click) => {
          if (!lead) return;
          click.preventDefault();
          handOverLead(item.id);
          router.push("/leads");
        }}
      >
        <span className={styles.tile} data-kind={item.kind} aria-hidden="true">
          <Icon size={18} />
        </span>
        <span className={styles.words}>
          <small>Pick up where you left off</small>
          <strong>{lead ? displayName(item.name) : item.name}</strong>
          <span>
            {lead ? "Lead" : "Report"} you opened {ago(item.at)}
          </span>
        </span>
        <ChevronRight size={18} aria-hidden="true" />
      </Link>
    </section>
  );
}

/* ---------- Recent calls ---------- */

/** Calls on Home; the rest are on Calls. */
export const RECENT_CALLS = 3;

export function HomeRecentCalls({
  week,
  saved,
}: {
  week: WeekActivity;
  /** The latest saved calls Home already reads, or null while unknown. */
  saved: readonly LibrarySubmission[] | null;
}) {
  const [now] = useState(() => new Date());
  if (week.status === "off" || week.status === "error") return null;
  const rows =
    week.status === "ready"
      ? mergeCalls(
          weekCalls(week.items).map(rowFromActivity),
          (saved ?? []).map(rowFromSaved),
        ).slice(0, RECENT_CALLS)
      : [];
  if (week.status === "ready" && rows.length === 0) return null;
  return (
    <section className={homeStyles.block} aria-labelledby="recent-calls-title">
      <div className={homeStyles.head}>
        <h2 id="recent-calls-title">Recent calls</h2>
        <Link className={styles.more} href="/analysis/calls">
          All calls
          <ChevronRight size={16} aria-hidden="true" />
        </Link>
      </div>
      {week.status === "loading" ? (
        <CallRowsSkeleton label="Recent calls" />
      ) : (
        <CallRows
          rows={rows}
          now={now}
          days={false}
          label="Recent calls, newest first"
        />
      )}
    </section>
  );
}

/* ---------- Recent activity ---------- */

export const RECENT_ACTIVITY = 4;

const ACTIVITY_ICONS: Record<string, LucideIcon> = {
  result: Phone,
  note: NotebookPen,
  stage: ArrowRightLeft,
  meeting: CalendarClock,
  message: MessageCircle,
  scheduled: Clock,
  assigned: UserPlus,
  reassigned: UserPlus,
  captured: Sparkles,
};

/** What happened on your leads lately, apart from the calls themselves. */
export function activityItems(week: WeekActivity): ActivityItem[] {
  if (week.status !== "ready") return [];
  return week.items.filter((item) => item.event.kind !== "call");
}

/** A line in the seller's own words; what someone else did keeps their name. */
export function activityLine(item: ActivityItem): string {
  const own = !["assigned", "reassigned", "captured"].includes(item.event.kind);
  return eventText(own ? { ...item.event, actor_name: "You" } : item.event)
    .title;
}

export function HomeActivity({ week }: { week: WeekActivity }) {
  const router = useRouter();
  const [now] = useState(() => new Date());
  const items = activityItems(week).slice(0, RECENT_ACTIVITY);
  if (week.status !== "ready" || items.length === 0) return null;
  return (
    <section className={homeStyles.block} aria-labelledby="activity-title">
      <div className={homeStyles.head}>
        <h2 id="activity-title">Recent activity</h2>
        <Link className={styles.more} href="/leads?tab=work">
          My work
          <ChevronRight size={16} aria-hidden="true" />
        </Link>
      </div>
      <ol
        className={styles.activity}
        aria-label="Recent activity, newest first"
      >
        {items.map((item) => {
          const Icon = ACTIVITY_ICONS[item.event.kind] ?? Clock;
          return (
            <li key={item.event_id}>
              <Link
                className={styles.activityRow}
                href="/leads"
                data-lead-row=""
                onClick={(click) => {
                  click.preventDefault();
                  handOverLead(item.lead_id, false, item.event.at);
                  router.push("/leads");
                }}
              >
                <span
                  className={styles.dot}
                  data-kind={item.event.kind}
                  aria-hidden="true"
                >
                  <Icon size={15} />
                </span>
                <span className={styles.words}>
                  <strong>{displayName(item.lead_name)}</strong>
                  <span>{activityLine(item)}</span>
                </span>
                <time dateTime={item.event.at}>
                  {shortWhen(item.event.at, now)}
                </time>
              </Link>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/* ---------- A new workspace's start ---------- */

type StartDesk = {
  counts: { open: number };
  numbers: { calls: number };
  numbers_week?: { calls: number } | null;
  team_pool?: { open: number } | null;
};

export type StartStep = {
  key: "phone" | "leads" | "call" | "team";
  title: string;
  hint: string;
  href: string;
  icon: LucideIcon;
  done: boolean;
};

/** The first steps and whether each is done, from what the desk already says. */
export function startSteps(
  desk: StartDesk,
  phone: { inApp: boolean; logging: boolean },
  manager: boolean,
): StartStep[] {
  const steps: StartStep[] = [
    {
      key: "phone",
      title: phone.inApp ? "Connect your phone calls" : "Get the phone app",
      hint: phone.inApp
        ? "See who you called, missed calls too"
        : "Calls and recordings log themselves",
      href: "/leads#phone-setup",
      icon: PhoneCall,
      done: phone.logging,
    },
    {
      key: "leads",
      title: "Add your leads",
      hint: "Import a sheet, or add one by hand",
      href: "/leads?import=file",
      icon: FileUp,
      done: desk.counts.open > 0 || (desk.team_pool?.open ?? 0) > 0,
    },
    {
      key: "call",
      title: "Make your first call",
      hint: "Tap Call on a lead; we log it",
      href: "/leads",
      icon: Phone,
      done: desk.numbers.calls > 0 || (desk.numbers_week?.calls ?? 0) > 0,
    },
  ];
  if (manager)
    steps.push({
      key: "team",
      title: "Add your team",
      hint: "Invite your sellers",
      href: "/organisation?tab=team",
      icon: UsersRound,
      done: false,
    });
  return steps;
}

/** One proportion as a ring: the share of steps done (rule 13). */
function StartRing({ done, total }: { done: number; total: number }) {
  const r = 22;
  const length = 2 * Math.PI * r;
  return (
    <span
      className={styles.ring}
      role="img"
      aria-label={`${done} of ${total} done`}
    >
      <svg viewBox="0 0 56 56" aria-hidden="true">
        <circle className={styles.ringTrack} cx="28" cy="28" r={r} />
        {/* Nothing done draws no fill: a round cap alone reads as a dot. */}
        {done > 0 ? (
          <circle
            className={styles.ringFill}
            cx="28"
            cy="28"
            r={r}
            strokeDasharray={`${(done / total) * length} ${length}`}
          />
        ) : null}
      </svg>
      <span aria-hidden="true">
        {done}/{total}
      </span>
    </span>
  );
}

/** Whether this phone already logs work calls; false in a browser. */
function usePhoneLogging(): { inApp: boolean; logging: boolean } {
  const [state, setState] = useState({ inApp: false, logging: false });
  useEffect(() => {
    if (!inPhoneApp()) return;
    let alive = true;
    void callLogStatus().then((status) => {
      if (alive)
        setState({
          inApp: true,
          logging: Boolean(status?.access && status.state !== "signed_out"),
        });
    });
    return () => {
      alive = false;
    };
  }, []);
  return state;
}

export const SAMPLE_REPORT_HREF = "/analysis/sample";

export function SetupStart({
  desk,
  manager,
}: {
  desk: StartDesk;
  manager: boolean;
}) {
  const phone = usePhoneLogging();
  const steps = startSteps(desk, phone, manager);
  const done = steps.filter((step) => step.done).length;
  return (
    <div className={styles.start}>
      <section className={styles.steps} aria-labelledby="start-title">
        <header className={styles.startHead}>
          <span>
            <h2 id="start-title">Let&apos;s get you calling</h2>
            <small>
              {steps.length} steps, about five minutes. Each one is a tap away.
            </small>
          </span>
          <StartRing done={done} total={steps.length} />
        </header>
        <ol>
          {steps.map((step) => {
            const Icon = step.icon;
            return (
              <li key={step.key}>
                <Link
                  className={styles.step}
                  href={step.href}
                  prefetch={false}
                  data-done={step.done ? "" : undefined}
                >
                  <span className={styles.stepIcon} aria-hidden="true">
                    {step.done ? <Check size={18} /> : <Icon size={18} />}
                  </span>
                  <span className={styles.words}>
                    <strong>{step.title}</strong>
                    <span>{step.done ? "Done" : step.hint}</span>
                  </span>
                  <ChevronRight size={18} aria-hidden="true" />
                </Link>
              </li>
            );
          })}
        </ol>
      </section>
      <Link
        className={styles.sample}
        href={SAMPLE_REPORT_HREF}
        prefetch={false}
        data-sx-action="report_open"
      >
        <span className={styles.sampleArt} aria-hidden="true">
          <AudioLines size={26} />
        </span>
        <span className={styles.words}>
          <small>Sample</small>
          <strong>See what a call report shows</strong>
          <span>
            Who talked most, the next step agreed and what to say next time
          </span>
        </span>
        <ChevronRight size={18} aria-hidden="true" />
      </Link>
      <Link className={homeStyles.primary} href="/leads#add=lead">
        <UserPlus size={18} aria-hidden="true" />
        Add your first lead
      </Link>
    </div>
  );
}
