import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { Progress } from "../acquisition-client";
import { ProcessingStatusCopy } from "../processing-status-copy";
import {
  plan,
  recordingId,
  submissionId,
} from "../../tests/acquisition-fixture";
import { levelFor, parseCallAi } from "./call-ai-client";
import { CallAiSettingsSection } from "./call-ai-settings";

vi.mock("../notice-center", () => ({ notify: vi.fn() }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  sessionStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const SELLER = "0b8f4f0e-5b9a-4c51-9a77-1f2e3d4c5b6a";
const settings = (overrides: Record<string, unknown> = {}) => ({
  revision: 3,
  default: "full",
  people: [{ person_id: SELLER, name: "Asha Fictional", level: "data_only" }],
  you: { level: "full", source: "organisation" },
  levels: [
    { id: "off", name: "Off", hint: "No AI reads them." },
    { id: "data_only", name: "Data only", hint: "Transcript and lead facts." },
    { id: "auto", name: "Auto", hint: "Picks per call." },
    { id: "full", name: "Full", hint: "The full report." },
  ],
  can_edit: true,
  ...overrides,
});

it("reads the levels and never breaks on a malformed answer", () => {
  const read = parseCallAi(settings());
  expect(levelFor(read, SELLER)).toEqual({ level: "data_only", own: true });
  expect(levelFor(read, "someone-else")).toEqual({ level: "full", own: false });
  const broken = parseCallAi({
    default: "cheap",
    people: [{ person_id: SELLER, level: "half" }, "nonsense"],
    levels: "nope",
  });
  expect(broken.default).toBe("full");
  expect(broken.people).toEqual([]);
  expect(broken.can_edit).toBe(false);
  expect(broken.levels.map((level) => level.id)).toEqual([
    "off",
    "data_only",
    "auto",
    "full",
  ]);
});

it("lets an owner or admin choose the organisation's default", async () => {
  const fetchMock = vi.fn<typeof fetch>(async (_url, init) =>
    init?.method === "PUT"
      ? new Response(
          JSON.stringify(settings({ revision: 4, default: "data_only" })),
        )
      : new Response(JSON.stringify(settings())),
  );
  vi.stubGlobal("fetch", fetchMock);
  await act(async () => root.render(<CallAiSettingsSection />));
  expect(host.textContent).toContain("Default: Full");
  expect(host.textContent).toContain("Asha Fictional");
  expect(host.querySelector('a[href="/leads?tab=team"]')).not.toBeNull();
  const save = [...host.querySelectorAll("button")].find(
    (item) => item.textContent === "Save default",
  )!;
  expect(save.disabled).toBe(true);
  const dataOnly = host.querySelector<HTMLInputElement>(
    'input[type="radio"][value="data_only"]',
  )!;
  await act(async () => dataOnly.click());
  expect(save.disabled).toBe(false);
  await act(async () => save.click());
  const [url, init] = fetchMock.mock.calls[1];
  expect(String(url)).toBe("/v1/sales-xray/call-ai/default");
  expect(init?.method).toBe("PUT");
  expect(JSON.parse(init?.body as string)).toEqual({
    expected_revision: 3,
    level: "data_only",
  });
  expect(host.textContent).toContain("Default: Data only");
});

it("shows a seller only what applies to their own calls", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(
      async () =>
        new Response(
          JSON.stringify(
            settings({
              can_edit: false,
              you: { level: "data_only", source: "person" },
            }),
          ),
        ),
    ),
  );
  await act(async () => root.render(<CallAiSettingsSection />));
  expect(host.querySelector('input[type="radio"]')).toBeNull();
  expect(host.textContent).toContain("Your calls: Data only");
  expect(host.textContent).toContain("set for you by an owner or admin");
});

const stopped = (
  canUpgrade: boolean,
  level: "off" | "data_only",
): Progress => ({
  state: "held",
  local_state: "completed",
  has_report: false,
  failure_code: level === "off" ? "ai_off" : "ai_data_only",
  automatic_progression: false,
  stages: [{ stage: "C2", state: "completed" }],
  recording_id: recordingId,
  run_state: "failed",
  minute_state: "released",
  retry_available: false,
  ai_skip: {
    level,
    reason: "level",
    stopped_before: level === "off" ? "C2" : "C4",
    can_upgrade: canUpgrade,
  },
});

const status = (progress: Progress) =>
  root.render(
    <ProcessingStatusCopy
      submissionId={submissionId}
      progress={progress}
      title="Call"
      paused={false}
      needsAttention
    />,
  );

it("says why a call has no report, and lets an admin get the full report", async () => {
  const fetchMock = vi.fn<typeof fetch>(
    async () => new Response(JSON.stringify(plan)),
  );
  vi.stubGlobal("fetch", fetchMock);
  await act(async () => status(stopped(true, "data_only")));
  expect(host.textContent).toContain("Data only: no report");
  expect(host.textContent).not.toContain("Analysis failed");
  // No price on a person's screen (owner, 19 Oct 2026).
  expect(host.textContent).not.toMatch(/₹|cost|price/i);
  const get = [...host.querySelectorAll("button")].find(
    (item) => item.textContent === "Get full report",
  )!;
  await act(async () => get.click());
  expect(String(fetchMock.mock.calls[0][0])).toContain(
    `/submissions/${submissionId}/full-report`,
  );
  expect(host.textContent).toContain("Accept and get full report");
});

it("tells a seller an owner or admin can get the full report", async () => {
  await act(async () => status(stopped(false, "off")));
  expect(host.textContent).toContain("AI is off for these calls");
  expect(host.textContent).toContain(
    "An owner or admin can get the full report",
  );
  expect(host.querySelector("button")).toBeNull();
});

it("says a short call keeps its transcript and lead details, with Get full report", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async () => new Response(JSON.stringify(plan))),
  );
  await act(async () =>
    status({
      ...stopped(true, "data_only"),
      failure_code: "ai_short_call",
      ai_skip: {
        level: "full",
        reason: "short_call",
        stopped_before: "C4",
        can_upgrade: true,
      },
    }),
  );
  expect(host.textContent).toContain("Short call: transcript and lead details");
  expect(host.textContent).toContain("Calls under a minute");
  expect(host.textContent).not.toContain("Data only");
  expect(
    [...host.querySelectorAll("button")].some(
      (item) => item.textContent === "Get full report",
    ),
  ).toBe(true);
});
