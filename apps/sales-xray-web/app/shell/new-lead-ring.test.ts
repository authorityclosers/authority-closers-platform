import { afterEach, describe, expect, it, vi } from "vitest";

import { popOnComputer, ringNewLead } from "./new-lead-ring";
import { parseNotifications } from "./updates-client";

function fakeNotification(permission: string) {
  const made: Array<{ title: string; options: NotificationOptions }> = [];
  const shown: Array<{ onclick: (() => void) | null }> = [];
  class Fake {
    static permission = permission;
    static requestPermission = vi.fn();
    onclick: (() => void) | null = null;
    close = vi.fn();
    constructor(title: string, options: NotificationOptions) {
      made.push({ title, options });
      shown.push(this);
    }
  }
  vi.stubGlobal("Notification", Fake);
  return { made, last: () => shown.at(-1) ?? null, Fake };
}

function hidden(value: boolean) {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => (value ? "hidden" : "visible"),
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  hidden(false);
});

describe("new lead ring", () => {
  it("pops a system notification in a background tab where allowed, and opens the lead", () => {
    const fake = fakeNotification("granted");
    hidden(true);
    const open = vi.fn();
    expect(popOnComputer("n1", "New lead: Asha", "Meta ad", open)).toBe(true);
    expect(fake.made).toEqual([
      {
        title: "New lead: Asha",
        options: expect.objectContaining({
          body: "Meta ad",
          tag: "lead-new:n1",
        }),
      },
    ]);
    fake.last()?.onclick?.();
    expect(open).toHaveBeenCalledOnce();
  });

  it("never asks for permission and stays quiet when not allowed or in view", () => {
    const fake = fakeNotification("default");
    hidden(true);
    expect(popOnComputer("n1", "New lead", undefined, vi.fn())).toBe(false);
    expect(fake.Fake.requestPermission).not.toHaveBeenCalled();
    const allowed = fakeNotification("granted");
    hidden(false);
    expect(popOnComputer("n2", "New lead", undefined, vi.fn())).toBe(false);
    expect(allowed.made).toEqual([]);
  });

  it("rings without sound support or page notifications", () => {
    vi.stubGlobal("Notification", undefined);
    vi.stubGlobal("Audio", undefined);
    expect(() => ringNewLead("n3", "New lead", "x", vi.fn())).not.toThrow();
  });

  it("rings with the sound picked for a new lead, from the library", () => {
    vi.stubGlobal("Notification", undefined);
    const made: string[] = [];
    vi.stubGlobal(
      "Audio",
      class {
        src = "";
        loop = false;
        preload = "";
        canPlayType = () => "probably";
        addEventListener = () => undefined;
        play = async () => made.push(this.src);
      },
    );
    window.localStorage.setItem(
      "sx-sounds-plays",
      JSON.stringify({ "sx.new_lead": "pulse-v2.mention" }),
    );
    ringNewLead("n4", "New lead", "x", vi.fn());
    expect(made).toEqual(["/sounds/pulse-v2/mention.mp3"]);
    window.localStorage.removeItem("sx-sounds-plays");
  });

  it("keeps lead_new lines from the server", () => {
    const parsed = parseNotifications({
      unread_count: 1,
      notifications: [
        {
          id: "a",
          kind: "lead_new",
          title: "New lead: Asha Fictional",
          body: "Meta ad · No one has it yet. Call now or give it to a seller.",
          href: "/leads?lead=00000000-0000-4000-8000-000000000001",
          urgent: true,
          created_at: "2026-11-17T08:00:00Z",
          read: false,
        },
      ],
    });
    expect(parsed.notifications).toEqual([
      expect.objectContaining({ id: "a", kind: "lead_new" }),
    ]);
  });
});
