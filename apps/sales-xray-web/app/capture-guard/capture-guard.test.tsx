import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { CaptureHealthView } from "./capture-health";
import { CaptureRatesView } from "./capture-rates";
import {
  AutoCaptureState,
  CaptureStateLabel,
} from "../leads/auto-capture-state";
import { parseSetup, parseRecorder } from "../leads/native-phone";
import { readCaptureGuard } from "../leads/capture-guard-client";
import { autoCaptureStates } from "../leads/native-phone";

vi.mock("../leads/capture-guard-client", () => ({ readCaptureGuard: vi.fn() }));
vi.mock("../leads/native-phone", async (original) => ({
  ...(await original<typeof import("../leads/native-phone")>()),
  autoCaptureStates: vi.fn(async () => []),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;
let host: HTMLDivElement;
async function render(view: React.ReactNode) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => {
    root?.render(view);
  });
}
afterEach(async () => {
  await act(async () => root?.unmount());
  host?.remove();
  vi.clearAllMocks();
});

it("shows the red missing state with a direct setup fix", async () => {
  await render(<CaptureStateLabel state="missing" />);
  expect(host.textContent).toContain("No recording after 30 minutes");
  expect(host.querySelector('[data-missing="true"]')).not.toBeNull();
  expect(host.querySelector("a")?.getAttribute("href")).toBe(
    "/settings/privacy#calls-setup",
  );
});
it("server missing and report receipts outrank a stale native queue", async () => {
  vi.mocked(autoCaptureStates).mockResolvedValue([
    { eventId: "event", state: "waiting" },
  ]);
  vi.mocked(readCaptureGuard).mockResolvedValue({
    generated_at: "2026-10-29",
    rates: [],
    calls: [
      {
        event_id: "event",
        lead_id: "lead",
        person_id: "person",
        at: "2026-10-29",
        state: "missing",
        submission_id: null,
        attention: false,
      },
    ],
  });
  await render(<AutoCaptureState eventId="event" />);
  expect(host.textContent).toContain("No recording after 30 minutes");
});
it("keeps an older app's native state when server evidence is unavailable", async () => {
  vi.mocked(autoCaptureStates).mockResolvedValue([
    { eventId: "event", state: "uploading" },
  ]);
  vi.mocked(readCaptureGuard).mockResolvedValue(null);
  await render(<AutoCaptureState eventId="event" />);
  expect(host.textContent).toContain("Uploading");
});
it("does not claim private recordings are accessible and fixes open the native controls", async () => {
  const recorder = vi.fn(),
    folder = vi.fn();
  const setup = parseSetup({
    checks: {},
    recorderProfile: { kind: "private", recording: "private", folders: [] },
    folderPicked: false,
  });
  await render(
    <CaptureHealthView
      setup={setup}
      status={null}
      consentOn={false}
      onRecorder={recorder}
      onFolder={folder}
      onRefresh={() => {}}
    />,
  );
  expect(host.textContent).toContain("keeps recordings private");
  expect(host.textContent).toContain("has not reported");
  expect(host.textContent).toContain("Standing consent needed");
  await act(async () => {
    (host.querySelector("button") as HTMLButtonElement).click();
  });
  expect(recorder).toHaveBeenCalledOnce();
  await act(async () => {
    (host.querySelectorAll("button")[1] as HTMLButtonElement).click();
  });
  expect(folder).toHaveBeenCalledOnce();
});
it("shows daily counts with no seller ranking", async () => {
  await render(
    <CaptureRatesView
      rates={[
        {
          person_id: "a",
          name: "Alex Example",
          day: "2026-10-29",
          calls: 10,
          received: 9,
          analysed: 8,
          rate: 90,
          needs_fix: false,
        },
        {
          person_id: "b",
          name: "Sam Example",
          day: "2026-10-29",
          calls: 10,
          received: 3,
          analysed: 2,
          rate: 30,
          needs_fix: true,
        },
      ]}
    />,
  );
  expect(host.textContent).toContain("10 calls · 9 recordings · 8 analysed");
  expect(host.querySelectorAll('[data-missing="true"]')).toHaveLength(1);
  expect(host.textContent).not.toMatch(/rank|score|best|worst/i);
});

it("retains measured recording time and ignores invalid timestamps", () => {
  const base = { kind: "folder", recording: "on", folders: [] };
  expect(parseRecorder({ ...base, newestMs: 12345 })?.newestMs).toBe(12345);
  expect(parseRecorder({ ...base, newestMs: -1 })?.newestMs).toBeUndefined();
  expect(parseRecorder(base)?.newestMs).toBeUndefined();
});
