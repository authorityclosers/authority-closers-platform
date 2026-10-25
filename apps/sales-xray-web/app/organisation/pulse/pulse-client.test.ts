import { afterEach, expect, it, vi } from "vitest";

import {
  parsePulseState,
  pulseReturnNotice,
  readPulse,
  readPulsePeople,
  startPulseLink,
} from "./pulse-client";

afterEach(() => vi.unstubAllGlobals());

const linked = {
  schema: "sx-pulse/1",
  configured: true,
  issuer: "https://pulse.example.test",
  link: {
    status: "active",
    pulse_org_id: "org-1",
    pulse_org_name: "Greenleaf Realty (test)",
    linked_at: "2026-10-25T10:00:00Z",
    linked_by: "Tara Kapoor",
    scopes: ["openid", "pulse.org.read", "pulse.org.webhooks"],
    sharing: { directory: "read", photos: "off", signals: "write" },
    webhooks: true,
    last_sync_at: "2026-10-25T10:01:00Z",
    last_sync: { seen: 3, matched: 1, missing: 1, problem: null },
  },
  members: [
    {
      id: "m1",
      name: "Rohan Iyer",
      email: "rohan.iyer@example.test",
      title: "Sales executive",
      team: "Inside sales",
      pulse_role: "member",
      status: "active",
      photo_url: "/v1/sales-xray/pulse/members/m1/photo",
      person_id: null,
      matched_by: null,
      can_invite: true,
      invited_at: null,
    },
    {
      id: "m2",
      name: "Kiran Mehta",
      photo_url: "https://evil.example.test/p.jpg",
      person_id: "p2",
      matched_by: "pulse_sign_in",
    },
    { name: "no id" },
  ],
  pulse_access: [
    { id: "g1", scopes: ["calls:read", "leads:write"], created_at: "2026-10-20T00:00:00Z" },
  ],
};

it("reads the link, the directory and Pulse's access, keeping only its own photo route", () => {
  const state = parsePulseState(linked);
  expect(state?.configured).toBe(true);
  expect(state?.link?.orgName).toBe("Greenleaf Realty (test)");
  expect(state?.link?.sharing).toEqual({
    directory: "read",
    photos: "off",
    signals: "write",
  });
  expect(state?.link?.lastSync.matched).toBe(1);
  expect(state?.members.map((member) => member.id)).toEqual(["m1", "m2"]);
  expect(state?.members[0].photoUrl).toBe("/v1/sales-xray/pulse/members/m1/photo");
  expect(state?.members[1].photoUrl).toBeNull();
  expect(state?.members[1].matchedBy).toBe("pulse_sign_in");
  expect(state?.access[0].scopes).toEqual(["calls:read", "leads:write"]);
  expect(parsePulseState({ ...linked, schema: "other" })).toBeNull();
  expect(parsePulseState({ ...linked, link: null })?.link).toBeNull();
});

it("hides Pulse from people who may not manage it, and when it isn't offered", async () => {
  for (const status of [401, 403, 404]) {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("{}", { status })),
    );
    expect(await readPulse()).toBeNull();
  }
});

it("goes to Pulse only at an address the server gave", async () => {
  const fetcher = vi.fn(async () =>
    Response.json({
      redirect_url: "https://pulse.example.test/oauth/authorize?x=1",
    }),
  );
  vi.stubGlobal("fetch", fetcher);
  expect(await startPulseLink()).toBe(
    "https://pulse.example.test/oauth/authorize?x=1",
  );
  const [, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
  expect(init.method).toBe("POST");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ redirect_url: "javascript:alert(1)" })),
  );
  await expect(startPulseLink()).rejects.toThrow();
});

it("reads Pulse titles and photos for member lists, nothing on refusal", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json({
        people: {
          p1: {
            title: "Founder",
            team: "Leadership",
            photo_url: "/v1/people/p1/photo?v=3f9c0a1b",
          },
          p2: { title: null, photo_url: "//elsewhere/p.jpg" },
        },
      }),
    ),
  );
  const people = await readPulsePeople();
  expect(people.p1).toEqual({
    title: "Founder",
    team: "Leadership",
    photoUrl: "/v1/people/p1/photo?v=3f9c0a1b",
  });
  expect(people.p2.photoUrl).toBeNull();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("", { status: 403 })),
  );
  expect(await readPulsePeople()).toEqual({});
});

it("says what happened on the way back from Pulse", () => {
  expect(pulseReturnNotice(null)).toBeNull();
  expect(pulseReturnNotice("connected")?.tone).toBe("success");
  expect(pulseReturnNotice("org_taken")?.message).toContain(
    "already linked to another organisation",
  );
  expect(pulseReturnNotice("anything")?.tone).toBe("error");
});
