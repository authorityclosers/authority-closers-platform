"use client";

/**
 * Alerts by urgency with fictional work, for the visual matrix: `?level=normal`
 * (default) a banner up top; `?level=urgent` the centre card; `?level=due` the
 * red banner for a follow-up due within the hour; `&long=1` long words that
 * must wrap. The page behind is a plain list, as Home would be.
 */

import { Suspense, useEffect } from "react";
import { useSearchParams } from "next/navigation";

import { raiseAlert } from "../../ui/alerts";

function Preview() {
  const params = useSearchParams();
  const urgent = params.get("level") === "urgent";
  const due = params.get("level") === "due";
  const long = params.get("long") === "1";
  useEffect(() => {
    if (due) {
      raiseAlert({
        id: "fixture-due",
        level: "normal",
        emphasis: "urgent",
        title: long
          ? "Meera Fictional-Deshpande: follow-up in 40 min"
          : "Priya Sample: follow-up in 40 min",
        message: "Tap Open to see the lead.",
        action: { label: "Open", href: "/review-fixture/alerts" },
        timeout: 600_000,
      });
      return;
    }
    raiseAlert(
      urgent
        ? {
            id: "fixture-urgent",
            level: "urgent",
            title: long
              ? "Three promised call-backs are more than an hour late"
              : "3 calls are late",
            message: long
              ? "Rohan Example asked for a call back at 4:30 pm about the three-bedroom flat near the station."
              : "Rohan Example promised a call back an hour ago.",
            action: { label: "Call Rohan", href: "/review-fixture/alerts" },
          }
        : {
            id: "fixture-normal",
            level: "normal",
            title: long
              ? "New lead from your Facebook form: Meera Fictional-Deshpande"
              : "New lead: Priya Sample",
            message: "From your Facebook form",
            action: { label: "Call", href: "/review-fixture/alerts" },
            timeout: 600_000,
          },
    );
  }, [urgent, due, long]);
  return (
    <main style={{ display: "grid", gap: 16, padding: 16 }}>
      <h1 style={{ margin: 0 }}>Today</h1>
      {["Asha Fictional", "Karan Example", "Neha Fictional", "Ravi Sample"].map(
        (name) => (
          <p key={name} style={{ margin: 0 }}>
            {`${name} · Call back now`}
          </p>
        ),
      )}
    </main>
  );
}

export function AlertsPreview() {
  return (
    <Suspense fallback={null}>
      <Preview />
    </Suspense>
  );
}
