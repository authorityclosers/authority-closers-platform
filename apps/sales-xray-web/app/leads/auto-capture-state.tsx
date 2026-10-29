"use client";
import { useEffect, useState } from "react";
import { autoCaptureStates, onPhoneSignal } from "./native-phone";

const labels: Record<string, string> = {
  waiting: "Waiting to upload · Undo in notifications",
  uploading: "Uploading",
  analysing: "Analysing",
  report_ready: "Report ready",
  cancelled: "Upload cancelled",
  held: "Upload paused · review this call",
};
export function AutoCaptureState({ eventId }: { eventId?: string | null }) {
  const [state, setState] = useState<string | null>(null);
  useEffect(() => {
    if (!eventId) return;
    let active = true;
    const read = () => {
      void autoCaptureStates().then((items) => {
        if (active)
          setState(
            items.find((item) => item.eventId === eventId)?.state ?? null,
          );
      });
    };
    read();
    const stop = onPhoneSignal((signal) => {
      if (signal === "recordings" || signal === "resume") read();
    });
    const timer = setInterval(read, 30_000);
    return () => {
      active = false;
      stop();
      clearInterval(timer);
    };
  }, [eventId]);
  return state && labels[state] ? (
    <small role="status">{labels[state]}</small>
  ) : null;
}
