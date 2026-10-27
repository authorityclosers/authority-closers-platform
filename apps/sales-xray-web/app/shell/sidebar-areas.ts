import {
  AudioLines,
  Contact,
  GraduationCap,
  LayoutGrid,
  LineChart,
  MessagesSquare,
  Users,
  UsersRound,
  type LucideIcon,
} from "lucide-react";

import { HUB_TABS, hubHref } from "../organisation/hub-tabs";

/**
 * The sidebar's areas and their pages (owner, dev #8, 26 Oct 2026: the one
 * long list was "cluttered, no clean distinctions"). As Pulse draws it, the
 * ribbon shows the areas and the panel beside it only the current area's
 * pages; both are drawn from this list.
 */
export type AreaKey = "home" | "work" | "team" | "results";

/** A page's sub-place: text only under it, lit while the page shows its ?tab=. */
export type SidebarSub = {
  label: string;
  href: string;
  path: string;
  tab: string;
};

export type SidebarPage = {
  /** The shell's place for the page (or "reports"), and its data-place. */
  key: string;
  /** The organisation hub's sections: lit on the hub while it shows this
   *  ?tab= (Overview with none). */
  hubTab?: string;
  label: string;
  /** The accessible name, where it says more than the label. */
  name?: string;
  href: string;
  icon: LucideIcon;
  subs?: SidebarSub[];
};

export type SidebarArea = {
  key: AreaKey;
  label: string;
  /** Where a tap on the area goes: its first page. */
  href: string;
  icon: LucideIcon;
  pages: SidebarPage[];
};

/** Every open lead (owner, 23 Oct 2026: "All leads one tap from anywhere"). */
export const ALL_LEADS_HREF = "/leads?tab=all&stage=open";

/**
 * Team's pages: every section of the organisation hub, from the hub's own
 * list in its order (orchestrator, 26 Oct 2026: on a computer the panel is the
 * hub's only section nav, so it lists them all, Insights and Plan & billing
 * included); the managers' sections only for those who may see the team.
 * Outside an organisation the hub is the organisation view: Overview only.
 */
/**
 * The hub's sections that change how the organisation works (routing rules,
 * chip choices and "Try a lead", connections, AI on calls, the plan): for
 * those who manage leads, not for a Viewer, who sees the team and changes
 * nothing (Roles B, 27 Oct 2026).
 */
const SETUP_TABS = new Set(["leads", "connections", "call-ai", "plan"]);

function hubPages(
  organisation: boolean,
  manager: boolean,
  manages: boolean,
): SidebarPage[] {
  return HUB_TABS.filter(
    (tab) =>
      (organisation || tab.id === "overview") &&
      (manager || !tab.managers) &&
      (manages || !SETUP_TABS.has(tab.id)),
  ).map((tab) =>
    tab.id === "overview"
      ? {
          key: "organisation",
          hubTab: "overview",
          label: tab.label,
          name: "Organisation overview",
          href: hubHref(tab),
          icon: tab.icon,
        }
      : tab.href
        ? // A section with a page of its own (Insights, Plan & billing) is
          // lit by that page's place.
          { key: tab.id, label: tab.label, href: tab.href, icon: tab.icon }
        : {
            key: `organisation-${tab.id}`,
            hubTab: tab.id,
            label: tab.label,
            href: hubHref(tab),
            icon: tab.icon,
          },
  );
}

export function sidebarAreas({
  organisation,
  team,
  manager,
  manages = manager,
}: {
  /** An organisation is the selected workspace. */
  organisation: boolean;
  /** Show the Team area: in an organisation, or on its hub. */
  team: boolean;
  /** May see the team (roles.ts "team.view"): the hub's managers' tabs. */
  manager: boolean;
  /** May change how leads work (roles.ts "leads.manage"): the setup tabs. */
  manages?: boolean;
}): SidebarArea[] {
  const areas: SidebarArea[] = [
    {
      key: "home",
      label: "Home",
      href: "/dashboard",
      icon: LayoutGrid,
      pages: [
        {
          key: "dashboard",
          label: "Home",
          href: "/dashboard",
          icon: LayoutGrid,
        },
      ],
    },
    {
      key: "work",
      label: "Work",
      href: "/leads",
      icon: Contact,
      pages: [
        {
          key: "leads",
          label: "Leads",
          href: "/leads",
          icon: Contact,
          subs: organisation
            ? [
                {
                  label: "All leads",
                  href: ALL_LEADS_HREF,
                  path: "/leads",
                  tab: "all",
                },
              ]
            : undefined,
        },
        { key: "chats", label: "Chats", href: "/chats", icon: MessagesSquare },
        {
          key: "calls",
          label: "Calls",
          href: "/analysis/calls",
          icon: AudioLines,
        },
        {
          key: "prospects",
          label: "Prospects",
          href: "/prospects",
          icon: Users,
        },
      ],
    },
  ];
  if (team)
    areas.push({
      key: "team",
      label: "Team",
      href: "/organisation",
      icon: UsersRound,
      pages: hubPages(organisation, manager, manages),
    });
  areas.push({
    key: "results",
    label: "Results",
    href: "/reports",
    icon: LineChart,
    pages: [
      { key: "reports", label: "Reports", href: "/reports", icon: LineChart },
      {
        key: "coaching",
        label: "Coaching",
        href: "/coaching",
        icon: GraduationCap,
      },
    ],
  });
  return areas;
}

/** The area a place belongs to; Account belongs to none. */
export function areaFor(
  place: string | undefined,
  reports: boolean,
): AreaKey | null {
  if (reports) return "results";
  switch (place) {
    case "dashboard":
      return "home";
    case "leads":
    case "chats":
    case "calls":
    case "prospects":
    case "analyse":
      return "work";
    case "organisation":
    case "insights":
      return "team";
    case "coaching":
    case "review":
      return "results";
    default:
      return null;
  }
}

/** Whether a page's row is lit: Reports sits on Home's place in the shell;
 *  the hub's sections light by the ?tab= the hub shows (`tab`). */
export function pageHere(
  key: string,
  place: string | undefined,
  reports: boolean,
  hub?: { section: string; tab: string | null },
): boolean {
  if (hub)
    return place === "organisation" && (hub.tab ?? "overview") === hub.section;
  if (key === "reports") return reports;
  return place === key && !reports;
}
