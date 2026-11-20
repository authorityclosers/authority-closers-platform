// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { parseSetup, type SetupStatus } from "../leads/native-phone";
import { SetupWalk, type SetupWalkProps } from "./setup-walk";
import { WALK_STEP_KEY, type AskStep, type WalkStep } from "./setup-walk-steps";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, 20 Nov 2026 (style C, "See what to tap"): one ask per screen, a
// picture of what to tap, the consent's sealed words in full with equal Turn
// on and Not now, nothing pre-ticked.

const STATUS = parseSetup({
  checks: {},
  family: "xiaomi",
  model: "Redmi 13",
  version: "1.0.60",
  device: "install-fictional-1",
  autostartNeeded: true,
  folderPickSupported: true,
  callLogSupported: true,
}) as SetupStatus;

const WORDS =
  "When I record a sales call with Sales X-Ray in Fictional Homes, the customer knows the call is recorded.";

let root: Root;
let host: HTMLDivElement;

function props(
  open: Set<AskStep>,
  extra: Partial<SetupWalkProps> = {},
): SetupWalkProps {
  return {
    steps: ["welcome", "alerts", "calls", "analyse", "all_set"] as WalkStep[],
    stillOpen: (step) => open.has(step),
    status: STATUS,
    settingsFor: () => false,
    questions: [
      "Allow Sales X-Ray to make and manage phone calls?",
      "Allow Sales X-Ray to access your phone call logs?",
    ],
    batteryPhase: "battery",
    test: "ready",
    consent: { words: WORDS, terms: "Fictional terms for review only." },
    busy: false,
    laterLabel: (step) => `Not now: ${step}`,
    onAsk: vi.fn(),
    onLater: vi.fn(),
    onNoCalls: vi.fn(),
    onShown: vi.fn(),
    onEnd: vi.fn(),
    ...extra,
  };
}

async function show(value: SetupWalkProps) {
  await act(async () => root.render(<SetupWalk {...value} />));
}

const tap = (words: string) => {
  const found = [...host.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === words,
  );
  if (!found) throw new Error(`no button ${words}: ${host.textContent}`);
  return found;
};
const heading = () => host.querySelector("h1")?.textContent;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  window.localStorage.clear();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

describe("SetupWalk", () => {
  it("asks one thing per screen, with a picture of what to tap, and moves on when it is granted", async () => {
    const open = new Set<AskStep>(["alerts", "calls", "analyse"]);
    const value = props(open);
    await show(value);
    expect(heading()).toBe("Let's set up your phone");
    expect(host.textContent).toContain("3 quick steps");
    await act(async () => tap("Start").click());
    expect(heading()).toBe("Hear about new leads first");
    expect(host.querySelectorAll("h1")).toHaveLength(1);
    expect(
      host.querySelectorAll("button[data-variant='primary']"),
    ).toHaveLength(1);
    const art = host.querySelector('[data-walk-art="alerts"]');
    expect(art?.getAttribute("aria-label")).toContain("Tap Allow");
    await act(async () => tap("Allow alerts").click());
    expect(value.onAsk).toHaveBeenCalledWith("alerts");
    // Android said yes: the next screen, by itself.
    open.delete("alerts");
    await show({ ...value, stillOpen: (step) => open.has(step) });
    expect(heading()).toBe("Let Sales X-Ray see your work calls");
    expect(
      host.querySelector("ol[aria-label]")?.getAttribute("aria-label"),
    ).toBe("Step 2 of 3");
    expect(window.localStorage.getItem(WALK_STEP_KEY)).toBe("calls");
    expect(value.onShown).toHaveBeenCalledWith("calls", 1, 3);
  });

  it("goes back a screen with the chevron", async () => {
    const value = props(new Set(["alerts", "calls"]), { start: "calls" });
    await show(value);
    await act(async () =>
      host
        .querySelector<HTMLButtonElement>('button[aria-label="Back"]')!
        .click(),
    );
    expect(heading()).toBe("Hear about new leads first");
  });

  it("shows the consent's sealed words in full, with equal Turn on and Not now, nothing pre-ticked", async () => {
    const value = props(new Set(["analyse"]), { start: "analyse" });
    await show(value);
    expect(heading()).toBe("Analyse my calls automatically?");
    expect(host.querySelector("[data-sx-consent-words] p")?.textContent).toBe(
      WORDS,
    );
    expect(host.querySelector('input[type="checkbox"]')).toBeNull();
    expect(tap("Turn on").dataset.variant).toBe("primary");
    expect(tap("Not now").dataset.variant).toBe("secondary");
    expect(host.textContent).toContain("Read the full terms");
    await act(async () => tap("Not now").click());
    expect(value.onLater).toHaveBeenCalledWith("analyse");
    expect(value.onAsk).not.toHaveBeenCalled();
    await act(async () => tap("Turn on").click());
    expect(value.onAsk).toHaveBeenCalledWith("analyse");
  });

  it("shows the settings page to open once Android won't ask again", async () => {
    await show(
      props(new Set(["alerts"]), {
        start: "alerts",
        settingsFor: () => true,
      }),
    );
    expect(tap("Open settings")).toBeTruthy();
    expect(
      host.querySelector('[data-walk-art="alerts-settings"]'),
    ).not.toBeNull();
  });

  it("names the maker's battery page and then Autostart", async () => {
    const value = props(new Set(["battery"]), {
      start: "battery",
      steps: ["battery"],
    });
    await show(value);
    expect(host.textContent).toContain("Battery saver → No restrictions");
    expect(host.textContent).toContain("Autostart → On");
    expect(tap("Open settings")).toBeTruthy();
    await show({ ...value, batteryPhase: "autostart" });
    expect(tap("Open Autostart")).toBeTruthy();
    expect(host.querySelector('[data-walk-art="autostart"]')).not.toBeNull();
  });

  it("ends when nothing is left to ask, and says so honestly after a Not now", async () => {
    const open = new Set<AskStep>(["alerts", "calls"]);
    const value = props(open, { start: "alerts" });
    await show(value);
    await act(async () => tap("Not now").click());
    open.clear();
    await show({ ...value, stillOpen: () => false });
    expect(heading()).toBe("Almost ready");
    await act(async () => tap("Go to Home").click());
    expect(value.onEnd).toHaveBeenCalledTimes(1);
    expect(window.localStorage.getItem(WALK_STEP_KEY)).toBeNull();
  });
});
