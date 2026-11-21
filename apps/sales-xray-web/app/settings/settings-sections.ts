/**
 * Settings (owner, 20 Oct: "revamp the settings with all this"): one place for
 * the account, the organisation, connected apps, developers and devices. Each
 * section is its own address under /settings; older addresses map here. Pure.
 *
 * Owner's round-2 board 7 (option A, 20 Nov 2026): one Settings, grouped the
 * way an owner thinks (Team, Leads, Calls & phones, Connections, Company, Plan
 * & billing), then Just me and This phone; every group says who it affects
 * (Everyone in the organisation, Just me, This phone). The Organisation hub's
 * settings live here again and its old addresses come here (org-hub.tsx).
 */
import {
  Activity,
  BellRing,
  Blocks,
  Bot,
  Building2,
  CircleUserRound,
  ClipboardList,
  Clock,
  Filter,
  Phone,
  Plug,
  CreditCard,
  Code,
  LifeBuoy,
  Link2,
  Music2,
  PhoneCall,
  Route,
  Sparkles,
  ShieldCheck,
  Smartphone,
  SmartphoneNfc,
  UsersRound,
  type LucideIcon,
} from "lucide-react";

import type { Capability } from "../organisation/roles";
import type { SettingScope } from "./scope-chip";

export type SettingsSectionId =
  | "profile"
  | "selling"
  | "security"
  | "ai-apps"
  | "plan"
  | "analysis-time"
  | "privacy"
  | "sounds"
  | "organisation"
  | "team"
  | "lead-rules"
  | "stages"
  | "call-ai"
  | "phones"
  | "team-sounds"
  | "sources"
  | "apps"
  | "ai-replies"
  | "notifications"
  | "developers"
  | "pulse"
  | "devices"
  | "help";

export type SettingsGroup =
  | "Team"
  | "Leads"
  | "Calls & phones"
  | "Connections"
  | "Company"
  | "Plan & billing"
  | "Just me"
  | "This phone";

export type SettingsSection = {
  id: SettingsSectionId;
  label: string;
  /** One line under the label in the list. */
  hint: string;
  icon: LucideIcon;
  group: SettingsGroup;
  /**
   * Shown only to roles with this capability (roles.ts), the one its API's
   * server guard asks for; the API still decides the rest.
   */
  needs?: Capability;
  /** The organisation's own: listed only inside an organisation (its address still works). */
  org?: true;
  /** Opens inside that section's screen, so it isn't listed on its own (its address still works). */
  within?: SettingsSectionId;
};

