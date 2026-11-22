// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

// Lead rules › Message senders (v1.95): fictional tools only.
const api = vi.hoisted(() => ({ read: vi.fn(), pause: vi.fn() }));
vi.mock("../../outreach/outreach-client", () => ({
  OutreachError: class OutreachError extends Error {},
  readSenders: api.read,
  pauseSender: api.pause,
  createSender: vi.fn(),
}));
vi.mock("../integrations/integrations-client", () => ({
  readIntegrations: () => Promise.resolve({ keys: [] }),
}));
vi.mock("../../notice-center", () => ({ notify: vi.fn() }));

import type { SenderView } from "../../outreach/outreach-client";
import {
  MessageSenders,
  seenWords,
  senderDetails,
  senderLine,
} from "./message-senders";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const NOW = Date.parse("2026-11-22T10:00:00Z");
const engine: SenderView = {
  sender_id: "s1",
  key: "fictional-engine",
  label: "Fictional engine",
  kind: "automation",
  person_id: null,
  person_name: null,
  api_key_id: "k1",
  api_key_prefix: "sxk_live_ab12",
  channels: ["whatsapp"],
  lead_defaults: { create: true, side: "cold", tags: [], assign: "none" },
  guard_mode: "report",
  status: "active",
  revision: 3,
  last_seen_at: "2026-11-22T08:00:00Z",
  touches_week: 12,
};

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  api.read.mockReset();
  api.pause.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("says each sender's channels and week, when it was last seen, and keeps the keys behind Details", () => {
  expect(senderLine(engine)).toBe("WhatsApp · 12 this week");
  expect(seenWords(engine.last_seen_at, NOW)).toBe("Last seen 2 h ago");
  expect(seenWords(null, NOW)).toBe("Not used yet");
  expect(senderDetails(engine)).toBe(
    "Short key fictional-engine · API key sxk_live_ab12… · Logs and advises",
  );
  expect(
    senderLine({
      ...engine,
      kind: "person_tool",
      person_name: "Mira Fictional",
    }),
  ).toBe("For Mira Fictional · WhatsApp · 12 this week");
  expect(
    senderDetails({ ...engine, api_key_prefix: null, guard_mode: "hold" }),
  ).toBe("Short key fictional-engine · No API key yet · Holds at a limit");
});

it("lists the senders and pauses one at once, on its revision", async () => {
  api.read.mockResolvedValue([engine]);
  api.pause.mockResolvedValue({ ...engine, status: "paused", revision: 4 });
  await act(async () => root.render(<MessageSenders />));
  expect(host.textContent).toContain("Fictional engine");
  expect(host.textContent).toContain("Sending");
  // The keys sit behind Details, in plain type (no code font).
  expect(host.querySelector("details summary")?.textContent).toBe("Details");
  expect(host.querySelector("code")).toBeNull();
  const pause = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Pause",
  )!;
  await act(async () => pause.click());
  expect(api.pause).toHaveBeenCalledWith(engine, true);
  expect(host.textContent).toContain("Paused");
  expect(
    [...host.querySelectorAll("button")].some(
      (button) => button.textContent === "Resume",
    ),
  ).toBe(true);
});

it("says plainly when there are no senders yet", async () => {
  api.read.mockResolvedValue([]);
  await act(async () => root.render(<MessageSenders />));
  expect(host.textContent).toContain("No senders yet");
  expect(host.textContent).toContain("Add a sender");
});
