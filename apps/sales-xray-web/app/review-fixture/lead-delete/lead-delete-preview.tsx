"use client";

/**
 * Leads → All leads → Select → Delete, with fictional leads, for screenshots
 * on GitHub (wb-ci --visual). The list's own API calls are answered here and
 * nothing leaves the browser; the page taps through the steps by itself.
 *
 * `?view=select` (default): Test data, Select, seven leads ticked.
 * `?view=confirm`: the same, then Delete: the confirm sheet.
 * `?view=one`: the confirm for one lead, as a lead's own Delete opens it.
 */

import { Suspense, useEffect, useState, useSyncExternalStore } from "react";

import { DeleteLeadsSheet } from "../../leads/delete-leads";
import { ListView } from "../../leads/list-view";
import styles from "../../leads/leads.module.css";

const NAMES: [string, string | null, string | null][] = [
  ["Asha Fictional", "Pune", "Flat enquiry"],
  ["Ravi Fictional", "Mumbai", "Site visit"],
  ["Meera Fictional", "Nashik", "Plot"],
  ["Karan Fictional", "Pune", "2 BHK"],
  ["Neha Fictional", "Thane", "Office space"],
  ["Test Lead One", "Pune", null],
  ["Test Lead Two", null, null],
  ["Sample Buyer", "Nagpur", "Villa"],
];
const STAGES: [string, string][] = [
  ["new", "New lead"],
  ["follow_up", "In talks"],
  ["interested", "Hot"],
  ["lost", "Lost"],
];

const rows = NAMES.map(([name, city, interest], index) => {
  const [stage, stageLabel] = STAGES[index % STAGES.length];
  return {
    lead_id: `00000000-0000-4000-8000-0000000002${String(index).padStart(2, "0")}`,
    revision: 1,
    name,
    company: null,
    city,
    language: null,
    interest,
    phone_last4: "3210",
    stage,
    stage_label: stageLabel,
    source: "synthetic",
    source_label: "Sample data",
    owner_person_id: null,
    owner_name: index % 2 ? "Priya Fictional" : null,
    why: "New",
    why_kind: "new",
    next_action_at: null,
    created_at: "2026-10-03T10:00:00Z",
    attempts: 0,
    calls: 0,
    last_result: null,
    last_result_label: null,
    test_data: true,
  };
});

function answer(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function install() {
  if (typeof window === "undefined") return true;
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    if (!url.includes("/v1/lead-desk/")) return real(input, init);
    if (url.includes("/leads/delete"))
      return answer({ deleted: 0, lead_ids: [], not_found: 0 });
    return answer({
      schema: "lead-desk/1",
      leads: rows,
      total: rows.length,
      next_offset: null,
    });
  };
  return true;
}

/** Tap through the screen as a person would: one step a tick. */
function drive(confirm: boolean) {
  const find = (text: string) =>
    [...document.querySelectorAll("button")].find(
      (item) => item.textContent?.trim() === text,
    );
  const tap = (text: string) => {
    const button = find(text);
    button?.click();
    return !!button;
  };
  let ticked = 0;
  const steps: (() => boolean)[] = [
    () => tap("Test data"),
    () => tap("Select"),
    () => {
      const boxes =
        document.querySelectorAll<HTMLButtonElement>('[role="checkbox"]');
      if (boxes.length < rows.length) return false;
      boxes[ticked]?.click();
      ticked += 1;
      return ticked >= 7;
    },
    ...(confirm ? [() => tap("Delete")] : []),
  ];
  let step = 0;
  const timer = window.setInterval(() => {
    if (step >= steps.length) window.clearInterval(timer);
    else if (steps[step]()) step += 1;
  }, 40);
  return () => window.clearInterval(timer);
}

// The address is read in the browser only; the server draws the plain list, so
// the first browser render matches it (no hydration error).
const unchanging = () => () => undefined;
const readView = () =>
  new URLSearchParams(window.location.search).get("view") ?? "select";

export function LeadDeletePreview() {
  useState(install);
  const view = useSyncExternalStore(unchanging, readView, () => "select");
  useEffect(() => {
    const asked = readView();
    if (asked !== "one") return drive(asked === "confirm");
  }, []);
  return (
    <div className={styles.root}>
      <Suspense>
        <ListView canManage onOpen={() => undefined} version={0} />
      </Suspense>
      {view === "one" ? (
        <DeleteLeadsSheet
          open
          leads={[{ lead_id: rows[0].lead_id, name: rows[0].name }]}
          onClose={() => undefined}
          onDeleted={() => undefined}
        />
      ) : null}
    </div>
  );
}