export const SETTINGS_SECTIONS: readonly SettingsSection[] = [
  {
    id: "team",
    label: "Team & roles",
    hint: "Members, invites and who can do what",
    icon: UsersRound,
    group: "Team",
    org: true,
  },
  {
    // Approved map, slice 5 (22 Oct 2026): Leads' own settings live here.
    id: "lead-rules",
    label: "Lead rules",
    hint: "Who gets new leads, limits, reassigning and work hours",
    icon: ClipboardList,
    group: "Leads",
    needs: "leads.manage",
    org: true,
  },
  {
    id: "stages",
    label: "Lead stages",
    hint: "What your sellers see",
    icon: Route,
    group: "Leads",
    needs: "leads.manage",
    org: true,
  },
  {
    id: "sources",
    label: "Lead sources",
    hint: "Lead forms, sheets, webhooks and imports",
    icon: Plug,
    group: "Leads",
    needs: "leads.manage",
    org: true,
  },
  {
    // Board 7's phone setup policy: each seller's phone, ready or what's missing.
    id: "phones",
    label: "Sellers' phones",
    hint: "Each seller's phone: ready to record, or what's missing",
    icon: SmartphoneNfc,
    group: "Calls & phones",
    needs: "team.view",
    org: true,
  },
  {
    id: "call-ai",
    label: "AI on calls",
    hint: "How much AI reads each seller's recorded calls",
    icon: Sparkles,
    group: "Calls & phones",
    needs: "leads.manage",
    org: true,
  },
  {
    // Owner's round-2 board 4: the team's sound for each moment.
    id: "team-sounds",
    label: "Sounds for everyone",
    hint: "The team's sound for each moment, and whether sellers pick their own",
    icon: Music2,
    group: "Calls & phones",
    needs: "leads.manage",
    org: true,
  },
  {
    id: "apps",
    label: "Connected apps",
    hint: "Lead ads, WhatsApp, Messenger and Instagram",
    icon: Blocks,
    group: "Connections",
    needs: "leads.manage",
    org: true,
  },
  {
    id: "ai-replies",
    label: "AI replies",
    hint: "Suggested and automatic replies to leads",
    icon: Bot,
    group: "Connections",
    needs: "leads.manage",
    org: true,
  },
  {
    id: "developers",
    label: "Developers",
    hint: "API keys, AI assistants (MCP), webhooks and the docs",
    icon: Code,
    group: "Connections",
    needs: "org.manage",
    org: true,
  },
  {
    // Owner, 25 Oct 2026: an organisation links its Pulse org.
    id: "pulse",
    label: "Pulse",
    hint: "Your team's profiles from Pulse, and what you share with it",
    icon: Link2,
    group: "Connections",
    needs: "org.manage",
    org: true,
  },
  {
    id: "organisation",
    label: "Company",
    hint: "Name, logo, details and your email domains",
    icon: Building2,
    group: "Company",
    org: true,
  },
  {
    id: "plan",
    label: "Plan & billing",
    hint: "Your plan, seats and invoices",
    icon: CreditCard,
    group: "Plan & billing",
    // Billing belongs to whoever pays: the person in a personal workspace,
    // in an organisation the roles that see billing (workspace-role.ts).
    needs: "billing.view",
  },
  {
    // Everyone, members too: how much analysis is left and who adds more
    // (orchestrator, 13 Nov 2026). Time only, never a price.
    id: "analysis-time",
    label: "Analysis time",
    hint: "How much call analysis you have left",
    icon: Clock,
    group: "Plan & billing",
  },
  {
    id: "profile",
    label: "Profile",
    hint: "Your name, photo, phone and theme",
    icon: CircleUserRound,
    group: "Just me",
  },
  {
    // Owner, 22 Oct 2026: salespeople need "much more settings".
    id: "selling",
    label: "Selling",
    hint: "Taking new leads, calling from your phone, alerts, AI on your calls",
    icon: PhoneCall,
    group: "Just me",
  },
  {
    // Owner's round-2 board 4 (option B, 20 Nov 2026): a sound for each
    // moment, hear it as you pick; the team's unless you pick your own.
    id: "sounds",
    label: "Sounds & alerts",
    hint: "A sound for each moment: new lead, call, follow-up, report",
    icon: Music2,
    group: "Just me",
  },
  {
    id: "security",
    label: "Sign-in & security",
    hint: "Google, Facebook and Apple sign-in, signing out",
    icon: ShieldCheck,
    group: "Just me",
  },
  {
    // Owner via the orchestrator, 24 Oct 2026: the AI apps a person connected
    // (Pulse, ChatGPT, Claude) had no screen; everyone, members too.
    id: "ai-apps",
    label: "AI apps",
    hint: "ChatGPT, Claude and Pulse with your calls and leads",
    icon: Sparkles,
    group: "Just me",
  },
  {
    // Owner, 24 Oct 2026: usage analytics on by default, each person can turn it off.
    id: "privacy",
    label: "Privacy",
    hint: "Usage analytics, for you and your workspace",
    icon: Activity,
    group: "Just me",
    // Owner, 24 Oct 2026: one screen for your own switches.
    within: "notifications",
  },
  {
    id: "help",
    label: "Help & support",
    hint: "First call guide and support",
    icon: LifeBuoy,
    group: "Just me",
  },
  {
    id: "notifications",
    label: "Phone & alerts",
    hint: "Phone setup, alerts, vibration and usage analytics",
    icon: BellRing,
    group: "This phone",
  },
  {
    id: "devices",
    label: "Apps & devices",
    hint: "The phone app and call recording",
    icon: Smartphone,
    group: "This phone",
    within: "notifications",
  },
];

