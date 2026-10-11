import { describe, expect, it } from "vitest";

import {
  discoverRoutes,
  KNOWN,
  knownFault,
  PERSON_ID,
  PROTECTED,
  SIDEWAYS_WIDTHS,
  sidewaysProblems,
  WIDTH_ROUTES,
} from "./page-matrix.mjs";
import { answer, CALL_ID, fixtureFor, ROLES } from "./page-matrix-fixtures.mjs";

const now = Date.UTC(2026, 9, 10, 9);

describe("page matrix (AUT-1663)", () => {
  it("finds every app page, with fixture ids in dynamic segments", () => {
    const routes = discoverRoutes();
    for (const route of ["/", "/dashboard", "/organisation", "/analysis/calls"])
      expect(routes).toContain(route);
    expect(routes).toContain(`/analysis/calls/${CALL_ID}`);
    expect(routes).toContain(`/organisation/people/${PERSON_ID}`);
    expect(routes.every((route) => route.startsWith("/"))).toBe(true);
    expect(routes.some((route) => /[[\]()]/.test(route))).toBe(false);
    expect(new Set(routes).size).toBe(routes.length);
    for (const route of PROTECTED) expect(routes).toContain(route);
  });

  it("answers like a server: guests 401, unknown reads 404, never a write", () => {
    const owner = fixtureFor("owner", now);
    expect(answer({}, "guest", "GET", "/v1/me/workspaces", "").status).toBe(
      401,
    );
    expect(answer(owner, "owner", "GET", "/v1/me/workspaces", "").status).toBe(
      200,
    );
    expect(answer(owner, "owner", "GET", "/v1/not-deployed", "").status).toBe(
      404,
    );
    expect(
      answer(owner, "owner", "POST", "/v1/organisation/members", "").status,
    ).toBe(409);
    const activity = answer(
      owner,
      "owner",
      "GET",
      "/v1/organisation/activity",
      "?days=30",
    );
    expect(activity.status).toBe(200);
    expect(activity.body.calls.length).toBeGreaterThan(0);
    expect(
      answer(
        fixtureFor("personal", now),
        "personal",
        "GET",
        "/v1/organisation",
        "",
      ),
    ).toEqual({ status: 404, body: { detail: "No organisation selected." } });
  });

  it("gives a member only their own calls; owners and admins see whose each is", () => {
    const list = (role) =>
      fixtureFor(role, now)["/v1/conversation/acquisition/submissions"]
        .submissions;
    const member = list("member");
    expect(member.length).toBeGreaterThan(0);
    expect(member.some((row) => "owner_name" in row)).toBe(false);
    for (const role of ["owner", "admin"]) {
      const rows = list(role);
      expect(rows.length).toBeGreaterThan(member.length);
      expect(rows.every((row) => typeof row.owner_name === "string")).toBe(
        true,
      );
    }
    expect(ROLES).toEqual(["guest", "member", "admin", "owner", "personal"]);
  });

  it("names where each known fault is tracked, matched by route and role", () => {
    for (const [key, reason] of Object.entries(KNOWN)) {
      expect(key).toMatch(/^\/[^|]*\|(\*|guest|member|admin|owner|personal)$/);
      expect(reason.length).toBeGreaterThan(20);
    }
    // Fixed by Strike B (#420): a guest on Prospects is offered sign-in.
    expect(knownFault("/prospects", "guest")).toBeNull();
    expect(knownFault("/account", "member")).toBe(KNOWN["/account|*"]);
    expect(knownFault("/dashboard", "guest")).toBeNull();
  });
});

describe("sideways check (owner, 11 Oct: no side scroll bar)", () => {
  const clean = { width: 1280, document: 1280, scrollers: [], outside: [] };

  it("passes a page that fits the window", () => {
    expect(sidewaysProblems(clean)).toEqual([]);
  });

  it("fails a document, a scroll box or an element that is too wide", () => {
    expect(sidewaysProblems({ ...clean, document: 1296 })).toEqual([
      "scrolls sideways by 16 px",
    ]);
    expect(
      sidewaysProblems({
        ...clean,
        scrollers: [
          {
            name: "div.filters",
            by: 130,
            intended: false,
            overflowX: "auto",
          },
        ],
      }),
    ).toEqual([
      "div.filters is 130 px wider inside than its box (overflow-x: auto)",
    ]);
    expect(
      sidewaysProblems({
        ...clean,
        outside: [{ name: "table.calls", left: 340, right: 1410 }],
      }),
    ).toEqual([
      "table.calls is drawn past the window edge (340..1410 of 1280 px)",
    ]);
  });

  it("lets a sideways scroller on purpose (data-scroll-x) scroll", () => {
    expect(
      sidewaysProblems({
        ...clean,
        scrollers: [
          { name: "div.chips", by: 324, intended: true, overflowX: "auto" },
        ],
      }),
    ).toEqual([]);
  });

  it("checks the signed-in pages at phone, tablet and laptop widths", () => {
    expect(SIDEWAYS_WIDTHS.map(([width]) => width)).toEqual([
      360, 768, 1024, 1280,
    ]);
    for (const route of ["/dashboard", "/analysis/new", "/analysis/calls"])
      expect(WIDTH_ROUTES).toContain(route);
  });
});
