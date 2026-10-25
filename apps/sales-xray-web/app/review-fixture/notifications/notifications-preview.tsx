"use client";

/**
 * Notifications with fictional entries, for the visual matrix: a ready report
 * that needs you, paused analysis, an invite, what's new and two read lines.
 * `?empty=1`: nothing waiting. The bell opens the sheet; nothing leaves the
 * browser.
 */

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import { UpdatesBell } from "../../shell/updates-bell";
import type { UpdateNotification } from "../../shell/updates-client";

const HOUR = 3_600_000;

function entries(now: number): UpdateNotification[] {
  const at = (hours: number) => new Date(now - hours * HOUR).toISOString();
  return [
    {
      id: "n1",
      kind: "report_ready",
      title: "Your report on the call with Priya Sample is ready",
      body: "She asked for the price list twice; the report says what to send.",
      href: "/review-fixture/notifications",
      urgent: true,
      created_at: at(0.2),
      read: false,
    },
    {
      id: "n2",
      kind: "analysis_paused",
      title: "Call analysis paused",
      body: "Two calls wait until your workspace has analysis time again.",
      href: "/review-fixture/notifications",
      urgent: false,
      created_at: at(3),
      read: false,
    },
    {
      id: "n3",
      kind: "invite_received",
      title: "Kavya Fictional invited you to Fictional Homes",
      href: "/review-fixture/notifications",
      urgent: false,
      created_at: at(26),
      read: false,
    },
    {
      id: "n4",
      kind: "updates",
      title: "4 new updates",
      href: null,
      urgent: false,
      created_at: at(50),
      read: true,
      count: 4,
    },
    {
      id: "n5",
      kind: "report_ready",
      title: "Your report on the call with Rohan Example is ready",
      href: "/review-fixture/notifications",
      urgent: false,
      created_at: at(80),
      read: true,
    },
  ];
}

function Preview() {
  const empty = useSearchParams().get("empty") === "1";
  const [list, setList] = useState(() => (empty ? [] : entries(Date.now())));
  return (
    <main style={{ display: "grid", gap: 16, padding: 16 }}>
      <header style={{ display: "flex", justifyContent: "flex-end" }}>
        <UpdatesBell
          notifications={list}
          unreadCount={list.filter((entry) => !entry.read).length}
          status="ready"
          openNews={() => {}}
          openEvent={async () => {}}
          markRead={async (ids) =>
            setList((now) =>
              now.map((entry) =>
                ids.includes(entry.id) ? { ...entry, read: true } : entry,
              ),
            )
          }
        />
      </header>
      <h1 style={{ margin: 0 }}>Home</h1>
    </main>
  );
}

export function NotificationsPreview() {
  return (
    <Suspense fallback={null}>
      <Preview />
    </Suspense>
  );
}
