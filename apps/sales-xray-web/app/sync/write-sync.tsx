"use client";

/**
 * The seller's unsent changes, always in sight (owner, 24 Oct 2026, P0:
 * never a silent failure). Mounted in the app frame, it:
 * - sends what waits at the start, after signing in, on reconnect, on return
 *   to the app, and when the next retry is due (write-queue.ts);
 * - shows a corner card while anything waits ("1 change not sent yet", with
 *   Send now), then "All changes saved" once it has gone;
 * - shows each change the server refused when sent again, with its words and
 *   Open lead, so nothing is dropped without the person seeing it.
 */

import { useEffect, useRef } from "react";

import { dismissNotice, notify } from "../notice-center";
import { useWorkspaceAccess } from "../workspace-access";
import {
  discardWrite,
  replayWrites,
  setWriteIdentity,
  useWrites,
  writtenWords,
  type QueuedWrite,
} from "./write-queue";

export const WAITING_NOTICE = "writes-waiting";

/** The leads page opened on one lead (leads-client.ts leadLink). */
const leadHref = (leadId: string) =>
  `/leads?lead=${encodeURIComponent(leadId)}`;

function refusedMessage(item: QueuedWrite): string {
  const why =
    item.status === 409
      ? "The lead changed before this could be sent."
      : item.status === null || item.status === 0
        ? "It waited too long to be sent."
        : "Sales X-Ray didn't accept it.";
  const words = writtenWords(item);
  return `${why} ${item.lead ? "Open the lead and enter it again." : "Enter it again."}${
    words
      ? ` You wrote: “${words.length > 140 ? `${words.slice(0, 140)}…` : words}”`
      : ""
  }`;
}

export function WriteSync() {
  const access = useWorkspaceAccess();
  const context = access?.authenticated === true ? access.context : null;
  const who = context ? `${context.personId}:${context.tenantId}` : null;

  // At the start and after signing in: what waits for this person goes now.
  useEffect(() => {
    setWriteIdentity(who);
    if (who) void replayWrites({ force: true });
  }, [who]);

  // Again on reconnect and on return to the app.
  useEffect(() => {
    const again = () => {
      if (document.visibilityState === "visible")
        void replayWrites({ force: true });
    };
    window.addEventListener("online", again);
    document.addEventListener("visibilitychange", again);
    return () => {
      window.removeEventListener("online", again);
      document.removeEventListener("visibilitychange", again);
    };
  }, []);

  const { waiting, check, sending, nextAt, signIn } = useWrites();

  // And when the next retry is due.
  useEffect(() => {
    if (!waiting || !nextAt) return;
    const timer = window.setTimeout(
      () => void replayWrites(),
      Math.max(1_000, nextAt - Date.now()),
    );
    return () => window.clearTimeout(timer);
  }, [waiting, nextAt]);

  const shown = useRef(0);
  useEffect(() => {
    if (waiting > 0) {
      shown.current = waiting;
      notify({
        id: WAITING_NOTICE,
        tone: "info",
        title:
          waiting === 1
            ? "1 change not sent yet"
            : `${waiting} changes not sent yet`,
        message: signIn
          ? "Kept on this phone. Sign in again and it goes to Sales X-Ray."
          : "Kept on this phone. It goes to Sales X-Ray as soon as it answers.",
        action: {
          label: sending ? "Sending…" : "Send now",
          run: () => void replayWrites({ force: true }),
        },
        // Closing it hides it until something changes; the change still waits.
        onDismiss: async () => undefined,
      });
      return;
    }
    if (shown.current > 0) {
      shown.current = 0;
      dismissNotice(WAITING_NOTICE);
      notify({
        id: "writes-sent",
        tone: "success",
        title: "All changes saved",
      });
    }
  }, [waiting, sending, signIn]);

  useEffect(() => {
    for (const item of check) {
      const id = `writes-check-${item.id}`;
      notify({
        id,
        tone: "error",
        noReport: true,
        title: `${item.label} wasn't saved`,
        message: refusedMessage(item),
        action: item.lead
          ? {
              label: "Open lead",
              run: () => {
                discardWrite(item.id);
                dismissNotice(id);
                window.location.assign(leadHref(item.lead as string));
              },
            }
          : undefined,
        onDismiss: async () => discardWrite(item.id),
      });
    }
  }, [check]);

  return null;
}
