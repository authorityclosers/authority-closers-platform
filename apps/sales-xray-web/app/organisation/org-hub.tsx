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

import { roleLabel } from "./roles";
import { Building2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState, type ReactNode } from "react";

import { useBranding } from "../shell/branding-store";
import { OrgLogo } from "../shell/org-logo";
import { AcquisitionShell } from "../acquisition-shell";
import { SettingsSectionView } from "../settings/sections";
import type { SettingsSectionId } from "../settings/settings-sections";
import { ActionList, ActionRow, Segmented } from "../ui/kit";
import { SideScroll, sideScrollFades, useSideScroll } from "../ui/side-scroll";
import { useWorkspaceAccess } from "../workspace-access";
import type { ServerOrganisation } from "./organisation-seed";
import { AnalyticsView } from "./analytics-view";
import { can } from "./roles";
import { OrganisationView } from "./organisation-view";
import { HUB_PATH, HUB_TABS, hubHref, type HubTab } from "./hub-tabs";
import { hubTabsFor } from "./setup-tabs";
import styles from "./org-hub.module.css";
import { OrganisationSources } from "./setup/sources";
import { OrganisationStages } from "./setup/stages";
import { OrganisationRules } from "./setup/rules";

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
  { key: "pulse", label: "Pulse", section: "pulse" },
];

/**
 * The tab row; Insights shows it too, so leaving for it keeps the place. On a
 * phone it scrolls, with the open tab in view (owner bug #43, 27 Oct 2026).
 */
export function HubTabs({
  tabs,
  current,
  base = HUB_PATH,
}: {
  tabs: readonly HubTab[];
  current: string;
  base?: string;
}) {
  const { ref, edges } = useSideScroll<HTMLElement>(
    '[aria-current="page"]',
    current,
  );
  return (
    <nav
      ref={ref}
      className={`${styles.tabs} ${sideScrollFades}`}
      aria-label="Organisation"
      {...edges}
    >
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
  // A tap shows its part at once. The address alone can't: here a bare
  // history.replaceState doesn't refresh useSearchParams, so Stages and Sources
  // stayed on Lead rules (owner, 25 Oct 2026). The tap holds until the address's
  // own part changes (a link, another tab).
  const [chosen, setChosen] = useState<{
    from: string | null;
    key: string;
  } | null>(null);
  const shown = chosen && chosen.from === part ? chosen.key : part;
  const current = parts.find((item) => item.key === shown) ?? parts[0];
  return (
    <div className={styles.parts}>
      {/* Its own scroller: a bare segmented control widened the page. */}
      <SideScroll chosen={current.key}>
        <Segmented
          label={tab.label}
          value={current.key}
          items={parts.map((item) => ({ key: item.key, label: item.label }))}
          onChange={(next) => {
            setChosen({ from: part, key: next });
            // The part lives in the address too, so reload and links keep it.
            const url = new URL(window.location.href);
            url.searchParams.set("part", next);
            window.history.replaceState(window.history.state, "", url);
          }}
        />
      </SideScroll>
      {current.section === "sources" ? (
        <OrganisationSources key="sources" />
      ) : current.section === "stages" ? (
        <OrganisationStages key="stages" />
      ) : current.section === "lead-rules" ? (
        <OrganisationRules key="rules" />
      ) : (
        <SettingsSectionView
          key={current.section}
          id={current.section}
          headless
        />
      )}
    </div>
  );
}

type HubWorkspace = { name: string; role: string | null };

/** The organisation's name and your role, at the top of the hub and of Insights. */
function OrgHeader({ workspace }: { workspace: HubWorkspace }) {
  // Its own logo where it has one, as the workspace switcher shows it
  // (owner, 26 Oct 2026); the building icon only without one.
  const logo = useBranding()?.logoUrl ?? null;
  return (
    <header className={styles.header}>
      <span className={styles.tile} aria-hidden="true">
        <OrgLogo src={logo} fallback={<Building2 size={20} />} />
      </span>
      <div>
        <h1>{workspace.name}</h1>
        <p>
          Organisation · Your role: <b>{roleLabel(workspace.role)}</b>
        </p>
      </div>
    </header>
  );
}

/**
 * The hub's header and tab row around a page of its own (Insights), so the
 * organisation keeps one shell (owner, 25 Oct 2026). Outside an organisation
 * the page shows on its own.
 */
export function OrgHubFrame({
  current,
  children,
}: {
  current: string;
  children: ReactNode;
}) {
  const access = useWorkspaceAccess();
  const workspace = access?.workspaces?.find(
    (item) => item.tenant_id === access.context?.tenantId,
  );
  if (workspace?.kind !== "organisation") return <>{children}</>;
  // A Viewer gets the team's tabs but none of the setup (Roles B).
  const tabs = hubTabsFor(workspace.role);
  return (
    <div className={styles.hub}>
      <OrgHeader workspace={workspace} />
      <HubTabs tabs={tabs} current={current} />
      <div className={styles.body}>{children}</div>
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

  const tabs = hubTabsFor(current.role);
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
        <AnalyticsView
          key={current.tenant_id}
          team={can(current.role, "team.view")}
          personId={access?.context?.personId}
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
        <OrgHeader workspace={current} />
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
