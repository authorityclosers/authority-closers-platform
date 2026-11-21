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
 *
 * Round-2 board 7 (20 Nov 2026): the organisation's settings moved into one
 * Settings, each with its scope. The hub keeps Analytics (until board 6's
 * Team today); every other tab's address, old links and connect flows coming
 * back with ?connected=… included, goes to its Settings section with its own
 * query kept.
 */

import { roleLabel } from "./roles";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useBranding } from "../shell/branding-store";
import { WorkspaceTile } from "../shell/workspace-picker";
import { AcquisitionShell } from "../acquisition-shell";
import { hubTarget } from "../settings/hub-redirect";
import { SettingsSectionView } from "../settings/sections";
import {
  hubTabSetting,
  isSettingsSection,
} from "../settings/settings-sections";
import { SettingsOverview } from "../settings/settings-shell";
import { sideScrollFades, useSideScroll } from "../ui/side-scroll";
import { useWorkspaceAccess } from "../workspace-access";
import type { ServerOrganisation } from "./organisation-seed";
import { AnalyticsView } from "./analytics-view";
import { can } from "./roles";
import { OrganisationView } from "./organisation-view";
import { OrganisationSkeleton } from "./organisation-skeleton";
import { HUB_PATH, HUB_TABS, hubHref, type HubTab } from "./hub-tabs";
import { hubTabsFor } from "./setup-tabs";
import styles from "./org-hub.module.css";

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

type HubWorkspace = {
  tenant_id: string;
  name: string;
  role: string | null;
  logo_url?: string | null;
};

/** The organisation's name and your role, at the top of the hub and of Insights. */
function OrgHeader({ workspace }: { workspace: HubWorkspace }) {
  // Its own logo where it has one, else its initials on its own colour, the
  // same tile as the workspace switcher and the top bar (owner bug #50).
  const logo = useBranding()?.logoUrl ?? null;
  return (
    <header className={styles.header}>
      <WorkspaceTile
        workspace={{
          tenant_id: workspace.tenant_id,
          kind: "organisation",
          name: workspace.name,
          logo_url: workspace.logo_url,
        }}
        logoUrl={logo}
        size="xl"
      />
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
  const router = useRouter();
  const query = useSearchParams() as URLSearchParams | null;
  const current = access?.workspaces?.find(
    (item) => item.tenant_id === access.context?.tenantId,
  );
  const inOrganisation = current?.kind === "organisation";
  // Every tab but Analytics is a Settings section now (round-2 board 7).
  const moved = inOrganisation
    ? hubTabSetting(query?.get("tab") ?? null, query?.get("part") ?? null)
    : null;
  // A review page (its own base) shows the section where it is, for its pictures.
  const real = base === HUB_PATH;
  useEffect(() => {
    if (moved && real)
      router.replace(
        hubTarget(moved, window.location.search, window.location.hash),
      );
  }, [moved, real, router]);
  // Its Settings page loads while the workspace is still being checked, so
  // the move is instant once it is (sx-redesign, 21 Nov 2026).
  const early = real
    ? hubTabSetting(query?.get("tab") ?? null, query?.get("part") ?? null)
    : null;
  useEffect(() => {
    if (early) router.prefetch(early);
  }, [early, router]);
  // Not in an organisation (or not known yet): the page as it was.
  if (!inOrganisation)
    return <OrganisationView initial={initial} sections={["overview"]} />;
  if (moved && real) return <OrganisationSkeleton />;

  const tabs = hubTabsFor(current.role);
  const section = moved?.split("/")[2] ?? null;
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      homeHref="/"
      active="organisation"
      mobileFit={false}
    >
      <div className={styles.hub}>
        <OrgHeader workspace={current} />
        <HubTabs
          tabs={tabs}
          current={moved ? (query?.get("tab") ?? "overview") : "analytics"}
          base={base}
        />
        <div className={styles.body}>
          {!moved ? (
            <AnalyticsView
              key={current.tenant_id}
              team={can(current.role, "team.view")}
              personId={access?.context?.personId}
            />
          ) : isSettingsSection(section) ? (
            <SettingsSectionView id={section} headless />
          ) : (
            <SettingsOverview />
          )}
        </div>
      </div>
    </AcquisitionShell>
  );
}

/** Where the hub lists an area in words (You, Home, search). */
export function hubLink(id: string): string {
  const tab = HUB_TABS.find((item) => item.id === id);
  return tab ? hubHref(tab) : HUB_PATH;
}
