"use client";

/**
 * Add task (owner order, 30 Oct 2026, fix 4: the + sheet's Add task opened
 * nothing). One sheet for a promise to keep: what to do, for which lead, when,
 * and whether to be reminded a little early. It opens from the + sheet and
 * from Tasks.
 *
 * The lead is optional (owner's spec, 30 Oct 2026; migration 0147): with no
 * lead the task is your own, on your list. A task on a lead is on the lead
 * owner's list and reminds them (lead_desk/tasks.py): on a teammate's lead it
 * is theirs, and the form says so. The server reminds on the phone once, at
 * the reminder's time (lead_desk/task_push.py); early means 15 minutes before
 * the task, otherwise at its time.
 */

import { CalendarClock, Check, Search } from "lucide-react";
import { useEffect, useId, useState } from "react";

import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { Button } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import { useWorkspaceAccess } from "../workspace-access";
import {
  addOwnTask,
  addTask,
  commandId,
  LeadsError,
  searchDesk,
  type LeadRow,
  type NewTask,
  type TaskKind,
} from "./leads-client";
import {
  daysFrom,
  dueWords,
  kindOf,
  localInput,
  quickTimes,
} from "./task-words";
import styles from "./add-task-sheet.module.css";

/** The kinds a seller adds by hand, the most used first. Tasks are the
    non-calling work (lead_desk/tasks.py CALLING_KINDS): a call back is booked
    as a follow-up, so it is not one of them (persona QA 8417b4d1, 31 Oct 2026). */
const KINDS: readonly TaskKind[] = [
  "whatsapp",
  "meeting",
  "send_file",
  "other",
];

/** "Remind me early": this many minutes before the task; off, at its time. */
export const EARLY_MINUTES = 15;

/** The most leads a search shows. */
const FOUND = 6;

/** The picked time with the day first ("Sat, 1 Nov, 4:00 pm"), whatever the
    phone's language: the native field wrote 11/01/2026 on some phones. */
