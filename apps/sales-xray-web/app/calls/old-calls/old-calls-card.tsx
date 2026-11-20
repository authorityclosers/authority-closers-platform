"use client";

/**
 * Find my old calls on Calls (owner, 20 Nov 2026): the first time, "Find my
 * old calls"; then, at most every six hours, the phone looks again quietly
 * (nothing uploads) and the card says how many new recorded calls it found;
 * with nothing new, a quiet line to look again. Only in the Android app.
 * Opening it runs the look in OldCallsSheet, where consent decides the rest.
 */

import { History } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import { inPhoneApp } from "../../leads/native-phone";
import { track } from "../../telemetry";
import { Button } from "../../ui/kit";
import { readHandled, readLooked, scanOldCalls } from "./old-calls-client";
import {
  cardWords,
  newCalls,
  quietLookDue,
  type OldCallsScan,
} from "./old-calls-rules";
import { OldCallsSheet, type OldCallsEntry } from "./old-calls-sheet";
import styles from "./old-calls.module.css";

const noSubscription = () => () => {};

/** The new found calls and recordings in a look: not yet analysed or set aside here. */
function freshIn(scan: OldCallsScan): number {
  const handled = readHandled();
  return (
    newCalls(scan.calls, handled).length +
    scan.unplaced.filter((item) => !handled.has(item.recording.source)).length
  );
}

export function OldCallsCard({ entry = "calls" }: { entry?: OldCallsEntry }) {
  const phone = useSyncExternalStore(noSubscription, inPhoneApp, () => false);
  const [looked, setLooked] = useState<number | null>(() =>
    typeof window === "undefined" ? null : readLooked(),
  );
  const [fresh, setFresh] = useState(0);
  const [open, setOpen] = useState(false);
  const [openedFrom, setOpenedFrom] = useState<OldCallsEntry>(entry);
  // Each opening is a fresh sheet: a new look, nothing ticked.
  const [openings, setOpenings] = useState(0);
  const shown = useRef(false);

  useEffect(() => {
    if (!inPhoneApp()) return;
    const last = readLooked();
    if (last === null || !quietLookDue(last, Date.now())) return;
    // The quiet look: the phone and the server only; nothing goes up.
    const controller = new AbortController();
    void scanOldCalls(controller.signal).then((outcome) => {
      if (controller.signal.aborted || "error" in outcome) return;
      setFresh(freshIn(outcome.scan));
    });
    return () => controller.abort();
  }, []);

  const onScanned = useCallback((scan: OldCallsScan) => {
    setLooked(Date.now());
    setFresh(freshIn(scan));
  }, []);

  const words = cardWords({ scannedAt: looked, fresh });
  useEffect(() => {
    if (!phone || shown.current) return;
    shown.current = true;
    track("sx.old_calls", { stage: "card_shown", entry, found: fresh });
  }, [entry, fresh, phone]);

  if (!phone) return null;
  return (
    <>
      <section
        className={styles.card}
        data-quiet={words.quiet ? "" : undefined}
        aria-label="Find my old calls"
      >
        <History size={20} aria-hidden="true" />
        <span>
          <strong>{words.title}</strong>
          <small>{words.note}</small>
        </span>
        <Button
          variant={words.quiet ? "ghost" : "primary"}
          onClick={() => {
            setOpenedFrom(looked === null ? entry : "card");
            setOpenings((count) => count + 1);
            setOpen(true);
          }}
        >
          {words.button}
        </Button>
      </section>
      <OldCallsSheet
        key={openings}
        open={open}
        entry={openedFrom}
        onClose={() => {
          setOpen(false);
          setFresh(0);
        }}
        onScanned={onScanned}
      />
    </>
  );
}
