"use client";

/**
 * The organisation's hub (owner, 23 Oct 2026: "if organisation is clicked
 * there should be clearly visible all management options like team,
 * analytics, insights … many views like tab view"). One header and one row of
 * tabs: Overview lists every area with what it is for; Team, Analytics, Leads
 * setup, Connections, AI on calls and Company open here; Insights and Plan &
 * billing open their own pages. Owners and admins see every tab, members see
 * Overview, Team, Analytics and Company. Each tab shows the same panes that
 * Settings shows, so nothing is built twice. Outside an organisation the page
 * is the organisation view as before, with its own states.
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
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import type { ReactNode } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import { SettingsSectionView } from "../settings/sections";
import type { SettingsSectionId } from "../settings/settings-sections";
import { ActionList, ActionRow, Segmented } from "../ui/kit";
import { useWorkspaceAccess } from "../workspace-access";
import type { ServerOrganisation } from "./organisation-server";
import { OrganisationView } from "./organisation-view";
import styles from "./org-hub.module.css";

export const HUB_PATH = "/organisation";

type HubTab = {
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
    note: "Lead ads, WhatsApp and Instagram, AI replies, API keys",
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

type Part = { key: string; label: string; section: SettingsSectionId };

const LEAD_PARTS: readonly Part[] = [
  { key: "rules", label: "Lead rules", section: "lead-rules" },
  { key: "stages", label: "Stages", section: "stages" },
  { key: "sources", label: "Sources", section: "sources" },
];
const CONNECTION_PARTS: readonly Part[] = [
  { key: "apps", label: "Connected apps", section: "apps" },
  { key: "ai-replies", label: "AI replies", section: "ai-replies" },
  { key: "developers", label: "Developers", section: "developers" },
];

/** The tab row; Insights shows it too, so leaving for it keeps the place. */
export function HubTabs({
  tabs,
  current,
  base = HUB_PATH,
}: {
  tabs: readonly HubTab[];
  current: string;
  base?: string;
}) {
  return (
    <nav className={styles.tabs} aria-label="Organisation">
      {tabs.map((tab) => (
        <Link
          key={tab.id}
          href={hubHref(tab, undefined, base)}
          scroll={false}
          className={styles.tab}
          aria-current={tab.id === current ? "page" : undefined}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}

function Parts({
  tab,
  parts,
  part,
}: {
  tab: HubTab;
  parts: readonly Part[];
  part: string | null;
}) {
  const current = parts.find((item) => item.key === part) ?? parts[0];
  return (
    <div className={styles.parts}>
      <Segmented
        label={tab.label}
        value={current.key}
        items={parts.map((item) => ({ key: item.key, label: item.label }))}
        onChange={(next) => {
          // The part lives in the address, so reload and links keep it.
          const url = new URL(window.location.href);
          url.searchParams.set("part", next);
          window.history.replaceState(window.history.state, "", url);
        }}
      />
      <SettingsSectionView
        key={current.section}
        id={current.section}
        headless
      />
    </div>
  );
}

export function OrganisationHub({
  initial = null,
  base = HUB_PATH,
}: {
  initial?: ServerOrganisation | null;
  /** The page the tabs live on (a review page passes its own). */
  base?: string;
}) {
  const access = useWorkspaceAccess();
  const query = useSearchParams() as URLSearchParams | null;
  const current = access?.workspaces?.find(
    (item) => item.tenant_id === access.context?.tenantId,
  );
  // Not in an organisation (or not known yet): the page as it was.
  if (current?.kind !== "organisation")
    return <OrganisationView initial={initial} sections={["overview"]} />;

  const manager = current.role === "owner" || current.role === "admin";
  const tabs = HUB_TABS.filter((tab) => manager || !tab.managers);
  const asked = query?.get("tab") ?? "overview";
  const tab = tabs.find((item) => item.id === asked && !item.href) ?? tabs[0];
  const part = query?.get("part") ?? null;

  let body: ReactNode;
  switch (tab.id) {
    case "team":
      body = <SettingsSectionView id="team" headless />;
      break;
    case "analytics":
      body = (
        <OrganisationView
          initial={initial}
          embedded
          headless
          sections={["overview"]}
        />
      );
      break;
    case "leads":
      body = <Parts tab={tab} parts={LEAD_PARTS} part={part} />;
      break;
    case "connections":
      body = <Parts tab={tab} parts={CONNECTION_PARTS} part={part} />;
      break;
    case "call-ai":
      body = <SettingsSectionView id="call-ai" headless />;
      break;
    case "company":
      body = <SettingsSectionView id="organisation" headless />;
      break;
    default:
      body = (
        <ActionList label="Organisation">
          {tabs
            .filter((item) => item.id !== "overview")
            .map((item) => {
              const Icon = item.icon;
              return (
                <ActionRow
                  key={item.id}
                  icon={<Icon size={20} />}
                  title={item.label}
                  note={item.note}
                  href={hubHref(item, undefined, base)}
                />
              );
            })}
        </ActionList>
      );
  }

  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      homeHref="/"
      active="organisation"
      mobileFit={false}
    >
      <div className={styles.hub}>
        <header className={styles.header}>
          <span className={styles.tile} aria-hidden="true">
            <Building2 size={20} />
          </span>
          <div>
            <h1>{current.name}</h1>
            <p>
              Organisation · Your role:{" "}
              <b>
                {current.role === "owner"
                  ? "Owner"
                  : manager
                    ? "Admin"
                    : "Member"}
              </b>
            </p>
          </div>
        </header>
        <HubTabs tabs={tabs} current={tab.id} base={base} />
        <div className={styles.body}>{body}</div>
      </div>
    </AcquisitionShell>
  );
}

/** Where the hub lists an area in words (You, Home, search). */
export function hubLink(id: string): string {
  const tab = HUB_TABS.find((item) => item.id === id);
  return tab ? hubHref(tab) : HUB_PATH;
}
