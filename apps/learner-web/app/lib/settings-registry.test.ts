import { describe, expect, it } from "vitest";

import {
  SETTINGS_SECTION_GROUPS,
  SETTINGS_SECTION_IDS,
  SETTINGS_SECTION_REGISTRY,
  SETTINGS_SECTIONS,
  getSettingsSectionByAnchor,
} from "./settings-registry";

const expectedIds = [
  "verified-account",
  "appearance",
  "learning-setup",
  "security-privacy",
  "session",
] as const;

const expectedScreenAnchors = [
  ["SET-01", "verified-account"],
  ["SET-02", "appearance"],
  ["SET-03", "learning-setup"],
  ["SET-04", "security-privacy"],
  ["SET-05", "session"],
] as const;

describe("learner settings registry", () => {
  it("contains exactly the contracted sections in contract order", () => {
    expect(SETTINGS_SECTION_IDS).toEqual(expectedIds);
    expect(SETTINGS_SECTIONS).toHaveLength(5);
    expect(SETTINGS_SECTIONS.map((section) => section.id)).toEqual(expectedIds);
    expect(SETTINGS_SECTIONS.map((section) => section.screenId)).toEqual([
      "SET-01",
      "SET-02",
      "SET-03",
      "SET-04",
      "SET-05",
    ]);
    expect(
      SETTINGS_SECTIONS.map((section) => [section.screenId, section.anchor]),
    ).toEqual(expectedScreenAnchors);
    expect(SETTINGS_SECTION_REGISTRY).toBe(SETTINGS_SECTIONS);
  });

  it("groups the same contracted sections for index presentation only", () => {
    expect(SETTINGS_SECTION_GROUPS.map((group) => group.id)).toEqual([
      "account",
      "setup",
      "security",
    ]);
    expect(SETTINGS_SECTION_GROUPS.map((group) => group.label)).toEqual([
      "Account",
      "Setup & preferences",
      "Security & access",
    ]);
    expect(SETTINGS_SECTIONS.map((section) => section.groupId)).toEqual([
      "account",
      "setup",
      "setup",
      "security",
      "security",
    ]);
    expect(
      SETTINGS_SECTION_GROUPS.every((group) =>
        SETTINGS_SECTIONS.some((section) => section.groupId === group.id),
      ),
    ).toBe(true);
  });

  it("gives every section a unique stable anchor and heading target", () => {
    const anchors = SETTINGS_SECTIONS.map((section) => section.anchor);
    const headingIds = SETTINGS_SECTIONS.map((section) => section.headingId);

    expect(new Set(anchors).size).toBe(SETTINGS_SECTIONS.length);
    expect(new Set(headingIds).size).toBe(SETTINGS_SECTIONS.length);
    expect(anchors).toEqual(expectedIds);
    expect(headingIds).toEqual(
      expectedIds.map((sectionId) => `${sectionId}-title`),
    );
    expect(
      SETTINGS_SECTIONS.every((section) => section.anchor === section.id),
    ).toBe(true);
    expect(getSettingsSectionByAnchor("appearance")?.screenId).toBe("SET-02");
    expect(getSettingsSectionByAnchor("unsupported") ?? null).toBeNull();
  });

  it("records the existing source owner for each bounded capability", () => {
    expect(SETTINGS_SECTIONS.map((section) => section.owner)).toEqual([
      "identity",
      "frontend/settings",
      "person profile",
      "identity/settings",
      "identity/settings",
    ]);
    expect(SETTINGS_SECTIONS.map((section) => section.source)).toEqual([
      "/v1/me",
      "device-local ac-appearance-theme, ac-appearance-accent, ac-appearance-density, ac-appearance-motion",
      "/v1/onboarding",
      "existing identity recovery and Terms/Privacy routes",
      "same-origin logout",
    ]);
  });

  it("does not widen the registry into blocked settings categories", () => {
    expect(JSON.stringify(SETTINGS_SECTIONS)).not.toMatch(
      /notification|marketing|payment|deletion|mfa|sso|\bai\b|playback|tenant.?branding/i,
    );
  });
});
