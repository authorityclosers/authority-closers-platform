"use client";

import { Check, ChevronDown, Play } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import {
  NEXT_STEP_FIRMNESS,
  NUMBER_MEANINGS,
  useCallFacts,
} from "./call-facts";
import { numbersHeard, priceTalk, timePromise, voicesOf } from "./call-data";
import { formatClock } from "./lightbox/time";
import type { SalesReport, Transcript } from "./report-contract";
import { getShellState } from "./shell/shell-store";
import { SPEAKER_ICONS } from "./speaker-icons";
import {
  ROLE_WORDS,
  speakerName,
  useSpeakerProfiles,
} from "./speaker-profiles";
import styles from "./key-facts.module.css";
import { useReportDocument } from "./report-reading-context";

const INDUSTRIES = SPEAKER_ICONS.filter((icon) => !icon.generic);

function Heard({ ms, onSeek }: { ms: number; onSeek: (ms: number) => void }) {
  const documentView = useReportDocument();
  if (documentView)
    return <span className={styles.heard}>{formatClock(ms)}</span>;
  return (
    <button
      type="button"
      className={styles.heard}
      onClick={() => onSeek(ms)}
      aria-label={`Play from ${formatClock(ms)}`}
    >
      <Play size={11} aria-hidden="true" />
      {formatClock(ms)}
    </button>
  );
}

function Row({
  label,
  value,
  status,
}: {
  label: string;
  value: ReactNode;
  status: ReactNode;
}) {
  return (
    <div className={styles.row}>
      <span className={styles.label}>{label}</span>
      <span className={styles.value}>{value}</span>
      <span className={styles.status}>{status}</span>
    </div>
  );
}

// Short names for the firmness steps; the saved value stays the full one.
const FIRMNESS_SHORT: Record<string, string> = {
  "No next step": "None",
  "Loose: no time set": "Loose",
  "A call with a set time": "Time set",
  "Invite sent": "Invite sent",
  "Committed or paid": "Committed",
};

