"use client";

/**
 * AI on calls with fictional people, for screenshots on GitHub (wb-ci --visual).
 * The screens' own API calls are answered here and nothing leaves the browser.
 *
 * `?view=settings` (default): Settings → AI on calls, an owner's view.
 * `?view=sellers`: Leads → Team, each seller's AI on calls level.
 * `?view=team`: the same, then a seller's lead rules with their AI level.
 * `?view=call`: a Data only call (owner or admin: Get full report) and an Off
 * call as its seller sees it.
 */

import { useEffect, useState, useSyncExternalStore } from "react";

import type { Progress } from "../../acquisition-client";
import { CallAiSettingsSection } from "../../call-ai/call-ai-settings";
import { TeamView } from "../../leads/team-view";
import styles from "../../leads/leads.module.css";
import { ProcessingStatusCopy } from "../../processing-status-copy";
import { Panel } from "../../ui/kit";

const SELLERS = [
  ["00000000-0000-4000-8000-000000000301", "Asha Fictional", "data_only"],
  ["00000000-0000-4000-8000-000000000302", "Ravi Fictional", null],
  ["00000000-0000-4000-8000-000000000303", "Meera Fictional", "off"],
  ["00000000-0000-4000-8000-000000000304", "Karan Fictional", null],
] as const;

const LEVELS = [
  {
    id: "off",
    name: "Off",
    hint: "Calls are saved and logged on the lead. No AI reads them.",
  },
  {
    id: "data_only",
    name: "Data only",
    hint: "Transcript and lead facts for the CRM, WhatsApp and automations. No report or coaching.",
  },
  {
    id: "auto",
    name: "Auto",
    hint: "Sales X-Ray picks per call. Until call types arrive, every call gets the full report.",
  },
  {
    id: "full",
    name: "Full",
    hint: "The full report and coaching on every call.",
  },
];

const settings = {
  revision: 4,
  default: "full",
  people: SELLERS.filter(([, , level]) => level).map(([id, name, level]) => ({
    person_id: id,
    name,
    level,
  })),
  you: { level: "full", source: "organisation" },
  levels: LEVELS,
  can_edit: true,
};

const team = {
  reps: SELLERS.map(([id, name], index) => ({
    person_id: id,
    name,
    role: index === 0 ? "admin" : "member",
    revision: 1,
    available: index !== 2,
    max_open: 50,
    languages: index % 2 ? ["Marathi", "Hindi"] : ["English"],
    areas: ["Pune"],
    interests: [],
    open_leads: 40 - index * 7,
    due_now: 6 - index,
    calls_today: 22 - index * 4,
    connected_today: 9 - index * 2,
    first_call_minutes: 4 + index,
    phone: null,
  })),
  settings: {
    revision: 7,
    auto_reassign: false,
    reassign_minutes: 10,
    default_country: "91",
    work_hours: null,
  },
  by_stage: { new: 120, not_connected: 160, follow_up: 60, interested: 30 },
  by_source: { csv: 370 },
  unassigned: 0,
  waiting_first_call: 120,
  first_call_minutes: 6,
};

function answer(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function install() {
  if (typeof window === "undefined") return true;
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    if (url.includes("/v1/sales-xray/call-ai")) return answer(settings);
    if (url.includes("/v1/lead-desk/team")) return answer(team);
    // The Team tab's other panels: nothing to show in this fixture.
    if (url.includes("/v1/lead-desk/"))
      return answer({ detail: "Sample data only." }, 404);
    return real(input, init);
  };
  return true;
}

/** Open the first seller's lead rules once the team has drawn. */
function openRules() {
  const timer = window.setInterval(() => {
    const button = document.querySelector<HTMLButtonElement>(
      'button[aria-label="Edit Asha Fictional\'s lead rules"]',
    );
    if (!button) return;
    button.click();
    window.clearInterval(timer);
  }, 40);
  return () => window.clearInterval(timer);
}

const stopped = (
  level: "off" | "data_only",
  canUpgrade: boolean,
): Progress => ({
  state: "held",
  local_state: "completed",
  has_report: false,
  failure_code: level === "off" ? "ai_off" : "ai_data_only",
  automatic_progression: false,
  stages: level === "off" ? [] : [{ stage: "C2", state: "completed" }],
  recording_id: "00000000-0000-4000-8000-000000000401",
  run_state: "failed",
  minute_state: "released",
  retry_available: false,
  ai_skip: {
    level,
    stopped_before: level === "off" ? "C2" : "C4",
    can_upgrade: canUpgrade,
  },
});

// Read in the browser only, so the first render matches the server's.
const unchanging = () => () => undefined;
const readView = () =>
  new URLSearchParams(window.location.search).get("view") ?? "settings";

export function CallAiPreview() {
  useState(install);
  const view = useSyncExternalStore(unchanging, readView, () => "settings");
  useEffect(() => (readView() === "team" ? openRules() : undefined), []);
  if (view === "team" || view === "sellers")
    return (
      <div className={styles.root}>
        <TeamView onChanged={() => undefined} onOpen={() => undefined} />
      </div>
    );
  if (view === "call")
    return (
      <div style={{ display: "grid", gap: 16, padding: 16, maxWidth: 720 }}>
        <Panel title="An owner or admin opens a Data only call">
          <div style={{ padding: 16 }}>
            <ProcessingStatusCopy
              submissionId="00000000-0000-4000-8000-000000000501"
              progress={stopped("data_only", true)}
              title="Call"
              paused={false}
              needsAttention
            />
          </div>
        </Panel>
        <Panel title="The seller opens a call while AI is off">
          <div style={{ padding: 16 }}>
            <ProcessingStatusCopy
              submissionId="00000000-0000-4000-8000-000000000502"
              progress={stopped("off", false)}
              title="Call"
              paused={false}
              needsAttention
            />
          </div>
        </Panel>
      </div>
    );
  return (
    <div style={{ padding: 16, maxWidth: 760 }}>
      <CallAiSettingsSection />
    </div>
  );
}
