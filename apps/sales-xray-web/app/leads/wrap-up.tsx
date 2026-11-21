"use client";

/**
 * The wrap-up screen after a call (round-2 board 1, the owner's pick B, 20 Nov 2026):
 * a focused screen of its own instead of a card loose on the lead page, so nothing
 * floats over it and the page's own buttons don't peek above it. Step 1 is "How did
 * the call go?" (four big answers and a real "I didn't call"), step 2 "What happens
 * next?" (CallOutcome, wrapUp), then "Saved" with the report on its way and "Call next
 * lead". The 19 Nov rules stay: while a call this phone placed waits for its answer
 * there is no way out but answering, and no "I didn't call" (lead-sheet.tsx).
 *
 * A phone shows it full screen; a computer shows it as a centred white card over the
 * page. v1.93 (22 Nov 2026): one back arrow, the frame's: on step 2 it goes back to
 * step 1 (WrapBack), on step 1 back to the lead (absent while it must be answered).
 */
import {
  CheckCircle2,
  ChevronLeft,
  CircleCheck,
  CircleDashed,
  FileText,
  LoaderCircle,
  PhoneCall,
} from "lucide-react";
import {
  createContext,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Avatar } from "../ui/kit";
import { trackFor, watchCapture, type Track } from "./auto-capture-state";
import { when, type LeadDetail } from "./leads-client";
import styles from "./wrap-up.module.css";

/** Step 2 hands the frame its way back to step 1 (null on step 1). */
export const WrapBack = createContext<
  ((back: (() => void) | null) => void) | null
>(null);

