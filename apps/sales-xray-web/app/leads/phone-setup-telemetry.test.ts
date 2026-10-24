import { afterEach, expect, it, vi } from "vitest";

import { telemetry } from "../telemetry";
import { parseSetup, type SetupStatus } from "./native-phone";
import {
  promptOf,
  promptOutcome,
  telemetryStep,
  trackPrompt,
} from "./phone-setup-telemetry";

afterEach(() => {
  vi.restoreAllMocks();
});

const status = (raw: Record<string, unknown>): SetupStatus =>
  parseSetup({ checks: {}, ...raw })!;

it("names each ask as the permission snapshot does", () => {
  const plain = status({});
  expect(promptOf("calls", plain)).toBe("calls");
  expect(promptOf("callLog", plain)).toBe("call_log");
  expect(telemetryStep("callLog")).toBe("call_log");
  expect(promptOf("recordings", plain)).toBe("rec_files");
  expect(
    promptOf(
      "recordings",
      status({ needsAllFiles: true, allFilesSupported: true }),
    ),
  ).toBe("all_files");
  expect(
    promptOf(
      "recordings",
      status({ needsAllFiles: true, folderPickSupported: true }),
    ),
  ).toBe("folder");
});

it("reads what came of an ask from the phone's status afterwards", () => {
  expect(
    promptOutcome("calls", status({ checks: { calls: true } }), true, false),
  ).toBe("granted");
  expect(promptOutcome("calls", status({}), false, false)).toBe("denied");
  expect(
    promptOutcome("calls", status({ blocked: { calls: true } }), false, false),
  ).toBe("blocked");
  // A settings screen that didn't open.
  expect(promptOutcome("battery", status({}), false, true)).toBe("not_opened");
  expect(promptOutcome("calls", null, true, false)).toBe("unknown");
});

it("sends one bounded event and never breaks setup", () => {
  const track = vi.spyOn(telemetry, "track").mockImplementation(() => {});
  trackPrompt({
    step: "notifications",
    before: status({}),
    after: status({ checks: { notifications: true } }),
    opened: true,
    settings: false,
    fix: true,
    ms: 4_321.4,
  });
  expect(track).toHaveBeenCalledWith("sx.permission_prompt", {
    permission: "notifications",
    outcome: "granted",
    via: "prompt",
    from: "fix",
    ms: 4_321,
  });
  track.mockImplementation(() => {
    throw new Error("no");
  });
  expect(() =>
    trackPrompt({
      step: "calls",
      before: status({}),
      after: null,
      opened: null,
      settings: false,
      fix: false,
      ms: 1,
    }),
  ).not.toThrow();
});
