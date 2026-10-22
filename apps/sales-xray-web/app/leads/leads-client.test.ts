import { afterEach, describe, expect, it, vi } from "vitest";

import { whyLine } from "./desk-view";
import {
  ago,
  CONNECTED_STAGES,
  dispose,
  localInputValue,
  minutesLabel,
  NOT_CONNECTED_REASONS,
  displayPhone,
  nextCallTime,
  parseContactText,
  sharedLead,
  peekPendingCall,
  quickFollowUp,
  rememberCall,
  takePendingCall,
  whatsappHref,
  readDesk,
  readNext,
  LeadsError,
  splitList,
  type LeadRow,
} from "./leads-client";

const NOW = new Date(2026, 9, 16, 11, 30, 0);

const row = (over: Partial<LeadRow> = {}): LeadRow => ({
  lead_id: "7b9e487e-2a1e-498c-946e-8a3342ee03a0",
  revision: 2,
  name: "Asha Patil",
  company: null,
  city: "Pune",
  language: "Hindi",
  interest: null,
  phone_last4: "3210",
  stage: "new",
  stage_label: "New",
  source: "manual",
  source_label: "Added by hand",
  owner_person_id: null,
  owner_name: null,
  why: "New lead",
  why_kind: "new",
  next_action_at: null,
  created_at: new Date(NOW.getTime() - 6 * 60_000).toISOString(),
  attempts: 0,
  calls: 0,
  last_result: null,
  last_result_label: null,
  test_data: false,
  ...over,
});

afterEach(() => vi.unstubAllGlobals());

describe("NeoDove dispose vocabulary", () => {
  it("offers the ten not-connected reasons and four connected stages", () => {
    expect(NOT_CONNECTED_REASONS).toHaveLength(10);
    expect(NOT_CONNECTED_REASONS[0]).toEqual({
      key: "did_not_pick",
      label: "Did not pick",
    });
    expect(CONNECTED_STAGES.map((stage) => [stage.key, stage.closes])).toEqual([
      ["follow_up", false],
      ["interested", false],
      ["won", true],
      ["lost", true],
    ]);
  });

  it("quick follow-ups are one hour, tomorrow and next week", () => {
    expect(quickFollowUp("hour", NOW).getHours()).toBe(12);
    expect(quickFollowUp("tomorrow", NOW).getDate()).toBe(17);
    expect(quickFollowUp("week", NOW).getDate()).toBe(23);
    expect(localInputValue(NOW)).toBe("2026-10-16T11:30");
  });
});

describe("plain numbers and times", () => {
  it("talk time and ages read naturally", () => {
    expect(minutesLabel(0)).toBe("0m");
    expect(minutesLabel(45)).toBe("45s");
    expect(minutesLabel(48 * 60)).toBe("48m");
    expect(minutesLabel(125 * 60)).toBe("2h 5m");
    expect(ago(new Date(NOW.getTime() - 6 * 60_000).toISOString(), NOW)).toBe(
      "6 min ago",
    );
    expect(
      ago(new Date(NOW.getTime() - 3 * 86_400_000).toISOString(), NOW),
    ).toBe("3 days ago");
  });

  it("rule lists split on commas and lines without repeats", () => {
    expect(splitList("Hindi, english\nHindi,  Marathi ,")).toEqual([
      "Hindi",
      "english",
      "Marathi",
    ]);
  });

  it("each queue row says why now and when", () => {
    expect(whyLine(row(), NOW)).toBe("New lead · 6 min ago");
    const due = row({
      why: "Follow-up due",
      why_kind: "due",
      next_action_at: new Date(2026, 9, 16, 10, 0).toISOString(),
    });
    expect(whyLine(due, NOW)).toMatch(/^Follow-up due · was today /);
  });
});

