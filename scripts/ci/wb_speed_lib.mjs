// The speed check's pure parts (`wb-ci --speed`; the owner, 27 Oct 2026, via the orchestrator: "on low-end devices
// with the worst processors this app might be slow"). wb_speed.mjs times the key screens of a production build
// (app/perf-fixture, the review fixtures' fictional screens; no API) in Chromium with the CPU slowed down: 1x, 4x
// (about a mid-range phone; Lighthouse's mobile setting) and 6x (a low-end phone). Nothing here needs a browser, so
// the tests run with plain `node --test`.
//
// What is timed, the way telemetry times real phones (apps/sales-xray-web/app/telemetry-auto.tsx):
// - load: from navigation to the screen settling (no change for 300 ms), with its LCP and blocking time;
// - a tap: from the tap to the screen settling (no change for 150 ms), for the actions telemetry names.

export const RATES = [1, 4, 6];
export const RUNS = 3;
export const LOW_END = 6;
export const VIEWPORT = { width: 390, height: 844 };

// Telemetry's tap actions and the markup that makes them (actionOf in telemetry-auto.tsx). A tap that leaves the
// page (a call report, a nav link) is not timed here: the fixture has no API behind the next page.
export const ACTIONS = {
  lead_open: "[data-lead-row]",
  tab_switch: '[role="tab"][aria-selected="false"]',
  sheet_open: '[aria-haspopup="dialog"]',
};

export const ACTION_WORDS = {
  load: "opening the screen",
  lead_open: "opening a lead",
  tab_switch: "switching a tab",
  sheet_open: "opening a sheet",
};

// The key screens (owner: leads, a lead, calls, the Report; plus Home, Chats, the organisation and Settings).
export const SPEED_SCREENS = {
  home: { path: "/perf-fixture/home", label: "Home" },
  leads: { path: "/perf-fixture/leads?tab=all", label: "Leads, All" },
  "leads-work": {
    path: "/perf-fixture/leads?tab=work",
    label: "Leads, My work",
  },
  "leads-board": {
    path: "/perf-fixture/leads?tab=board",
    label: "Leads, board",
  },
  calls: { path: "/perf-fixture/calls", label: "Calls" },
  report: { path: "/perf-fixture/report", label: "Report" },
  chats: { path: "/perf-fixture/chats", label: "Chats" },
  hub: { path: "/perf-fixture/hub", label: "Organisation" },
  settings: { path: "/perf-fixture/settings", label: "Settings" },
};

// When a measure is slow at 6x (a low-end phone): a card; over the builder's limit: a card for the builder
// (orchestrator: "anything over 2 s goes to the builder"). A screen's first load also downloads and runs its code,
// so it gets more room.
export const LIMITS = {
  load: { slow: 3000, builder: 5000 },
  tap: { slow: 1000, builder: 2000 },
};

/** The screens a request names (speed screen names); none, or none known, means all. */
export function pickSpeedScreens(routes = []) {
  const known = routes.filter((route) => SPEED_SCREENS[route]);
  return (known.length ? known : Object.keys(SPEED_SCREENS)).map((key) => [
    key,
    SPEED_SCREENS[key],
  ]);
}

export const median = (values) => {
  const sorted = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[mid]
    : Math.round((sorted[mid - 1] + sorted[mid]) / 2);
};

/** A card's marker: perf:<screen>:<action> (orchestrator, 27 Oct 2026). */
export const perfKey = (screen, action) => `perf:${screen}:${action}`;

/**
 * Every (screen, action) with its median per rate, from the raw measures [{screen, action, rate, ms, lcp, tbt,
 * result}]. A measure that never settled counts as its cap; "no_change" taps are kept apart.
 */
export function summarize(measures) {
  const rows = new Map();
  for (const m of measures) {
    const key = `${m.screen}|${m.action}`;
    let row = rows.get(key);
    if (!row)
      rows.set(key, (row = { screen: m.screen, action: m.action, rates: {} }));
    const at = (row.rates[m.rate] ??= {
      ms: [],
      lcp: [],
      tbt: [],
      results: [],
    });
    if (m.result !== "no_change" && m.result !== "failed") at.ms.push(m.ms);
    if (m.lcp !== undefined && m.lcp !== null) at.lcp.push(m.lcp);
    if (m.tbt !== undefined && m.tbt !== null) at.tbt.push(m.tbt);
    at.results.push(m.result);
  }
  return [...rows.values()].map((row) => ({
    ...row,
    rates: Object.fromEntries(
      Object.entries(row.rates).map(([rate, at]) => [
        rate,
        {
          median: median(at.ms),
          runs: at.ms.length,
          lcp: median(at.lcp),
          tbt: median(at.tbt),
          settled: at.results.filter((r) => r === "settled").length,
          capped: at.results.filter((r) => r === "timeout").length,
          no_change: at.results.filter((r) => r === "no_change").length,
          failed: at.results.filter((r) => r === "failed").length,
        },
      ]),
    ),
  }));
}

