"use client";

/**
 * Team controls (owner, 31 Oct 2026: "what settings would immediately matter
 * to an owner?"): one sheet of cards, each showing its value; one tap opens
 * its detail. No tabs and no list of every seller: an exception to a team rule
 * is picked inside its card ("Except…").
 *
 * 1. Working hours & breaks: they drive late, overdue and break detection.
 * 2. First call on new enquiries: the first-response target (5-30 minutes).
 * 3. Seller nudges: on for everyone, except the sellers picked.
 * 4. Alert me when an enquiry waits past the first-call limit.
 * 5. The month's revenue target.
 *
 * Only what works is here (the owner's rule, no dead ends; Dipak, ph1-19,
 * 1 Nov 2026): the idle and no-recording alerts and the 7 PM summary come
 * back when the server does them.
 */

import {
  AlarmClock,
  BellRing,
  ChevronLeft,
  ChevronRight,
  Clock3,
  PhoneIncoming,
  Plus,
  Settings2,
  X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { displayName } from "../display-name";
import { notify } from "../notice-center";
import {
  readTeam,
  saveWorkHours,
  type Team,
  type WorkHours,
} from "../leads/leads-client";
import { saveNudges, type NudgeSettings } from "../leads/team-engine-client";
import { waCall, type Sla } from "../leads/whatsapp-client";
import { Sheet } from "../ui/sheet";
import { RevenueTargetCard, RevenueTargetDetail } from "./revenue-target-card";
import styles from "./team-controls.module.css";

type Card = "hours" | "first_call" | "nudges" | "alerts" | "revenue";
type Loaded = { team: Team; sla: Sla | null };

const TITLES: Record<Card, string> = {
  hours: "Working hours & breaks",
  first_call: "First call on new enquiries",
  nudges: "Seller nudges",
  alerts: "Alert me when…",
  revenue: "Monthly revenue target",
};

/** First-call limits an owner picks from (the server takes 5 to 120). */
const LIMITS = [5, 10, 15, 30] as const;
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
/** The owner's day when none is set yet: 10:30 to 7:00, lunch 1:30 to 2:15. */
const USUAL = {
  days: [0, 1, 2, 3, 4, 5],
  start: "10:30",
  end: "19:00",
  pause_leads: false,
  breaks: [{ start: "13:30", end: "14:15" }],
};

/** "19:00" as "7:00", the way the team says it. */
const clock = (value: string) => {
  const [hours, minutes] = value.split(":").map(Number);
  return `${hours % 12 || 12}:${String(minutes).padStart(2, "0")}`;
};

/** The team and the first-call target, read when the sheet opens. */
function useControls(open: boolean, round: number) {
  const [state, setState] = useState<Loaded | "error" | null>(null);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    Promise.all([
      readTeam(controller.signal),
      waCall<Sla>("/sla", { signal: controller.signal }).catch(() => null),
    ])
      .then(([team, sla]) => setState({ team, sla }))
      .catch(() => {
        if (!controller.signal.aborted) setState("error");
      });
    return () => controller.abort();
  }, [open, round]);
  return state;
}

function Toggle({
  label,
  on,
  onChange,
  disabled = false,
}: {
  label: string;
  on: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      className={styles.toggle}
      onClick={() => onChange(!on)}
    >
      <span aria-hidden="true" />
    </button>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={styles.row}>
      <span className={styles.rowLabel}>{label}</span>
      {children}
    </div>
  );
}

const failed = (title: string) =>
  notify({
    id: "team-controls",
    tone: "error",
    title,
    message: "Someone may have changed it just now. Try again.",
  });

