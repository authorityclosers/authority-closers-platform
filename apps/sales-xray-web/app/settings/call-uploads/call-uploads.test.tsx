import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AutoCaptureItem,
  AutoCaptureStatus,
  SetupStatus,
} from "../../leads/native-phone";

// SX-AUTOUPLOAD (owner, 25 Nov 2026: "auto upload is not working for any of the people who are using it").
const phone = vi.hoisted(() => ({
  inApp: true,
  status: null as AutoCaptureStatus | null,
  setup: null as SetupStatus | null,
  items: [] as AutoCaptureItem[],
  retryOne: vi.fn(async () => null),
  setupCalls: [] as Array<[boolean, boolean]>,
}));
vi.mock("../../leads/native-phone", () => ({
  inPhoneApp: () => phone.inApp,
  autoCaptureStatus: async () => phone.status,
  setupStatus: async () => phone.setup,
  autoCaptureStates: async () => phone.items,
  autoCaptureRetry: async () => phone.status,
  autoCaptureRetryOne: phone.retryOne,
  autoCaptureSetup: async (on: boolean, wifi: boolean) => {
    phone.setupCalls.push([on, wifi]);
    return { ...(phone.status as AutoCaptureStatus), on, wifiOnly: wifi };
  },
  askNotifications: async () => null,
  onPhoneSignal: () => () => undefined,
  pickRecordingsFolder: async () => null,
  recorderOpen: async () => true,
  setupOpen: async () => true,
}));
vi.mock("../auto-analysis-sheet", () => ({
  AutoAnalysisSheet: ({ open }: { open: boolean }) =>
    open ? <div data-testid="agree-sheet">sheet</div> : null,
}));

import { CallUploads } from "./call-uploads";
import {
  agoText,
  canRetry,
  counts,
  folderLine,
  headline,
} from "./call-uploads-rules";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const NOW = Date.parse("2026-11-25T09:30:00Z"); // 15:00 IST
const status = (extra: Partial<AutoCaptureStatus> = {}): AutoCaptureStatus => ({
  supported: true,
  on: true,
  wifiOnly: false,
  health: "ok",
  pending: 0,
  ...extra,
});
const setup = (kind: "folder" | "private", recording = "on"): SetupStatus =>
  ({
    recorder: {
      kind,
      maker: kind === "private" ? "google" : "xiaomi",
      dialerLabel: kind === "private" ? "Phone by Google" : "Phone",
      recording,
      folders: [
        {
          path: "MIUI/sound_recorder/call_rec",
          state: "found",
          recordings: 12,
        },
      ],
      switchTo: null,
    },
    blocked: {
      calls: false,
      notifications: false,
      recordings: false,
      microphone: false,
    },
    folderPicked: true,
  }) as unknown as SetupStatus;

describe("call uploads rules", () => {
  it("says the truth on iPhone, in a browser and with Google's Phone app", () => {
    expect(headline("iphone", null, null, NOW).title).toBe(
      "iPhone can't send calls by itself",
    );
    expect(headline("iphone", null, null, NOW).action).toBe("upload");
    expect(headline("web", null, null, NOW).action).toBe("open_app");
    const google = headline("android", status(), setup("private"), NOW);
    expect(google.tone).toBe("blocked");
    expect(google.line).toContain("Phone by Google");
    expect(google.action).toBe("share_help");
  });

  it("names recording off, uploads off, new terms and blocked notices, each with its one tap", () => {
    expect(
      headline("android", status(), setup("folder", "off"), NOW).action,
    ).toBe("recorder");
    expect(
      headline(
        "android",
        status({ on: false, health: "off" }),
        setup("folder"),
        NOW,
      ).action,
    ).toBe("turn_on");
    // Older builds stop uploads on new terms ("consent"); newer ones hold calls ("terms").
    expect(
      headline(
        "android",
        status({ on: false, health: "consent" }),
        setup("folder"),
        NOW,
      ).action,
    ).toBe("agree");
    const held = headline(
      "android",
      status({ health: "terms", healthCalls: 2 }),
      setup("folder"),
      NOW,
    );
    expect(held.action).toBe("agree");
    expect(held.line).toContain("2 lead calls wait");
    expect(
      headline(
        "android",
        status({ on: false, health: "notices" }),
        setup("folder"),
        NOW,
      ).action,
    ).toBe("notices");
  });

  it("all well: the last upload and its lead", () => {
    const ok = headline(
      "android",
      status({
        lastUploadAt: NOW - 4 * 60_000,
        lastUploadLead: "Rohan Deshmukh",
      }),
      setup("folder"),
      NOW,
    );
    expect(ok.tone).toBe("ok");
    expect(ok.title).toBe("Uploading by itself");
    expect(ok.line).toBe("Last call uploaded 4 min ago · Rohan Deshmukh");
    expect(agoText(NOW - 30_000, NOW)).toBe("just now");
    expect(agoText(NOW - 3 * 3_600_000, NOW)).toBe("3 h ago");
    expect(agoText(NOW - 26 * 3_600_000, NOW)).toBe("yesterday");
  });

  it("figures add up to the rows: today's uploads (India day), waiting, failed", () => {
    const items: AutoCaptureItem[] = [
      { eventId: "a", id: "1", state: "analysing", uploadedAt: NOW - 60_000 },
      {
        eventId: "b",
        id: "2",
        state: "report_ready",
        uploadedAt: NOW - 2 * 3_600_000,
      },
      // 23:00 IST yesterday: not today.
      {
        eventId: "c",
        id: "3",
        state: "received",
        uploadedAt: Date.parse("2026-11-24T17:30:00Z"),
      },
      { eventId: "d", id: "4", state: "waiting", stamp: NOW - 120_000 },
      { eventId: "e", id: "5", state: "held", hold: "review" },
      { eventId: "f", id: "6", state: "held", hold: "expired" },
    ];
    const c = counts(items, NOW);
    expect(c.today).toBe(2);
    expect(c.waiting).toHaveLength(1);
    expect(c.failed).toHaveLength(2);
    expect(canRetry(items[4])).toBe(true);
    expect(canRetry(items[5])).toBe(false);
  });

  it("the folder: the picked one, else the one the phone found", () => {
    expect(
      folderLine(
        status({ folders: ["Music/Recordings/Call Recordings"] }),
        null,
      ),
    ).toBe("Music / Recordings / Call Recordings");
    expect(folderLine(status(), setup("folder"))).toBe(
      "MIUI / sound_recorder / call_rec (found by itself)",
    );
    expect(folderLine(status(), null)).toBe("Not chosen");
  });
});

