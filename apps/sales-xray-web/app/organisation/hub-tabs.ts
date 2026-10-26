/**
 * The organisation hub's sections, in one list for the hub's tab row and the
 * sidebar's Team panel (orchestrator, 26 Oct 2026: "the same section list
 * everywhere, in the same order"). A module of its own, so the sidebar
 * doesn't load the hub to list them.
 */

import {
  BarChart3,
  Building2,
  CreditCard,
  LayoutGrid,
  Lightbulb,
  Plug,
  Route,
  Sparkles,
  UsersRound,
  type LucideIcon,
} from "lucide-react";

export const HUB_PATH = "/organisation";

export type HubTab = {
  id: string;
  label: string;
  /** What the area is for, in the Overview list. */
  note: string;
  icon: LucideIcon;
  /** Opens its own page instead of a tab here. */
  href?: string;
  managers?: true;
};

export const HUB_TABS: readonly HubTab[] = [
  {
    id: "overview",
    label: "Overview",
    note: "Everything your organisation can set and see",
    icon: LayoutGrid,
  },
  {
    id: "team",
    label: "Team",
    note: "Members, invites and who can do what",
    icon: UsersRound,
  },
  {
    id: "analytics",
    label: "Analytics",
    note: "Calls and activity over the last 30 days, person by person",
    icon: BarChart3,
  },
  {
    id: "insights",
    label: "Insights",
    note: "What your team's calls show: skills, objections, coaching",
    icon: Lightbulb,
    href: "/organisation/insights",
    managers: true,
  },
  {
    id: "leads",
    label: "Leads setup",
    note: "Who gets new leads, your stages and where leads come from",
    icon: Route,
    managers: true,
  },
  {
    id: "connections",
    label: "Connections",
    note: "Lead ads, WhatsApp and Instagram, AI replies, API keys, Pulse",
    icon: Plug,
    managers: true,
  },
  {
    id: "call-ai",
    label: "AI on calls",
    note: "How much AI reads each seller's recorded calls",
    icon: Sparkles,
    managers: true,
  },
  {
    id: "company",
    label: "Company",
    note: "Name, logo, details and your email domains",
    icon: Building2,
  },
  {
    id: "plan",
    label: "Plan & billing",
    note: "Your plan, analysis time and invoices",
    icon: CreditCard,
    href: "/settings/plan",
    managers: true,
  },
];

/** A tab's address: its own page, or the hub with ?tab=. */
export function hubHref(
  tab: HubTab,
  part?: string,
  base: string = HUB_PATH,
): string {
  if (tab.href) return tab.href;
  const query = [
    tab.id === "overview" ? "" : `tab=${tab.id}`,
    part ? `part=${part}` : "",
  ]
    .filter(Boolean)
    .join("&");
  return query ? `${base}?${query}` : base;
}
