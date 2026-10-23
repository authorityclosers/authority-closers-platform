"use client";

/**
 * Switches that matter (owner, 23 Oct 2026), for screenshots on a phone and on
 * GitHub: Taking new leads as the Leads chip and as the Settings row, for a
 * seller or an owner, on, off or paused for work hours. Its reads and saves
 * are answered here; nothing leaves the browser.
 *
 *   ?as=seller|owner              who is looking (seller)
 *   ?state=on|off|after-hours     the switch (on)
 *   ?open=status|off|override     opens that sheet, for screenshots
 */

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { TakingSwitch } from "../../leads/taking-switch";
import { PageHeader, Panel } from "../../ui/kit";
import { WorkspaceAccessContext } from "../../workspace-access";

const PERSON = "00000000-0000-4000-8000-000000000002";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";

function tomorrowNine() {
  const at = new Date();
  at.setDate(at.getDate() + 1);
  at.setHours(9, 0, 0, 0);
  return at.toISOString();
}

function install(owner: boolean, until: string | null) {
  if (typeof window === "undefined") return;
  const hours = (pause: boolean) => ({
    days: [1, 2, 3, 4, 5, 6],
    start: "09:00",
    end: "19:00",
    pause_leads: pause,
    inside: false,
    next_start: until,
  });
  const team = (pause: boolean) => ({
    reps: [],
    settings: {
      revision: 3,
      auto_reassign: false,
      reassign_minutes: 15,
      default_country: "IN",
      work_hours: hours(pause),
    },
    by_stage: {},
    by_source: {},
    unassigned: 0,
    waiting_first_call: 0,
  });
  const real = window.fetch.bind(window);
  const answer = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    if (path === "/v1/lead-desk/me/taking") {
      const { taking } = JSON.parse(String(init?.body ?? "{}")) as {
        taking: boolean;
      };
      return answer({
        person_id: PERSON,
        name: owner ? "rahul example" : "swamini fictional",
        role: owner ? "owner" : "member",
        can_manage: owner,
        taking_leads: taking,
        paused_until: until,
      });
    }
    if (path === "/v1/lead-desk/team")
      return owner
        ? answer(team(true))
        : answer({ detail: "Owners and admins only." }, 403);
    if (path === "/v1/lead-desk/work-hours") return answer(team(false));
    if (path.startsWith("/v1/"))
      return answer({ detail: "Sample data only." }, 404);
    return real(input, init);
  };
}

export function SwitchesPreview() {
  return (
    <Suspense fallback={null}>
      <Switches />
    </Suspense>
  );
}

function Switches() {
  const query = useSearchParams();
  const owner = query.get("as") === "owner";
  const state = query.get("state") ?? "on";
  const open = query.get("open");
  const [until] = useState(() =>
    state === "after-hours" ? tomorrowNine() : null,
  );
  useState(() => install(owner, until));

  // Screenshots can't tap on every phone: ?open= presses the button once.
  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => {
      const target =
        open === "status"
          ? document.querySelector<HTMLButtonElement>(
              "[data-review-chip] button",
            )
          : open === "off"
            ? document.querySelector<HTMLButtonElement>(
                '[data-review-row] button[role="switch"]',
              )
            : [
                ...document.querySelectorAll<HTMLButtonElement>(
                  "[data-review-row] button",
                ),
              ].find(
                (button) => button.textContent === "Hand out leads after hours",
              );
      target?.click();
    }, 600);
    return () => window.clearTimeout(timer);
  }, [open]);

  const taking = state !== "off";
  return (
    <WorkspaceAccessContext.Provider
      value={{
        status: "ready",
        authenticated: true,
        context: { personId: PERSON, sessionId: SESSION, tenantId: TENANT },
        workspaces: [
          {
            tenant_id: TENANT,
            kind: "organisation",
            name: "Fictional Homes",
            role: owner ? "owner" : "member",
            sales_xray_enabled: true,
          },
        ],
        retry: () => {},
      }}
    >
      <AcquisitionShell authenticated active="account" pageName="Settings">
        <div style={{ display: "grid", gap: 16, padding: 16 }}>
          <PageHeader title="Selling" />
          <Panel title="On Leads, beside the stage tabs">
            <div data-review-chip="">
              <TakingSwitch initial={taking} place="chip" pausedUntil={until} />
            </div>
          </Panel>
          <Panel title="New leads">
            <div data-review-row="">
              <TakingSwitch initial={taking} place="row" pausedUntil={until} />
            </div>
          </Panel>
        </div>
      </AcquisitionShell>
    </WorkspaceAccessContext.Provider>
  );
}