describe("API client", () => {
  it("shows the server's plain refusal and keeps the status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json(
          { detail: "Leads work inside an organisation workspace." },
          { status: 403 },
        ),
      ),
    );
    await expect(readDesk()).rejects.toMatchObject({
      message: "Leads work inside an organisation workspace.",
      status: 403,
    });
  });

  it("refuses a desk without the fields the screen needs", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ queue: "nope" })),
    );
    await expect(readDesk()).rejects.toBeInstanceOf(LeadsError);
  });

  it("dispose sends the command id, the revision and only the chosen answers", async () => {
    const fetcher = vi.fn(async () => Response.json({}));
    vi.stubGlobal("fetch", fetcher);
    await dispose(
      row(),
      { connected: false, reason: "busy", remark: "" },
      "c-1",
    );
    const [url, init] = fetcher.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toBe(
      "/v1/lead-desk/leads/7b9e487e-2a1e-498c-946e-8a3342ee03a0/dispose",
    );
    expect(JSON.parse(init.body as string)).toEqual({
      command_id: "c-1",
      expected_revision: 2,
      connected: false,
      reason: "busy",
    });
  });
  // Start calling one pipeline at a time (23 Oct 2026).
  it("asks for one pipeline's day and next lead only when one is chosen", async () => {
    const fetcher = vi.fn<(url: string) => Promise<Response>>(async () =>
      Response.json(null),
    );
    vi.stubGlobal("fetch", fetcher);
    await readDesk(undefined, "partner_outreach").catch(() => undefined);
    await readDesk(undefined, null).catch(() => undefined);
    await readNext(undefined, undefined, "partner_outreach");
    await readNext("lead-1", undefined, "partner_outreach");
    await readNext("lead-1");
    expect(fetcher.mock.calls.map((call) => String(call[0]))).toEqual([
      "/v1/lead-desk?pipeline=partner_outreach",
      "/v1/lead-desk",
      "/v1/lead-desk/next?pipeline=partner_outreach",
      "/v1/lead-desk/next?skip=lead-1&pipeline=partner_outreach",
      "/v1/lead-desk/next?skip=lead-1",
    ]);
  });
});

describe("calling from the desk", () => {
  it("offers human call-back times", () => {
    const morning = new Date(2026, 9, 16, 11, 20);
    expect(nextCallTime("hour", morning).getHours()).toBe(12);
    expect(nextCallTime("evening", morning).getHours()).toBe(18);
    expect(
      nextCallTime("evening", new Date(2026, 9, 16, 17, 30)).getHours(),
    ).toBe(19);
    const tomorrow = nextCallTime("morning", morning);
    expect([
      tomorrow.getDate(),
      tomorrow.getHours(),
      tomorrow.getMinutes(),
    ]).toEqual([17, 10, 0]);
    const week = nextCallTime("week", morning);
    expect([week.getDate(), week.getHours()]).toEqual([23, 10]);

    // Someday: three weeks out at 11, never on a Sunday.
    const someday = nextCallTime("someday", morning);
    expect([someday.getMonth(), someday.getDate(), someday.getHours()]).toEqual(
      [10, 6, 11],
    );
    const fromSunday = nextCallTime("someday", new Date(2026, 9, 18, 9, 0));
    expect(fromSunday.getDay()).toBe(1);
    expect(fromSunday.getDate()).toBe(9);
  });

  it("shows Indian mobiles the way people read them", () => {
    expect(displayPhone("+919876543210")).toBe("+91 98765 43210");
    expect(displayPhone("+14155550100")).toBe("+14155550100");
  });

  it("opens WhatsApp with the number's digits", () => {
    expect(whatsappHref("+91 98765 43210")).toBe("https://wa.me/919876543210");
  });

  it("remembers the call that was started and forgets it once taken", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
    });
    try {
      rememberCall("lead-1", 1_000);
      expect(peekPendingCall(5_000)).toEqual({ leadId: "lead-1", at: 1_000 });
      expect(takePendingCall(5_000)).toEqual({ leadId: "lead-1", at: 1_000 });
      expect(peekPendingCall(6_000)).toBeNull();
      rememberCall("lead-2", 0);
      expect(peekPendingCall(4 * 60 * 60 * 1000)).toBeNull();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("adding leads", () => {
  it("fills a lead from a pasted WhatsApp contact or message", () => {
    expect(parseContactText("Asha Patil\n+91 98765 43210")).toEqual({
      name: "Asha Patil",
      phone: "+919876543210",
      email: undefined,
    });
    expect(
      parseContactText(
        "Name: Ravi Kumar\nPhone: 91234-56780\nravi@example.com",
      ),
    ).toEqual({
      name: "Ravi Kumar",
      phone: "9123456780",
      email: "ravi@example.com",
    });
    expect(parseContactText("call me on 98765 43210")).toEqual({
      name: undefined,
      phone: "9876543210",
      email: undefined,
    });
    expect(parseContactText("hello")).toEqual({
      name: "hello",
      phone: undefined,
      email: undefined,
    });
  });
});

describe("a lead handed over by the Chrome extension", () => {
  it("fills Add lead only from an add=lead link, trimmed and bounded", () => {
    const link = (query: string) => sharedLead(new URLSearchParams(query));
    expect(link("tab=all")).toBeNull();
    expect(link("add=lead")).toBeNull();
    expect(
      link(
        "add=lead&name=%20Asha%20Patil%20&phone=%2B91%2098765%2043210&note=From%20LinkedIn",
      ),
    ).toEqual({
      name: "Asha Patil",
      phone: "+91 98765 43210",
      email: "",
      note: "From LinkedIn",
    });
    expect(link(`add=lead&name=${"x".repeat(500)}`)?.name).toHaveLength(200);
  });
});