function whenWords(at: Date, now: Date): string {
  const clock = at.toLocaleTimeString("en-IN", {
    hour: "numeric",
    minute: "2-digit",
  });
  const days = daysFrom(at, now);
  if (days === 0) return `Today, ${clock}`;
  if (days === 1) return `Tomorrow, ${clock}`;
  const day = at.toLocaleDateString("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
  return `${day}, ${clock}`;
}

export type TaskLead = {
  lead_id: string;
  name: string;
  /** Whose list the task goes on: the lead's owner. */
  owner_person_id?: string | null;
  owner_name?: string | null;
};

/** A teammate's lead: the task is theirs (null when it is yours or unknown). */
function theirs(lead: TaskLead, me: string | null): string | null {
  if (!me || !lead.owner_person_id || lead.owner_person_id === me) return null;
  return lead.owner_name ? displayName(lead.owner_name) : "the lead's owner";
}

function LeadPicker({
  lead,
  me,
  onPick,
}: {
  lead: TaskLead | null;
  me: string | null;
  onPick: (lead: TaskLead | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<{ q: string; leads: LeadRow[] } | null>(
    null,
  );
  const words = query.trim();
  useEffect(() => {
    if (lead || words.length < 2) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      searchDesk(words, controller.signal).then(
        (result) => setFound({ q: words, leads: result.leads }),
        () => {
          // A failed search shows nothing; typing again searches again.
        },
      );
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [lead, words]);

  if (lead) {
    const owner = theirs(lead, me);
    return (
      <div className={styles.pickedWrap}>
        <div className={styles.picked}>
          <Check size={16} aria-hidden="true" />
          <span>{displayName(lead.name)}</span>
          <button
            type="button"
            className={styles.textButton}
            onClick={() => onPick(null)}
          >
            Change
          </button>
        </div>
        {owner ? (
          <p className={styles.hint}>
            {owner}&apos;s lead: the task goes on their list and reminds them.
          </p>
        ) : null}
      </div>
    );
  }
  const shown = found && found.q === words ? found.leads.slice(0, FOUND) : null;
  return (
    <div className={styles.picker}>
      <label className={styles.search}>
        <Search size={16} aria-hidden="true" />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search a lead by name or number"
          aria-label="Which lead"
          autoComplete="off"
          enterKeyHint="search"
        />
      </label>
      {shown ? (
        shown.length ? (
          <ul className={styles.found} aria-label="Leads found">
            {shown.map((row) => (
              <li key={row.lead_id}>
                <button
                  type="button"
                  className={styles.foundRow}
                  onClick={() =>
                    onPick({
                      lead_id: row.lead_id,
                      name: row.name,
                      owner_person_id: row.owner_person_id,
                      owner_name: row.owner_name,
                    })
                  }
                >
                  <strong>{displayName(row.name)}</strong>
                  <small>
                    {[
                      row.stage_label,
                      row.phone_last4 && `…${row.phone_last4}`,
                      row.owner_person_id &&
                        row.owner_person_id !== me &&
                        row.owner_name &&
                        `${displayName(row.owner_name)}'s`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </small>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.hint}>No lead matches “{words}”.</p>
        )
      ) : null}
    </div>
  );
}

export function AddTaskSheet({
  open,
  onClose,
  onAdded,
  lead: given = null,
  onOpenTasks,
  now = () => new Date(),
}: {
  open: boolean;
  onClose: () => void;
  /** Saved (or kept on the phone until Sales X-Ray answers): its time. */
  onAdded: (at: Date) => void;
  /** A lead already chosen (opened from a lead). */
  lead?: TaskLead | null;
  /** Where "Open Tasks" in the saved card goes; none where Tasks is open. */
  onOpenTasks?: () => void;
  now?: () => Date;
}) {
  const id = useId();
  const me = useWorkspaceAccess()?.context?.personId ?? null;
  // One command per sheet: Add again after a failure never adds twice.
  const [command] = useState(commandId);
  const [times] = useState(() => quickTimes(now()));
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<TaskKind>(KINDS[0]);
  const [lead, setLead] = useState<TaskLead | null>(given);
  const [at, setAt] = useState<Date>(times[0].at);
  const [early, setEarly] = useState(true);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (busy) return;
    setBusy(true);
    const when = dueWords({ starts_at: at.toISOString() }, now());
    const task: NewTask = {
      kind,
      starts_at: at.toISOString(),
      title: title.trim() || null,
      remind_before_minutes: early ? EARLY_MINUTES : 0,
    };
    try {
      if (lead) await addTask(lead.lead_id, task, command);
      else await addOwnTask(task, command);
      const owner = lead ? theirs(lead, me) : null;
      notify({
        id: "task-added",
        tone: "success",
        title: `Task added for ${when}`,
        message: !lead
          ? "On your list"
          : owner
            ? `${displayName(lead.name)} · on ${owner}'s list`
            : displayName(lead.name),
        ...(onOpenTasks
          ? { action: { label: "Open Tasks", run: onOpenTasks } }
          : {}),
        timeout: 5000,
      });
      onAdded(at);
    } catch (reason) {
      if (reason instanceof LeadsError && reason.kept) {
        notify({
          id: "task-added",
          tone: "info",
          title: `Task kept for ${when}`,
          message: reason.message,
        });
        onAdded(at);
        return;
      }
      notify({
        id: "task-added",
        tone: "error",
        title: "The task wasn't added",
        message:
          reason instanceof LeadsError
            ? reason.message
            : "Sales X-Ray isn't answering. Try again.",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      open={open}
      onClose={() => {
        if (!busy) onClose();
      }}
      title="Add task"
      wide="center"
      footer={
        <Button
          variant="primary"
          className={styles.add}
          disabled={busy}
          onClick={() => void save()}
        >
          {busy ? "Adding…" : "Add task"}
        </Button>
      }
    >
      <div className={styles.form}>
        <label className={styles.field}>
          <span>What to do</span>
          <input
            type="text"
            value={title}
            maxLength={200}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Send the brochure"
            autoComplete="off"
          />
        </label>
        <div className={styles.chips} role="group" aria-label="Kind">
          {KINDS.map((key) => {
            const item = kindOf(key);
            const Icon = item.icon;
            return (
              <button
                key={key}
                type="button"
                className={styles.chip}
                aria-pressed={kind === key}
                onClick={() => setKind(key)}
              >
                <Icon size={15} aria-hidden="true" />
                {item.label}
              </button>
            );
          })}
        </div>

        <div className={styles.field}>
          <span>For which lead (optional)</span>
          <LeadPicker lead={lead} me={me} onPick={setLead} />
        </div>

        <div className={styles.field}>
          <span id={`${id}-when`}>When</span>
          <div
            className={styles.chips}
            role="group"
            aria-labelledby={`${id}-when`}
          >
            {times.map((time) => (
              <button
                key={time.key}
                type="button"
                className={styles.chip}
                aria-pressed={time.at.getTime() === at.getTime()}
                onClick={() => setAt(time.at)}
              >
                {time.label}
              </button>
            ))}
          </div>
          {/* Our words over the phone's own picker: a tap opens its calendar. */}
          <label className={styles.when}>
            <CalendarClock size={16} aria-hidden="true" />
            <span>{whenWords(at, now())}</span>
            <input
              type="datetime-local"
              className={styles.whenInput}
              aria-label="Date and time"
              value={localInput(at)}
              onClick={(event) => {
                try {
                  event.currentTarget.showPicker();
                } catch {
                  // Older phones have no showPicker; they open it on the tap.
                }
              }}
              onChange={(event) => {
                const picked = new Date(event.target.value);
                if (!Number.isNaN(picked.getTime())) setAt(picked);
              }}
            />
          </label>
        </div>

        <label className={styles.switch}>
          <span className={styles.switchWords}>
            <strong>Remind me {EARLY_MINUTES} minutes early</strong>
          </span>
          <input
            type="checkbox"
            role="switch"
            checked={early}
            onChange={(event) => setEarly(event.target.checked)}
          />
        </label>
      </div>
    </Sheet>
  );
}
