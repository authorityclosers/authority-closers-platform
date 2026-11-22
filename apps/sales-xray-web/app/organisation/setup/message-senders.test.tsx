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
import { MessageSenders, seenWords, senderLine } from "./message-senders";

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

it("says each sender's key, channels, week and last seen in one line", () => {
  expect(senderLine(engine, NOW)).toBe(
    "key sxk_live_ab12… · WhatsApp · 12 this week · seen 2 h ago",
  );
  expect(seenWords(null, NOW)).toBe("not used yet");
  expect(
    senderLine(
      {
        ...engine,
        kind: "person_tool",
        person_name: "Mira Fictional",
        api_key_prefix: null,
      },
      NOW,
    ),
  ).toContain("For Mira Fictional · no key yet");
});

it("lists the senders and pauses one at once, on its revision", async () => {
  api.read.mockResolvedValue([engine]);
  api.pause.mockResolvedValue({ ...engine, status: "paused", revision: 4 });
  await act(async () => root.render(<MessageSenders />));
  expect(host.textContent).toContain("Fictional engine");
  expect(host.textContent).toContain("Sending");
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
