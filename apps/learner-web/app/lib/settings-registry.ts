/**
 * The learner settings surface is deliberately a small, closed vocabulary.
 * Keep this registry free of React, API clients, and route builders so it can
 * be used as a pure source of truth by the index, cards, and contract tests.
 */

export const SETTINGS_SECTION_IDS = [
  "verified-account",
  "appearance",
  "learning-setup",
  "security-privacy",
  "session",
] as const;

export type SettingsSectionId = (typeof SETTINGS_SECTION_IDS)[number];

export type SettingsSectionScreenId =
  | "SET-01"
  | "SET-02"
  | "SET-03"
  | "SET-04"
  | "SET-05";

export type SettingsSectionIconName =
  | "account"
  | "appearance"
  | "learning"
  | "security"
  | "session";

export type SettingsSectionGroupId = "account" | "setup" | "security";

export type SettingsSectionOwner =
  | "identity"
  | "frontend/settings"
  | "person profile"
  | "identity/settings";

export type SettingsSectionDefinition = {
  id: SettingsSectionId;
  screenId: SettingsSectionScreenId;
  anchor: SettingsSectionId;
  headingId: `${SettingsSectionId}-title`;
  icon: SettingsSectionIconName;
  groupId: SettingsSectionGroupId;
  label: string;
  detail: string;
  title: string;
  description: string;
  owner: SettingsSectionOwner;
  source: string;
};

/**
 * SET-01..SET-05 are the only settings sections currently contracted for the
 * authenticated learner surface. Ordering is intentional: it is shared by
 * the index and the rendered cards, and must not be inferred at call sites.
 */
export const SETTINGS_SECTIONS = [
  {
    id: "verified-account",
    screenId: "SET-01",
    anchor: "verified-account",
    headingId: "verified-account-title",
    icon: "account",
    groupId: "account",
    label: "Verified account",
    detail: "Your identity and verification",
    title: "Verified account",
    description: "Your identity and verification details.",
    owner: "identity",
    source: "/v1/me",
  },
  {
    id: "appearance",
    screenId: "SET-02",
    anchor: "appearance",
    headingId: "appearance-title",
    icon: "appearance",
    groupId: "setup",
    label: "Appearance",
    detail: "Theme and display",
    title: "Appearance",
    description: "Choose how Authority Closers LMS looks.",
    owner: "frontend/settings",
    source:
      "device-local ac-appearance-theme, ac-appearance-accent, ac-appearance-density, ac-appearance-motion",
  },
  {
    id: "learning-setup",
    screenId: "SET-03",
    anchor: "learning-setup",
    headingId: "learning-setup-title",
    icon: "learning",
    groupId: "setup",
    label: "Learning setup",
    detail: "Your learning preferences",
    title: "Learning setup",
    description: "Your learning preferences.",
    owner: "person profile",
    source: "/v1/onboarding",
  },
  {
    id: "security-privacy",
    screenId: "SET-04",
    anchor: "security-privacy",
    headingId: "security-privacy-title",
    icon: "security",
    groupId: "security",
    label: "Security & privacy",
    detail: "Account and privacy",
    title: "Security & privacy",
    description: "Review important policies and account support.",
    owner: "identity/settings",
    source: "existing identity recovery and Terms/Privacy routes",
  },
  {
    id: "session",
    screenId: "SET-05",
    anchor: "session",
    headingId: "session-title",
    icon: "session",
    groupId: "security",
    label: "Session",
    detail: "Sign out",
    title: "Session",
    description: "Sign out of your account on this device.",
    owner: "identity/settings",
    source: "same-origin logout",
  },
] as const satisfies readonly SettingsSectionDefinition[];

/**
 * Presentation-only group labels keep the index scannable without widening
 * the contracted SET-01..SET-05 vocabulary or changing card order.
 */
export const SETTINGS_SECTION_GROUPS = [
  {
    id: "account",
    label: "Account",
    detail: "Identity and verification",
  },
  {
    id: "setup",
    label: "Setup & preferences",
    detail: "Presentation and learning context",
  },
  {
    id: "security",
    label: "Security & access",
    detail: "Policies and current session",
  },
] as const satisfies ReadonlyArray<{
  id: SettingsSectionGroupId;
  label: string;
  detail: string;
}>;

export type SettingsSection = (typeof SETTINGS_SECTIONS)[number];

/** Return the contracted section for a URL hash without touching browser state. */
export function getSettingsSectionByAnchor(
  anchor: string,
): SettingsSection | undefined {
  return SETTINGS_SECTIONS.find((section) => section.anchor === anchor);
}

/** Alias for callers that need to name the source explicitly as a registry. */
export const SETTINGS_SECTION_REGISTRY = SETTINGS_SECTIONS;
