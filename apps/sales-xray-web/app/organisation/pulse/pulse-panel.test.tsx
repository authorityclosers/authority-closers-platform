import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PulsePanel } from "./pulse-panel";
import {
  readPulse,
  savePulseSharing,
  syncPulse,
  unlinkPulse,
  type PulseState,
} from "./pulse-client";
vi.mock("../../notice-center", () => ({ notify: vi.fn() }));
vi.mock("./pulse-client", async (original) => ({
  ...(await original<typeof import("./pulse-client")>()),
  readPulse: vi.fn(),
  savePulseSharing: vi.fn(),
  syncPulse: vi.fn(),
  unlinkPulse: vi.fn(),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement, root: Root;
const linked: PulseState = {
  configured: true,
  link: {
    orgId: "sample",
    orgName: "Sample Office",
    linkedAt: null,
    linkedBy: "Mira Fictional",
    scopes: [],
    sharing: { directory: "read", photos: "off", signals: "off" },
    webhooks: true,
    lastSyncAt: null,
    lastSync: {},
  },
  members: [],
  access: [],
};
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(readPulse).mockResolvedValue(linked);
  vi.mocked(syncPulse).mockResolvedValue(linked);
  vi.mocked(savePulseSharing).mockResolvedValue(linked);
  vi.mocked(unlinkPulse).mockResolvedValue({ ...linked, link: null });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.clearAllMocks();
});
async function tap(text: string) {
  const button = [...host.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === text,
  );
  expect(button).toBeDefined();
  await act(async () => button!.click());
}
it("reads and syncs the linked organisation without silently enabling sharing", async () => {
  await act(async () => root.render(<PulsePanel />));
  expect(host.textContent).toContain("Linked to Sample Office");
  expect(savePulseSharing).not.toHaveBeenCalled();
  await tap("Sync now");
  expect(syncPulse).toHaveBeenCalledOnce();
});
it("requires a second explicit unlink and shows the connect action afterwards", async () => {
  await act(async () => root.render(<PulsePanel />));
  await tap("Unlink");
  expect(unlinkPulse).not.toHaveBeenCalled();
  await tap("Unlink from Pulse?");
  expect(unlinkPulse).toHaveBeenCalledOnce();
  expect(host.textContent).toContain("Connect your Pulse org");
});
it("offers the connect action for an unlinked organisation", async () => {
  vi.mocked(readPulse).mockResolvedValue({ ...linked, link: null });
  await act(async () => root.render(<PulsePanel />));
  expect(
    [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Connect your Pulse org"),
    )?.disabled,
  ).toBe(false);
  expect(syncPulse).not.toHaveBeenCalled();
});