export const SETTINGS_GROUPS: readonly SettingsGroup[] = [
  "Team",
  "Leads",
  "Calls & phones",
  "Connections",
  "Company",
  "Plan & billing",
  "Just me",
  "This phone",
];

/**
 * The Settings hub (sx-redesign board pick C "Summary first", owner 21 Nov
 * 2026): each group is one card that opens its own page (/settings/group/<slug>)
 * listing its sections, or the section itself when it has only one. "Just me"
 * holds "This phone" too, so an owner sees six company cards and one of their own.
 */
export const GROUP_SLUG: Record<SettingsGroup, string> = {
  Team: "team",
  Leads: "leads",
  "Calls & phones": "calls-phones",
  Connections: "connections",
  Company: "company",
  "Plan & billing": "plan-billing",
  "Just me": "just-me",
  "This phone": "this-phone",
};

/** One short line under a group's name when nothing better is known. */
export const GROUP_LINE: Record<SettingsGroup, string> = {
  Team: "People and what they can do",
  Leads: "Rules, stages and sources",
  "Calls & phones": "Phones, AI on calls, sounds",
  Connections: "Apps, AI replies, developers",
  Company: "Name, logo and details",
  "Plan & billing": "Plan and analysis time",
  "Just me": "Profile, sounds, sign-in, this phone",
  "This phone": "Phone setup and alerts",
};

export const GROUP_ICON: Record<SettingsGroup, LucideIcon> = {
  Team: UsersRound,
  Leads: Filter,
  "Calls & phones": Phone,
  Connections: Plug,
  Company: Building2,
  "Plan & billing": CreditCard,
  "Just me": CircleUserRound,
  "This phone": Smartphone,
};

/** The group a /settings/group/<slug> address names; null for anything else. */
export function groupBySlug(
  slug: string | null | undefined,
): SettingsGroup | null {
  const hit = SETTINGS_GROUPS.find((group) => GROUP_SLUG[group] === slug);
  return hit ?? null;
}

/** The groups a group page lists: "Just me" shows "This phone" under it. */
export function groupPageGroups(group: SettingsGroup): SettingsGroup[] {
  return group === "Just me" ? ["Just me", "This phone"] : [group];
}

/** Who a group's settings affect. */
export function groupScope(
  group: SettingsGroup,
  inOrganisation: boolean,
): SettingScope {
  if (group === "This phone") return "phone";
  if (group === "Just me" || !inOrganisation) return "me";
  return "everyone";
}

/**
 * Where an old Organisation hub address (/organisation?tab=…&part=…) lives in
 * Settings now (an unknown tab: Settings itself); null for Analytics, the
 * hub's own view, which stays there until the owner's Team today (board 6).
 */
export function hubTabSetting(
  tab: string | null,
  part: string | null,
): string | null {
  switch (tab ?? "overview") {
    case "overview":
      return "/settings";
    case "team":
      return "/settings/team";
    case "leads":
      return part === "stages"
        ? "/settings/stages"
        : part === "sources"
          ? "/settings/sources"
          : "/settings/lead-rules";
    case "connections":
      return part === "ai-replies" || part === "developers" || part === "pulse"
        ? `/settings/${part}`
        : "/settings/apps";
    case "call-ai":
      return "/settings/call-ai";
    case "company":
      return "/settings/organisation";
    case "plan":
      return "/settings/plan";
    case "analytics":
      return null;
    default:
      return "/settings";
  }
}

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