/** A chip that opens a small panel of choices; tap one to pick it. */
function ChipPicker({
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string;
  value: string | undefined;
  options: readonly string[];
  disabled?: boolean;
  onChange: (value: string | null) => void;
}) {
  const documentView = useReportDocument();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  if (documentView) return <span>{value ?? "Not labelled"}</span>;
  return (
    <div ref={box} className={styles.picker}>
      <button
        type="button"
        className={styles.pickerChip}
        data-set={value ? "" : undefined}
        aria-label={label}
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        {value ?? "What is it?"}
        <ChevronDown size={13} aria-hidden="true" />
      </button>
      {open ? (
        <div className={styles.pickerMenu} role="group" aria-label={label}>
          {options.map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={option === value}
              onClick={() => {
                onChange(option === value ? null : option);
                setOpen(false);
              }}
            >
              {option}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Confirmed({ children = "Confirmed" }: { children?: ReactNode }) {
  return (
    <span className={styles.ok}>
      <Check size={13} aria-hidden="true" />
      {children}
    </span>
  );
}

/**
 * The call's key facts, each shown with how sure we are: ✓ when you confirmed
 * it, "Is this right?" when it was only heard or guessed, and "add it" when
 * the call never said it. Everything shown comes from this call's transcript
 * or report; nothing is invented.
 */
export function KeyFacts({
  callId,
  transcript,
  report,
  durationMs,
  onSeek,
}: {
  callId: string | null;
  transcript: Transcript;
  report: SalesReport;
  durationMs: number;
  onSeek: (ms: number) => void;
}) {
  const documentView = useReportDocument();
  const { facts, save, canSave: writable } = useCallFacts(callId);
  const canSave = writable && !documentView;
  const { profiles } = useSpeakerProfiles(callId);
  const accountName = getShellState().profileName;
  const [editingState, setEditing] = useState<string | null>(null);
  const editing = documentView ? null : editingState;
  const [draft, setDraft] = useState("");

  const voices = useMemo(() => voicesOf(transcript), [transcript]);
  const promise = useMemo(() => timePromise(transcript), [transcript]);
  const price = useMemo(() => priceTalk(transcript), [transcript]);
  const numbers = useMemo(() => {
    // The same number in the same line counts once.
    const seen = new Set<string>();
    return numbersHeard(transcript).filter((number) => {
      const key = `${number.segment.id}:${number.spoken}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return number.kind === "money" || number.kind === "percent";
    });
  }, [transcript]);
  const nameOf = (id: string) =>
    speakerName(voices.indexOf(id), profiles[id], accountName);
  const people = voices
    .filter((id) => profiles[id]?.name.trim() || profiles[id]?.role)
    .map((id) => {
      const profile = profiles[id]!;
      const name = profile.name.trim() || nameOf(id);
      return profile.role
        ? `${name} (${ROLE_WORDS[profile.role].toLowerCase()})`
        : name;
    });
  const industry = facts.values.industry?.trim() || null;
  const priceHasAmount = price.some((segment) =>
    numbers.some((number) => number.segment.id === segment.id),
  );

  function startEdit(id: string, value = "") {
    setEditing(id);
    setDraft(value);
  }
  function commit(id: string) {
    save({ kind: "value", id, value: draft });
    save({ kind: "confirm", id, value: true });
    setEditing(null);
  }
  const ask = (id: string, onYes?: () => void) =>
    canSave ? (
      <span className={styles.ask}>
        Is this right?
        <button
          type="button"
          onClick={() => {
            onYes?.();
            save({ kind: "confirm", id, value: true });
          }}
        >
          Yes
        </button>
        <button type="button" onClick={() => startEdit(id)}>
          Fix
        </button>
      </span>
    ) : null;
  const add = (id: string, text = "Add it") =>
    canSave ? (
      <button
        type="button"
        className={styles.add}
        onClick={() => startEdit(id)}
      >
        {text}
      </button>
    ) : null;
  const editor = (id: string, placeholder: string) => (
    <form
      className={styles.editor}
      onSubmit={(event) => {
        event.preventDefault();
        commit(id);
      }}
    >
      <input
        autoFocus
        value={draft}
        placeholder={placeholder}
        aria-label={placeholder}
        onChange={(event) => setDraft(event.target.value)}
      />
      <button type="submit">Save</button>
      <button type="button" onClick={() => setEditing(null)}>
        Cancel
      </button>
    </form>
  );

  return (
    <section className={styles.facts} aria-label="Key facts">
      <header className={styles.head}>
        <div>
          <h3>Key facts</h3>
          <p>
            {documentView
              ? "Source facts and saved confirmations."
              : "Checked before we trust them. Tap to confirm or fix."}
          </p>
        </div>
        <small>Saved on this device for now</small>
      </header>

      <Row
        label="Who is on the call"
        value={people.length ? people.join(" · ") : "Not named yet"}
        status={
          people.length ? (
            <Confirmed>Named</Confirmed>
          ) : documentView ? null : (
            <button
              type="button"
              className={styles.add}
              onClick={() =>
                document
                  .querySelector('figure[aria-label="Call map"]')
                  ?.scrollIntoView({ behavior: "smooth", block: "center" })
              }
            >
              Name them on the call map
            </button>
          )
        }
      />

      <Row
        label="Industry"
        value={
          editing === "industry" ? (
            <select
              className={styles.select}
              autoFocus
              aria-label="Industry"
              value={draft}
              onChange={(event) => {
                save({
                  kind: "value",
                  id: "industry",
                  value: event.target.value,
                });
                save({ kind: "confirm", id: "industry", value: true });
                setEditing(null);
              }}
            >
              <option value="">Pick an industry</option>
              {INDUSTRIES.map((icon) => (
                <option key={icon.key} value={icon.label}>
                  {icon.label}
                </option>
              ))}
            </select>
          ) : industry ? (
            industry
          ) : (
            <span className={styles.muted}>Not found</span>
          )
        }
        status={
          facts.confirmed.industry ? (
            <Confirmed />
          ) : industry ? (
            ask("industry")
          ) : (
            add("industry")
          )
        }
      />

      <Row
        label="Time asked for"
        value={
          editing === "time" ? (
            editor("time", "Minutes agreed, e.g. 10")
          ) : facts.values.time ? (
            `${facts.values.time} min · call took ${Math.round(durationMs / 60000)} min`
          ) : promise ? (
            <>
              Up to {promise.upToMinutes} min · call took{" "}
              {Math.round(durationMs / 60000)} min
              {promise.segments.map((segment) => (
                <Heard key={segment.id} ms={segment.start_ms} onSeek={onSeek} />
              ))}
            </>
          ) : (
            <span className={styles.muted}>No time agreed at the start</span>
          )
        }
        status={
          facts.confirmed.time ? (
            <Confirmed />
          ) : promise ? (
            ask("time")
          ) : (
            add("time")
          )
        }
      />

      <Row
        label="Price or budget"
        value={
          editing === "budget" ? (
            editor("budget", "Budget, e.g. ₹50,000")
          ) : facts.values.budget ? (
            `Budget ${facts.values.budget}`
          ) : price.length ? (
            <>
              Came up{priceHasAmount ? "" : ", no amount said"}
              {price.slice(0, 3).map((segment) => (
                <Heard key={segment.id} ms={segment.start_ms} onSeek={onSeek} />
              ))}
            </>
          ) : (
            <span className={styles.muted}>Never came up</span>
          )
        }
        status={
          facts.values.budget ? (
            <Confirmed>Added</Confirmed>
          ) : (
            add("budget", "Add budget")
          )
        }
      />

      <Row
        label="Next step"
        value={
          editing === "next" ? (
            editor("next", "When, e.g. tomorrow 11 am")
          ) : facts.values.next ? (
            facts.values.next
          ) : report.overview?.outcome?.text ? (
            <span className={styles.clamp}>{report.overview.outcome.text}</span>
          ) : (
            <span className={styles.muted}>Not clear from the call</span>
          )
        }
        status={
          facts.values.next ? (
            <Confirmed>Added</Confirmed>
          ) : (
            add("next", "Add a time")
          )
        }
      />

      <Row
        label="How firm is the next step"
        value={
          documentView ? (
            (facts.values.firmness ?? "Not set")
          ) : (
            <div
              className={styles.steps}
              role="radiogroup"
              aria-label="How firm is the next step"
            >
              {NEXT_STEP_FIRMNESS.map((option) => (
                <button
                  key={option}
                  type="button"
                  role="radio"
                  aria-checked={facts.values.firmness === option}
                  title={option}
                  disabled={!canSave}
                  onClick={() =>
                    save({
                      kind: "value",
                      id: "firmness",
                      value: facts.values.firmness === option ? null : option,
                    })
                  }
                >
                  {FIRMNESS_SHORT[option] ?? option}
                </button>
              ))}
            </div>
          )
        }
        status={facts.values.firmness ? <Confirmed>Set</Confirmed> : null}
      />

      <div className={styles.numbers}>
        <h3>
          Money and percentages heard <span>{numbers.length}</span>
        </h3>
        {numbers.length === 0 ? (
          <p className={styles.muted}>
            No currency amount or percentage was said.
          </p>
        ) : (
          numbers.slice(0, 10).map((number) => (
            <div key={number.id} className={styles.number}>
              <b>{number.spoken}</b>
              <Heard ms={number.segment.start_ms} onSeek={onSeek} />
              <span className={styles.who}>{nameOf(number.voice)}</span>
              <ChipPicker
                label={`What is ${number.spoken}?`}
                value={facts.numberLabels[number.id]}
                options={NUMBER_MEANINGS}
                disabled={!canSave}
                onChange={(value) =>
                  save({ kind: "number", id: number.id, value })
                }
              />
              <q className={styles.said}>{number.segment.text}</q>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
