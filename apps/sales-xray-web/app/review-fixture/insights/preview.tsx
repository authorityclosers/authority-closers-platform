"use client";

import { useState } from "react";

import { Segmented } from "../../ui/kit";
import { DEFAULT_FILTERS } from "../../organisation/insights/insights-data";
import { InsightsView } from "../../organisation/insights/insights-view";
import sandbox from "./sandbox.json";

type View = "sandbox" | "team" | "empty" | "denied";

/**
 * Insights with fictional data from the synthetic sandbox (AUT-1798), through
 * the real parser and screen: the sandbox organisation, a small real-style
 * team (no teams, talk share from confirmed sellers), empty and denied.
 */
function teamOf(body: typeof sandbox): unknown {
  const overview = sandbox.overview;
  return {
    ...overview,
    source: "call",
    synthetic: false,
    teams: [],
    mistakes: [],
    people: overview.people
      .slice(0, 6)
      .map((person) => ({ ...person, team: null })),
    facets: {
      ...overview.facets,
      teams: [],
      people: overview.facets.people.slice(0, 6),
    },
    calls: body.overview.calls,
  };
}

export function InsightsFixture() {
  const [view, setView] = useState<View>("sandbox");
  const team = { ...sandbox.calls, synthetic: false };
  const seeds: Record<View, { status: number; body: unknown }> = {
    sandbox: { status: 200, body: sandbox.overview },
    team: { status: 200, body: teamOf(sandbox) },
    empty: {
      status: 200,
      body: {
        ...sandbox.overview,
        totals: { calls: 0 },
        trend: [],
        people: [],
      },
    },
    denied: { status: 403, body: null },
  };
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 1fr)",
        gap: 16,
        padding: 16,
        maxWidth: 1280,
        margin: "0 auto",
      }}
    >
      <div style={{ minWidth: 0, overflowX: "auto" }}>
        <Segmented<View>
          label="Fixture"
          value={view}
          onChange={setView}
          items={[
            { key: "sandbox", label: "Sandbox org" },
            { key: "team", label: "Small team" },
            { key: "empty", label: "Empty" },
            { key: "denied", label: "Member" },
          ]}
        />
      </div>
      <InsightsView
        key={view}
        fixture
        filters={DEFAULT_FILTERS}
        initial={seeds[view]}
        initialCalls={{
          status: 200,
          body: view === "team" ? team : sandbox.calls,
        }}
      />
    </div>
  );
}