/** What is slow on a low-end phone: severity "builder" over the builder's limit, else "slow". */
export function classify(rows, limits = LIMITS, rate = LOW_END) {
  const findings = [];
  for (const row of rows) {
    const at = row.rates[rate];
    if (!at || at.median === null) continue;
    const limit = row.action === "load" ? limits.load : limits.tap;
    if (at.median < limit.slow) continue;
    findings.push({
      key: perfKey(row.screen, row.action),
      screen: row.screen,
      action: row.action,
      // For the card's words (ac-bug-radar has no copy of these maps).
      label: SPEED_SCREENS[row.screen]?.label ?? row.screen,
      words: ACTION_WORDS[row.action] ?? row.action,
      path: SPEED_SCREENS[row.screen]?.path ?? null,
      severity: at.median >= limit.builder ? "builder" : "slow",
      builder: limit.builder,
      ms: at.median,
      limit: limit.slow,
      at4: row.rates[4]?.median ?? null,
      at1: row.rates[1]?.median ?? null,
    });
  }
  return findings.sort((a, b) => b.ms - a.ms);
}

const cell = (at) =>
  !at || at.median === null ? "–" : `${at.median}${at.capped ? "+" : ""}`;

/** The run's report: every screen and action at 1x, 4x and 6x, then what is slow. */
export function speedMarkdown(run) {
  const { rows, findings, failures = [] } = run;
  const lines = [
    "### Speed check",
    "",
    `Production build, fictional screens, a 390 px phone; CPU at 1x, 4x (a mid-range phone) and 6x (a low-end phone); ` +
      `the median of ${RUNS} runs` +
      (run.source_sha
        ? ` for \`${String(run.source_sha).slice(0, 12)}\``
        : "") +
      ". Load: from navigation to the screen settling; a tap: from the tap to the screen settling (as telemetry measures phones). " +
      `Slow at 6x: a load over ${LIMITS.load.slow} ms or a tap over ${LIMITS.tap.slow} ms; for the builder over ` +
      `${LIMITS.load.builder} and ${LIMITS.tap.builder} ms.`,
    "",
    "| screen | what | 1x ms | 4x ms | 6x ms | 6x LCP | 6x blocking | |",
    "|---|---|---|---|---|---|---|---|",
  ];
  for (const row of rows) {
    const label = SPEED_SCREENS[row.screen]?.label ?? row.screen;
    const six = row.rates[LOW_END];
    const flag = findings.find(
      (f) => f.screen === row.screen && f.action === row.action,
    );
    lines.push(
      `| ${label} | ${ACTION_WORDS[row.action] ?? row.action} | ${cell(row.rates[1])} | ${cell(row.rates[4])} | ` +
        `${cell(six)} | ${six?.lcp ?? "–"} | ${six?.tbt ?? "–"} | ${flag ? (flag.severity === "builder" ? "**for the builder**" : "slow") : ""} |`,
    );
  }
  lines.push("", `#### Slow on a low-end phone (${findings.length})`, "");
  if (!findings.length) lines.push("None.");
  for (const f of findings)
    lines.push(
      `- \`${f.key}\` ${SPEED_SCREENS[f.screen]?.label ?? f.screen}, ${ACTION_WORDS[f.action] ?? f.action}: ` +
        `${f.ms} ms at 6x (${f.at4 ?? "–"} at 4x, ${f.at1 ?? "–"} at 1x)${f.severity === "builder" ? ", over the builder's limit" : ""}`,
    );
  if (failures.length) {
    lines.push("", "#### Could not be measured", "");
    for (const failure of failures) lines.push(`- ${failure}`);
  }
  lines.push(
    "",
    "A `+` means a run never settled within its cap (15 s for a load, 10 s for a tap) and counts at the cap. " +
      "Runs are one at a time on a GitHub runner, so other work never shares the CPU.",
  );
  return lines.join("\n") + "\n";
}

// In the page, from before the first script: when the page last changed, LCP, blocking time and the last tap.
export const SPEED_INIT = `(() => {
  const s = (window.__speed = { last: 0, lcp: null, tbt: 0, tap: 0 });
  new MutationObserver(() => { s.last = performance.now(); })
    .observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
  try {
    new PerformanceObserver((list) => { for (const e of list.getEntries()) s.lcp = Math.round(e.startTime); })
      .observe({ type: "largest-contentful-paint", buffered: true });
    new PerformanceObserver((list) => { for (const e of list.getEntries()) s.tbt += Math.max(0, e.duration - 50); })
      .observe({ type: "longtask", buffered: true });
  } catch {}
  addEventListener("pointerdown", (e) => { s.tap = e.timeStamp; }, true);
})();`;