export function WrapUpFrame({
  name,
  line,
  onLater,
  asking = true,
  children,
}: {
  /** Still asking (not the Saved screen). */
  asking?: boolean;
  /** The lead's name, at the top: whose call this is. */
  name: string;
  /** "Talked 4 min 12 s · just now", when the phone said. */
  line?: string | null;
  /** Back to the lead with the question on it; absent while it must be answered. */
  onLater?: () => void;
  children: ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [back, setBack] = useState<(() => void) | null>(null);
  const register = useCallback(
    (next: (() => void) | null) => setBack(() => next),
    [],
  );
  // The page behind stays still while this is up (bug 172: the page behind
  // an open sheet scrolled).
  useEffect(() => {
    const root = document.documentElement;
    const was = root.style.overflow;
    root.style.overflow = "hidden";
    box.current
      ?.querySelector<HTMLElement>("button:not([disabled])")
      ?.focus({ preventScroll: true });
    return () => {
      root.style.overflow = was;
    };
  }, []);
  if (typeof document === "undefined") return null;
  const onBack = back ?? onLater;
  return createPortal(
    <div
      className={styles.scrim}
      // While it asks, the corner's news waits (notice-center.tsx); once
      // saved, the "Moved to" card with its Undo shows.
      data-after-call={asking ? "" : undefined}
      data-wrap-up=""
    >
      <div
        ref={box}
        className={styles.screen}
        role="dialog"
        aria-modal="true"
        aria-label={`After the call with ${name}`}
      >
        <header className={styles.head}>
          {onBack ? (
            <button
              type="button"
              className={styles.later}
              aria-label={back ? "Change how it went" : `Back to ${name}`}
              data-sx-feature={back ? "wrap_up_back_step" : "wrap_up_later"}
              onClick={onBack}
            >
              <ChevronLeft size={22} aria-hidden="true" />
            </button>
          ) : null}
          <Avatar name={name} size={44} />
          <span className={styles.who}>
            <strong>{name}</strong>
            {line ? <small>{line}</small> : null}
          </span>
        </header>
        <WrapBack.Provider value={register}>
          <div className={styles.body}>{children}</div>
        </WrapBack.Provider>
      </div>
    </div>,
    document.body,
  );
}

type Row = { label: string; state: "done" | "now" | "wait" };

/**
 * The report's way, said only as far as this screen can know it (v1.93): the
 * recording found, uploaded, then read (about 2 minutes). Nothing known yet (a
 * computer, or the phone not asked yet): one plain line. No recording: said so.
 */
export function reportRows(
  track: Track | null,
  first: string,
): { title: string; rows: Row[]; line: string | null } {
  const onItsWay = "Your call report is on its way";
  const reading = "Reading the call · about 2 min";
  if (!track || track.done < 0)
    return {
      title: onItsWay,
      rows: [],
      line: `Ready about 2 min after the recording arrives, on ${first}'s page and in Reports.`,
    };
  if (track.done >= 6)
    return {
      title: "Your call report is ready",
      rows: [
        { label: "Recording found", state: "done" },
        { label: "Uploaded", state: "done" },
        { label: "Report ready", state: "done" },
      ],
      line: `On ${first}'s page and in Reports.`,
    };
  if (track.ended && track.recording === "arrived")
    return {
      title: "This call was short",
      rows: [
        { label: "Recording found", state: "done" },
        { label: "Uploaded", state: "done" },
      ],
      line: "A short call gets its transcript and lead details, not a report.",
    };
  if (track.recording === "not found" || (track.done === 0 && track.fix))
    return {
      title: "No recording for this call",
      rows: [],
      line: `So there is no report yet. You can add the recording on ${first}'s page.`,
    };
  if (track.recording === "waiting")
    return {
      title: onItsWay,
      rows: [
        { label: "Looking for the recording", state: "now" },
        { label: "Upload", state: "wait" },
        { label: reading, state: "wait" },
      ],
      line: null,
    };
  if (track.done >= 4)
    return {
      title: onItsWay,
      rows: [
        { label: "Recording found", state: "done" },
        { label: "Uploaded", state: "done" },
        { label: reading, state: "now" },
      ],
      line: null,
    };
  return {
    title: onItsWay,
    rows: [
      { label: "Recording found", state: "done" },
      { label: track.stuck ? track.label : "Uploading", state: "now" },
      { label: reading, state: "wait" },
    ],
    line: null,
  };
}

/** The report's rows for the call just saved, from the phone and the server. */
function ReportOnItsWay({
  eventId,
  first,
}: {
  eventId: string | null;
  first: string;
}) {
  const [track, setTrack] = useState<Track | null>(null);
  useEffect(() => {
    if (!eventId) return;
    return watchCapture(eventId, (evidence) =>
      setTrack(
        trackFor(
          evidence.native,
          evidence.server,
          evidence.unavailable,
          evidence.recorder,
          evidence.folder,
        ),
      ),
    );
  }, [eventId]);
  const said = reportRows(track, first);
  return (
    <div className={styles.report} role="status">
      <span className={styles.reportIcon}>
        <FileText size={20} aria-hidden="true" />
      </span>
      <span className={styles.reportWords}>
        <strong>{said.title}</strong>
        {said.rows.length ? (
          <ul className={styles.reportRows}>
            {said.rows.map((row) => (
              <li key={row.label} data-state={row.state}>
                {row.state === "done" ? (
                  <CircleCheck size={18} aria-hidden="true" />
                ) : row.state === "now" ? (
                  <LoaderCircle size={18} aria-hidden="true" />
                ) : (
                  <CircleDashed size={18} aria-hidden="true" />
                )}
                {row.label}
              </li>
            ))}
          </ul>
        ) : null}
        {said.line ? <small>{said.line}</small> : null}
      </span>
    </div>
  );
}

/** After Save: where the lead went, the report on its way, and Call next lead. */
export function WrapUpDone({
  saved,
  talked,
  reportExpected,
  onCallNext,
  onBack,
}: {
  saved: LeadDetail;
  talked: boolean;
  /** A call the phone records: its report follows by itself. */
  reportExpected: boolean;
  onCallNext?: () => void;
  onBack: () => void;
}) {
  const first = saved.lead.name.split(" ")[0] ?? saved.lead.name;
  // The call just saved: the newest call on the lead's history.
  const callId =
    saved.events.find((event) => event.kind === "call" && event.event_id)
      ?.event_id ?? null;
  return (
    <section className={styles.done} aria-labelledby="wrap-up-done">
      <CheckCircle2 className={styles.doneMark} size={40} aria-hidden="true" />
      <h3 id="wrap-up-done" className={styles.doneTitle}>
        Saved
      </h3>
      <p className={styles.doneLine}>
        {saved.lead.stage_label}
        {saved.lead.next_action_at
          ? ` · next call ${when(saved.lead.next_action_at)}`
          : ""}
      </p>
      {talked && reportExpected ? (
        <ReportOnItsWay eventId={callId} first={first} />
      ) : null}
      <div className={styles.doneActions}>
        {onCallNext ? (
          <button
            type="button"
            className={styles.primary}
            data-sx-feature="wrap_up_call_next"
            onClick={onCallNext}
          >
            <PhoneCall size={20} aria-hidden="true" />
            Call next lead
          </button>
        ) : null}
        <button
          type="button"
          className={onCallNext ? styles.secondary : styles.primary}
          data-sx-feature="wrap_up_back"
          onClick={onBack}
        >
          Back to {first}
        </button>
      </div>
    </section>
  );
}
