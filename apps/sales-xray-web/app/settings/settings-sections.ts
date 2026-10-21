/**
 * Settings (owner, 20 Oct: "revamp the settings with all this"): one place for
 * the account, the organisation, connected apps, developers and devices. Each
 * section is its own address under /settings; older addresses map here. Pure.
 */
import {
  BellRing,
  Blocks,
  Bot,
  Building2,
  CircleUserRound,
  CreditCard,
  Code,
  LifeBuoy,
  Route,
  Sparkles,
  ShieldCheck,
  Smartphone,
  UsersRound,
  type LucideIcon,
} from "lucide-react";

export type SettingsSectionId =
  | "profile"
  | "security"
  | "plan"
  | "organisation"
  | "team"
  | "call-ai"
  | "apps"
  | "ai-replies"
  | "notifications"
  | "developers"
  | "devices"
  | "help";

export type SettingsSection = {
  id: SettingsSectionId;
  label: string;
  /** One line under the label in the list. */
  hint: string;
  icon: LucideIcon;
  group: "Account" | "Organisation" | "Connections" | "This device";
  /** Shown to organisation owners and admins only (the API decides the rest). */
  managers?: true;
};

export const SETTINGS_SECTIONS: readonly SettingsSection[] = [
  {
    id: "profile",
    label: "Profile",
    hint: "Your name, photo, phone and theme",
    icon: CircleUserRound,
    group: "Account",
  },
  {
    id: "security",
    label: "Sign-in & security",
    hint: "Google, Facebook and Apple sign-in, signing out",
    icon: ShieldCheck,
    group: "Account",
  },
  {
    id: "plan",
    label: "Plan & usage",
    hint: "Your plan, minutes left and invoices",
    icon: CreditCard,
    group: "Account",
  },
  {
    id: "organisation",
    label: "Organisation",
    hint: "Company details, logo and activity",
    icon: Building2,
    group: "Organisation",
  },
  {
    id: "team",
    label: "Team & roles",
    hint: "Members, invites and who can do what",
    icon: UsersRound,
    group: "Organisation",
  },
  {
    id: "call-ai",
    label: "AI on calls",
    hint: "How much AI reads each seller's recorded calls",
    icon: Sparkles,
    group: "Organisation",
    managers: true,
  },
  {
    id: "apps",
    label: "Connected apps",
    hint: "Lead ads, WhatsApp, Messenger and Instagram",
    icon: Blocks,
    group: "Connections",
    managers: true,
  },
  {
    id: "ai-replies",
    label: "AI replies",
    hint: "Suggested and automatic replies to leads",
    icon: Bot,
    group: "Connections",
    managers: true,
  },
  {
    id: "developers",
    label: "Developers",
    hint: "API keys, AI assistants (MCP), webhooks and the docs",
    icon: Code,
    group: "Connections",
    managers: true,
  },
  {
    id: "notifications",
    label: "Notifications",
    hint: "Lead alerts on your phone",
    icon: BellRing,
    group: "This device",
  },
  {
    id: "devices",
    label: "Apps & devices",
    hint: "The phone app and call recording",
    icon: Smartphone,
    group: "This device",
  },
  {
    id: "help",
    label: "Help & support",
    hint: "First call guide and support",
    icon: LifeBuoy,
    group: "This device",
  },
];

/**
 * Settings that live with their own work and are listed here so they are easy
 * to find; each opens its own page. Lead stages live in Leads (lead journey
 * session, 20 Oct).
 */
export type SettingsLink = Omit<SettingsSection, "id"> & {
  key: string;
  href: string;
};

export const SETTINGS_LINKS: readonly SettingsLink[] = [
  {
    key: "lead-stages",
    label: "Lead stages",
    hint: "Your stages from an industry template, and what each tells your ad platforms",
    icon: Route,
    group: "Organisation",
    managers: true,
    href: "/leads?tab=stages",
  },
];

export const SETTINGS_GROUPS = [
  "Account",
  "Organisation",
  "Connections",
  "This device",
] as const;

export const isSettingsSection = (
  value: string | null | undefined,
): value is SettingsSectionId =>
  SETTINGS_SECTIONS.some((section) => section.id === value);

export const sectionById = (id: SettingsSectionId) =>
  SETTINGS_SECTIONS.find((section) => section.id === id) as SettingsSection;

/** The account dialog's old section names (#settings/<name>, /account#<name>). */
const LEGACY: Record<string, SettingsSectionId> = {
  general: "profile",
  profile: "profile",
  usage: "plan",
  billing: "plan",
  security: "security",
  help: "help",
};

/** The address of a section, from a new or an old section name; Settings itself without one. */
export function settingsPath(section?: string | null): string {
  const name = (section ?? "").trim().toLowerCase();
  if (isSettingsSection(name)) return `/settings/${name}`;
  const legacy = LEGACY[name];
  return legacy ? `/settings/${legacy}` : "/settings";
}

/** Where an old /account address points: its #section or ?section=. */
export function accountRedirect(hash: string, search: string): string {
  const fromHash = hash.replace(/^#/, "").replace(/^settings\/?/, "");
  const fromQuery = new URLSearchParams(search).get("section");
  return settingsPath(fromHash || fromQuery);
}
