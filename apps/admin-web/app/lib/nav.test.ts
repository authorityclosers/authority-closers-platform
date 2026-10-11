import { describe, expect, it } from "vitest";

import { commandEntries } from "../ui/command-menu";
import {
  activeHref,
  isSalesXrayControl,
  visibleNavigation,
  type ConsoleAccess,
} from "./nav";

const base: ConsoleAccess = {
  state: "verified",
  email: "dipak@authorityclosers.com",
  displayName: "Dipak",
  role: "admin",
  permissions: ["admin_surface"],
  platform: [],
};
const hrefs = (access: ConsoleAccess) =>
  visibleNavigation(access).flatMap((group) =>
    group.items.map((item) => item.href),
  );

describe("console navigation", () => {
  it("shows Sales Xray sections only to verified control accounts with admin rights", () => {
    expect(isSalesXrayControl(base)).toBe(true);
    expect(
      isSalesXrayControl({ ...base, email: "DIPAK@authorityclosers.com " }),
    ).toBe(true);
    expect(isSalesXrayControl({ ...base, email: "coach@example.com" })).toBe(
      false,
    );
    expect(isSalesXrayControl({ ...base, role: "member" })).toBe(false);
    expect(isSalesXrayControl({ ...base, permissions: [] })).toBe(false);
    expect(isSalesXrayControl({ ...base, state: "unavailable" })).toBe(false);
    expect(hrefs(base)).toContain("/calls");
    expect(hrefs({ ...base, email: "coach@example.com" })).not.toContain(
      "/calls",
    );
  });

  it("gates platform sections by their named platform grants", () => {
    expect(hrefs(base)).not.toContain("/platform/organisations");
    expect(hrefs({ ...base, platform: ["platform_tenants_read"] })).toContain(
      "/platform/organisations",
    );
    expect(hrefs({ ...base, platform: ["platform_billing_manage"] })).toContain(
      "/platform?tab=billing",
    );
    expect(
      hrefs({ ...base, platform: ["platform_tenants_read"] }),
    ).not.toContain("/platform?tab=billing");
  });

  it("needs admin_surface plus the named permission for academy sections", () => {
    expect(
      hrefs({ ...base, permissions: ["admin_surface", "learner_diagnose"] }),
    ).toContain("/people");
    expect(hrefs({ ...base, permissions: ["learner_diagnose"] })).not.toContain(
      "/people",
    );
    expect(
      hrefs({ ...base, permissions: ["admin_surface", "job_retry"] }),
    ).toContain("/learning-operations");
  });

  it("lists only Home when the session can't be confirmed, and everything in local preview", () => {
    expect(hrefs({ ...base, state: "unavailable" })).toEqual(["/"]);
    expect(hrefs({ ...base, state: "preview", email: null })).toContain(
      "/platform/organisations",
    );
  });

  it("lists every built section in local preview", () => {
    const everything = hrefs({ ...base, state: "preview" });
    expect(everything).toContain("/gold");
    expect(everything).toContain("/safety");
  });

  it("marks the most specific matching section, including query-addressed tabs", () => {
    const groups = visibleNavigation({ ...base, state: "preview" });
    expect(activeHref("/", groups)).toBe("/");
    expect(activeHref("/calls/abc", groups)).toBe("/calls");
    expect(activeHref("/sales-xray/review/report/abc", groups)).toBe(
      "/reviewers",
    );
    expect(activeHref("/sales-xray/providers", groups, "tab=benchmark")).toBe(
      "/sales-xray/providers",
    );
    expect(activeHref("/platform", groups)).toBe("/platform");
    expect(activeHref("/platform", groups, "tab=billing")).toBe(
      "/platform?tab=billing",
    );
    expect(activeHref("/platform/organisations", groups)).toBe(
      "/platform/organisations",
    );
    expect(activeHref("/nowhere", groups)).toBeNull();
  });

  it("finds sections by name and opens a pasted call id", () => {
    const groups = visibleNavigation(base);
    expect(commandEntries(groups, "prov").map((entry) => entry.href)).toEqual([
      "/sales-xray/providers",
    ]);
    const id = "0f8c1f8e-1d2b-4c3d-9e4f-5a6b7c8d9e0f";
    expect(commandEntries(groups, ` ${id.toUpperCase()} `)[0]?.href).toBe(
      `/calls/${id}`,
    );
    expect(commandEntries(groups, "zzz")).toEqual([]);
  });
});