describe("<CallUploads>", () => {
  let root: Root;
  let host: HTMLDivElement;
  beforeEach(() => {
    vi.useFakeTimers({ now: NOW, toFake: ["Date"] });
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    phone.inApp = true;
    phone.setupCalls = [];
    phone.retryOne.mockClear();
  });
  afterEach(() => {
    act(() => root.unmount());
    host.remove();
    vi.useRealTimers();
  });
  const render = async () => {
    await act(async () => root.render(<CallUploads />));
    // Where it runs is set on the next task (never synchronously in the effect).
    await act(async () => new Promise((done) => setTimeout(done, 0)));
    await act(async () => undefined);
  };

  it("shows the figures, the failed call with Retry and the waiting one", async () => {
    phone.status = status({
      lastUploadAt: NOW - 4 * 60_000,
      lastUploadLead: "Rohan Deshmukh",
    });
    phone.setup = setup("folder");
    phone.items = [
      {
        eventId: "a",
        id: "1",
        state: "analysing",
        uploadedAt: NOW - 60_000,
        leadName: "Rohan Deshmukh",
      },
      {
        eventId: "b",
        id: "2",
        state: "held",
        hold: "review",
        leadName: "Sanjay Patil",
        stamp: NOW - 3_600_000,
        seconds: 360,
      },
      {
        eventId: "c",
        id: "3",
        state: "waiting",
        leadName: "Neha Joshi",
        due: NOW + 42_000,
      },
    ];
    await render();
    expect(host.textContent).toContain("Uploading by itself");
    expect(host.textContent).toContain(
      "Last call uploaded 4 min ago · Rohan Deshmukh",
    );
    expect(host.textContent).toContain("Call with Sanjay Patil didn't upload");
    expect(host.textContent).toContain("Uploads in 0:42");
    const retry = [...host.querySelectorAll("button")].find(
      (b) => b.textContent === "Retry",
    );
    expect(retry).toBeTruthy();
    await act(async () => retry?.click());
    expect(phone.retryOne).toHaveBeenCalledWith("2");
  });

  it("stopped by new terms: Read and agree opens the consent sheet", async () => {
    phone.status = status({ on: false, health: "consent" });
    phone.setup = setup("folder");
    phone.items = [];
    await render();
    expect(host.textContent).toContain("Agree to the new upload terms");
    const agree = [...host.querySelectorAll("button")].find(
      (b) => b.textContent === "Read and agree",
    );
    await act(async () => agree?.click());
    expect(host.querySelector("[data-testid=agree-sheet]")).not.toBeNull();
  });

  it("Google's Phone app: no figures, the share steps on tap", async () => {
    phone.status = status();
    phone.setup = setup("private");
    phone.items = [];
    await render();
    expect(host.textContent).toContain(
      "Your Phone app keeps recordings to itself",
    );
    expect(host.textContent).not.toContain("Sent today");
    const how = [...host.querySelectorAll("button")].find(
      (b) => b.textContent === "Show me how",
    );
    await act(async () => how?.click());
    expect(host.textContent).toContain("Tap Share and choose Sales X-Ray.");
  });

  it("mobile data off asks the phone for Wi-Fi only", async () => {
    phone.status = status();
    phone.setup = setup("folder");
    phone.items = [];
    await render();
    const toggle = host.querySelector<HTMLButtonElement>("button[role=switch]");
    expect(toggle?.getAttribute("aria-checked")).toBe("true");
    await act(async () => toggle?.click());
    expect(phone.setupCalls).toContainEqual([true, true]);
  });
});