function HoursDetail({
  team,
  onSaved,
}: {
  team: Team;
  onSaved: (next: Team) => void;
}) {
  const set: WorkHours | null | undefined = team.settings.work_hours;
  const [days, setDays] = useState<number[]>(set?.days ?? USUAL.days);
  const [start, setStart] = useState(set?.start ?? USUAL.start);
  const [end, setEnd] = useState(set?.end ?? USUAL.end);
  const [breaks, setBreaks] = useState(set ? (set.breaks ?? []) : USUAL.breaks);
  const [pause, setPause] = useState(set?.pause_leads ?? false);
  const [busy, setBusy] = useState(false);
  const valid =
    days.length > 0 &&
    start < end &&
    breaks.every(
      (gap) => gap.start < gap.end && gap.start >= start && gap.end <= end,
    );
  const save = async () => {
    setBusy(true);
    try {
      onSaved(
        await saveWorkHours(team.settings.revision, {
          days,
          start,
          end,
          pause_leads: pause,
          breaks,
        }),
      );
      notify({
        id: "team-controls",
        tone: "success",
        title: "Working hours saved",
        timeout: 4_000,
      });
    } catch {
      failed("Working hours weren't saved");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={styles.detail}>
      <div className={styles.days} role="group" aria-label="Work days">
        {DAYS.map((name, index) => (
          <button
            key={name}
            type="button"
            aria-pressed={days.includes(index)}
            className={styles.day}
            onClick={() =>
              setDays((now) =>
                now.includes(index)
                  ? now.filter((day) => day !== index)
                  : [...now, index].sort(),
              )
            }
          >
            {name}
          </button>
        ))}
      </div>
      <Row label="Starts">
        <input
          type="time"
          className={styles.time}
          value={start}
          onChange={(event) => setStart(event.target.value)}
          aria-label="Work starts"
        />
      </Row>
      <Row label="Ends">
        <input
          type="time"
          className={styles.time}
          value={end}
          onChange={(event) => setEnd(event.target.value)}
          aria-label="Work ends"
        />
      </Row>
      {breaks.map((gap, index) => (
        <Row key={index} label={index === 0 ? "Lunch" : "Break"}>
          <span className={styles.span}>
            <input
              type="time"
              className={styles.time}
              value={gap.start}
              aria-label={`Break ${index + 1} starts`}
              onChange={(event) =>
                setBreaks((now) =>
                  now.map((item, at) =>
                    at === index
                      ? { ...item, start: event.target.value }
                      : item,
                  ),
                )
              }
            />
            <span aria-hidden="true">–</span>
            <input
              type="time"
              className={styles.time}
              value={gap.end}
              aria-label={`Break ${index + 1} ends`}
              onChange={(event) =>
                setBreaks((now) =>
                  now.map((item, at) =>
                    at === index ? { ...item, end: event.target.value } : item,
                  ),
                )
              }
            />
            <button
              type="button"
              className={styles.remove}
              aria-label={`Remove break ${index + 1}`}
              onClick={() =>
                setBreaks((now) => now.filter((_, at) => at !== index))
              }
            >
              <X size={16} aria-hidden="true" />
            </button>
          </span>
        </Row>
      ))}
      {breaks.length < 3 ? (
        <button
          type="button"
          className={styles.add}
          onClick={() =>
            setBreaks((now) => [...now, { start: "16:00", end: "16:15" }])
          }
        >
          <Plus size={16} aria-hidden="true" />
          Add a break
        </button>
      ) : null}
      <Row label="Hold new leads outside these hours">
        <Toggle
          label="Hold new leads outside these hours"
          on={pause}
          onChange={setPause}
        />
      </Row>
      <button
        type="button"
        className={styles.save}
        disabled={!valid || busy}
        onClick={() => void save()}
      >
        {busy ? "Saving…" : set ? "Save hours" : "Use these hours"}
      </button>
    </div>
  );
}

function FirstCallDetail({
  sla,
  onSaved,
}: {
  sla: Sla;
  onSaved: (next: Sla) => void;
}) {
  const [busy, setBusy] = useState(false);
  const save = async (next: Pick<Sla, "on" | "minutes" | "alertManagers">) => {
    setBusy(true);
    try {
      onSaved(
        await waCall<Sla>("/sla", {
          method: "PUT",
          body: JSON.stringify(next),
        }),
      );
    } catch {
      failed("The first-call limit wasn't saved");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={styles.detail}>
      <Row label="A limit for the first call">
        <Toggle
          label="A limit for the first call"
          on={sla.on}
          disabled={busy}
          onChange={(on) =>
            void save({
              on,
              minutes: sla.minutes,
              alertManagers: sla.alertManagers,
            })
          }
        />
      </Row>
      <div
        className={styles.choices}
        role="radiogroup"
        aria-label="Call new enquiries within"
      >
        {LIMITS.map((minutes) => (
          <button
            key={minutes}
            type="button"
            role="radio"
            aria-checked={sla.on && sla.minutes === minutes}
            disabled={busy}
            className={styles.choice}
            onClick={() =>
              void save({ on: true, minutes, alertManagers: sla.alertManagers })
            }
          >
            {`${minutes} min`}
          </button>
        ))}
      </div>
    </div>
  );
}

function NudgesDetail({
  team,
  onSaved,
}: {
  team: Team;
  onSaved: (next: Team) => void;
}) {
  const settings = team.settings as NudgeSettings;
  const on = settings.nudges !== false;
  const offFor = settings.nudges_off_for ?? [];
  const [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState(false);
  const save = async (enabled: boolean, off: string[]) => {
    setBusy(true);
    try {
      onSaved(await saveNudges(settings.revision, enabled, off));
    } catch {
      failed("Nudges weren't changed");
    } finally {
      setBusy(false);
    }
  };
  const except = team.reps.filter((rep) => offFor.includes(rep.person_id));
  const others = team.reps.filter((rep) => !offFor.includes(rep.person_id));
  return (
    <div className={styles.detail}>
      <Row label="Nudge sellers who fall behind">
        <Toggle
          label="Nudge sellers who fall behind"
          on={on}
          disabled={busy}
          onChange={(next) => void save(next, offFor)}
        />
      </Row>
      {on ? (
        <div className={styles.except}>
          <span className={styles.rowLabel}>Except…</span>
          <ul className={styles.people}>
            {except.map((rep) => (
              <li key={rep.person_id}>
                {displayName(rep.name)}
                <button
                  type="button"
                  aria-label={`Nudge ${displayName(rep.name)} again`}
                  disabled={busy}
                  onClick={() =>
                    void save(
                      true,
                      offFor.filter((id) => id !== rep.person_id),
                    )
                  }
                >
                  <X size={14} aria-hidden="true" />
                </button>
              </li>
            ))}
            {others.length ? (
              <li>
                <button
                  type="button"
                  className={styles.add}
                  aria-expanded={picking}
                  onClick={() => setPicking((now) => !now)}
                >
                  <Plus size={16} aria-hidden="true" />
                  Pick a seller
                </button>
              </li>
            ) : null}
          </ul>
          {picking ? (
            <ul className={styles.pick} aria-label="Sellers">
              {others.map((rep) => (
                <li key={rep.person_id}>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setPicking(false);
                      void save(true, [...offFor, rep.person_id]);
                    }}
                  >
                    {displayName(rep.name)}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function AlertsDetail({
  sla,
  onSaved,
  onFirstCall,
}: {
  sla: Sla | null;
  onSaved: (next: Sla) => void;
  /** Opens First call on new enquiries, where the limit is set. */
  onFirstCall: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const live = !!sla?.on;
  const alertMe = async (alertManagers: boolean) => {
    if (!sla) return;
    setBusy(true);
    try {
      onSaved(
        await waCall<Sla>("/sla", {
          method: "PUT",
          body: JSON.stringify({
            on: sla.on,
            minutes: sla.minutes,
            alertManagers,
          }),
        }),
      );
    } catch {
      failed("The alert wasn't changed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={styles.detail}>
      <Row label="An enquiry waits past the first-call limit">
        <Toggle
          label="An enquiry waits past the first-call limit"
          on={live && !!sla?.alertManagers}
          disabled={!sla || !live || busy}
          onChange={(next) => void alertMe(next)}
        />
      </Row>
      {sla && !live ? (
        <p className={styles.hint}>
          <button
            type="button"
            className={styles.hintLink}
            onClick={onFirstCall}
          >
            Set a first-call limit
          </button>{" "}
          to use this.
        </p>
      ) : null}
    </div>
  );
}

export function TeamControls() {
  const [open, setOpen] = useState(false);
  const [card, setCard] = useState<Card | null>(null);
  const [round, setRound] = useState(0);
  const state = useControls(open, round);
  const [team, setTeam] = useState<Team | null>(null);
  const [sla, setSla] = useState<Sla | null>(null);
  const loaded = state && state !== "error" ? state : null;
  const shownTeam = team ?? loaded?.team ?? null;
  const shownSla = sla ?? loaded?.sla ?? null;
  const close = () => {
    setOpen(false);
    setCard(null);
    setTeam(null);
    setSla(null);
  };
  const hours = shownTeam?.settings.work_hours;
  const settings = shownTeam?.settings as NudgeSettings | undefined;
  const nudgesOn = settings ? settings.nudges !== false : false;
  const except = settings?.nudges_off_for?.length ?? 0;
  const alertsOn = shownSla?.on && shownSla.alertManagers ? 1 : 0;
  const cards: {
    key: Card;
    icon: ReactNode;
    value: string;
    tone?: "off";
  }[] = [
    {
      key: "hours",
      icon: <Clock3 size={20} />,
      value: hours
        ? `${clock(hours.start)}–${clock(hours.end)}${
            hours.breaks?.[0]
              ? ` · lunch ${clock(hours.breaks[0].start)}–${clock(hours.breaks[0].end)}`
              : ""
          }`
        : "Not set",
      tone: hours ? undefined : "off",
    },
    {
      key: "first_call",
      icon: <PhoneIncoming size={20} />,
      value: shownSla?.on ? `Within ${shownSla.minutes} min` : "Off",
      tone: shownSla?.on ? undefined : "off",
    },
    {
      key: "nudges",
      icon: <BellRing size={20} />,
      value: nudgesOn
        ? except
          ? `On, except ${except}`
          : "On for everyone"
        : "Off",
      tone: nudgesOn ? undefined : "off",
    },
    {
      key: "alerts",
      icon: <AlarmClock size={20} />,
      value: alertsOn ? "On" : "Off",
      tone: alertsOn ? undefined : "off",
    },
  ];
  return (
    <>
      <button
        type="button"
        className={styles.gear}
        aria-haspopup="dialog"
        onClick={() => {
          setOpen(true);
          setRound((value) => value + 1);
        }}
      >
        <Settings2 size={18} aria-hidden="true" />
        Controls
      </button>
      <Sheet
        open={open}
        onClose={close}
        title={card ? TITLES[card] : "Team controls"}
      >
        {state === "error" ? (
          <p className={styles.quiet} role="status">
            The team didn&apos;t load. Close this and try again in a moment.
          </p>
        ) : !loaded || !shownTeam ? (
          <div className={styles.loading} aria-busy="true" />
        ) : card === null ? (
          <ul className={styles.cards}>
            {cards.map((item, index) => (
              <li key={item.key} style={{ animationDelay: `${index * 40}ms` }}>
                <button
                  type="button"
                  className={styles.card}
                  data-control={item.key}
                  onClick={() => setCard(item.key)}
                >
                  <span className={styles.icon} aria-hidden="true">
                    {item.icon}
                  </span>
                  <span className={styles.cardTitle}>{TITLES[item.key]}</span>
                  <span className={styles.chip} data-tone={item.tone}>
                    {item.value}
                  </span>
                  <ChevronRight
                    className={styles.chevron}
                    size={18}
                    aria-hidden="true"
                  />
                </button>
              </li>
            ))}
            {/* The month's revenue target: capture-setup's card. */}
            <li>
              <RevenueTargetCard onOpen={() => setCard("revenue")} />
            </li>
          </ul>
        ) : (
          <div className={styles.page}>
            <button
              type="button"
              className={styles.back}
              onClick={() => setCard(null)}
            >
              <ChevronLeft size={18} aria-hidden="true" />
              Team controls
            </button>
            {card === "hours" ? (
              <HoursDetail team={shownTeam} onSaved={setTeam} />
            ) : card === "first_call" ? (
              shownSla ? (
                <FirstCallDetail sla={shownSla} onSaved={setSla} />
              ) : (
                <p className={styles.quiet}>
                  The first-call limit didn&apos;t load. Try again in a moment.
                </p>
              )
            ) : card === "nudges" ? (
              <NudgesDetail team={shownTeam} onSaved={setTeam} />
            ) : card === "alerts" ? (
              <AlertsDetail
                sla={shownSla}
                onSaved={setSla}
                onFirstCall={() => setCard("first_call")}
              />
            ) : (
              <RevenueTargetDetail />
            )}
          </div>
        )}
      </Sheet>
    </>
  );
}
