// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

import { TesterActions } from "./tester-actions";
import {
  aboutLine,
  inView,
  nextStep,
  normalizeTesters,
  testerView,
  type Tester,
} from "./testers-data";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const RAW = {
  items: [
    {
      id: ID,
      email: "ravi.tester@example.test",
      name: "Ravi Tester",
      source: "applied",
      stage: "applied",
      phone_model: "Redmi 13",
      role: "seller",
      business: "Solar panels",
      applied_at: "2026-11-13T10:00:00+00:00",
      has_account: true,
      app_sessions: 0,
      bugs: 0,
    },
    {
      id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      email: "asha.tester@example.test",
      source: "listed",
      stage: "active",
      app_version: "1.0.99",
      last_app_at: "2026-11-12T10:00:00+00:00",
      bugs: 2,
      email_status: "sent",
      emailed_via: "gmail",
    },
    { id: "not-a-uuid", email: "x@example.test", stage: "active" },
    { id: ID, email: "y@example.test", stage: "somewhere" },
  ],
  counts: { applied: 1, active: 1 },
  feedback: 1,
  active: 1,
  play_needs: 12,
  group: {
    email: "salesxray-testers@authorityclosers.com",
    members_url: "https://evil.example/members",
  },
};

describe("the tester list", () => {
  it("reads the list defensively and keeps Google's own group link", () => {
    const page = normalizeTesters(RAW);
    expect(page.items.map((item) => item.email)).toEqual([
      "ravi.tester@example.test",
      "asha.tester@example.test",
    ]);
    expect(page.counts.applied).toBe(1);
    expect(page.counts.declined).toBe(0);
    expect(page.playNeeds).toBe(12);
    expect(page.groupUrl).toBe(
      "https://groups.google.com/a/authorityclosers.com/g/salesxray-testers/members",
    );
    expect(page.items[1]).toMatchObject({
      appVersion: "1.0.99",
      bugs: 2,
      emailedVia: "gmail",
      emailStatus: "sent",
    });
    const empty = normalizeTesters({});
    expect(empty.items).toEqual([]);
    expect(empty.activeDays).toBe(7);
  });

  it("filters by the chosen tab and says what they told us", () => {
    const page = normalizeTesters(RAW);
    expect(testerView("active")).toBe("active");
    expect(testerView(["feedback"])).toBe("feedback");
    expect(testerView("nonsense")).toBe("all");
    expect(inView(page.items, "feedback").map((item) => item.email)).toEqual([
      "asha.tester@example.test",
    ]);
    expect(inView(page.items, "applied")).toHaveLength(1);
    expect(inView(page.items, "all")).toHaveLength(2);
    expect(aboutLine(page.items[0]!)).toBe(
      "Redmi 13 · Salesperson · Solar panels",
    );
  });

  it("names the team's next step for each stage", () => {
    const page = normalizeTesters(RAW);
    const at = (stage: Tester["stage"]) =>
      nextStep({ ...page.items[0]!, stage });
    expect(at("applied")).toBe("review");
    expect(at("approved")).toBe("add_to_group");
    expect(at("in_group")).toBe("send_email");
    expect(at("emailed")).toBe("send_again");
    expect(at("declined")).toBe("reconsider");
    expect(at("installed")).toBeNull();
    expect(at("active")).toBeNull();
  });
});

describe("the team's buttons", () => {
  let root: Root;
  let host: HTMLDivElement;

  beforeEach(() => {
    refresh.mockReset();
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
    vi.unstubAllGlobals();
  });

  const tester = (stage: Tester["stage"]) => ({
    ...normalizeTesters(RAW).items[0]!,
    stage,
  });
  const buttons = () =>
    [...host.querySelectorAll("button")].map((item) => item.textContent);
  const click = (label: string) =>
    act(async () => {
      [...host.querySelectorAll("button")]
        .find((item) => item.textContent === label)!
        .click();
    });

  it("approves an application and refreshes the list", async () => {
    const fetcher = vi.fn(
      async () =>
        new Response("{}", {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetcher);
    await act(async () =>
      root.render(
        <TesterActions
          tester={tester("applied")}
          groupUrl="https://groups.google.com/x"
        />,
      ),
    );
    expect(buttons()).toEqual(["Approve", "Decline"]);
    await click("Approve");
    expect(fetcher).toHaveBeenCalledWith(
      `/v1/admin/testers/${ID}/decision`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ decision: "approve" }),
      }),
    );
    expect(refresh).toHaveBeenCalled();
  });

  it("copies the address and opens the group, then marks them added and emails", async () => {
    const fetcher = vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "Approve them first." }), {
          status: 422,
          headers: { "content-type": "application/json" },
        }),
    );
    const writeText = vi.fn(async () => undefined);
    const open = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    vi.stubGlobal("open", open);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    await act(async () =>
      root.render(
        <TesterActions
          tester={tester("approved")}
          groupUrl="https://groups.google.com/x"
        />,
      ),
    );
    expect(buttons()).toEqual(["Add to group", "Added, send email"]);
    await click("Add to group");
    expect(writeText).toHaveBeenCalledWith("ravi.tester@example.test");
    expect(open).toHaveBeenCalledWith(
      "https://groups.google.com/x",
      "_blank",
      "noopener,noreferrer",
    );
    expect(host.textContent).toContain("Address copied");
    await click("Added, send email");
    expect(fetcher).toHaveBeenCalledWith(
      `/v1/admin/testers/${ID}/group`,
      expect.objectContaining({ body: JSON.stringify({ send_email: true }) }),
    );
    expect(host.querySelector('[role="alert"]')?.textContent).toBe(
      "Approve them first.",
    );
    expect(refresh).not.toHaveBeenCalled();
  });

  it("shows nothing for a tester already in the app", async () => {
    await act(async () =>
      root.render(
        <TesterActions
          tester={tester("active")}
          groupUrl="https://groups.google.com/x"
        />,
      ),
    );
    expect(host.textContent).toBe("");
  });
});
