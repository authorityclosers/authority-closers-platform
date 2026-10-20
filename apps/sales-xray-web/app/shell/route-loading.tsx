"use client";

/**
 * What the app shows while the next screen is on its way (owner, 20 Oct:
 * "anything we switch any page screen etc this wave comes up and its ugly").
 *
 * Next.js wraps every top-level page in the root loading screen, so opening
 * Leads, Calls or Settings used to draw New analysis (its wave and drop
 * area) until the page arrived. The root loading screen now draws the
 * outline of the screen being opened, in the same frame, so the only change
 * on arrival is the content filling in. Pages outside the app frame (sign
 * in, policies) get a quiet blank page instead of the app's frame.
 *
 * Only light skeleton modules are imported here: this screen is part of
 * every page's code. A page whose outline lives inside its own big module
 * (Insights, Invites, Review) gets the shared outline in its place in the
 * frame.
 */
import { usePathname } from "next/navigation";

import AccountLoading from "../account/loading";
import { AcquisitionShell } from "../acquisition-shell";
import { callIdFromPath } from "../analysis-routes";
import { NewAnalysisSkeleton } from "../analysis/new/new-analysis-skeleton";
import { isShellRoute } from "../app-session";
import CallLoading from "../analysis/calls/[callId]/loading";
import CallsLoading from "../calls/loading";
import { ChatsSkeleton } from "../chats/chats-skeleton";
import CoachingLoading from "../coaching/loading";
import DashboardLoading from "../dashboard/loading";
import { LeadsSkeleton } from "../leads/leads-skeleton";
import OrganisationLoading from "../organisation/loading";
import PersonLoading from "../organisation/people/[personId]/loading";
import ProspectDetailLoading from "../prospects/[prospectId]/loading";
import ProspectsLoading from "../prospects/loading";
import { SettingsSkeleton } from "../settings/settings-skeleton";
import { useWorkspaceAccess } from "../workspace-access";
import { PageSkeleton, type SkeletonVariant } from "./page-skeleton";

export type RouteLoadingKind =
  | "plain"
  | "new"
  | "call"
  | "dashboard"
  | "leads"
  | "chats"
  | "calls"
  | "prospect"
  | "prospects"
  | "coaching"
  | "insights"
  | "invites"
  | "person"
  | "organisation"
  | "settings"
  | "account"
  | "review"
  | "page";

const under = (route: string, root: string) =>
  route === root || route.startsWith(`${root}/`);

/** Which outline an address loads with (trailing slash ignored). */
export function routeLoadingKind(pathname: string | null): RouteLoadingKind {
  const route = (pathname ?? "/").replace(/\/$/, "") || "/";
  if (under(route, "/review")) return "review";
  if (!isShellRoute(route)) return "plain";
  if (route === "/" || under(route, "/analysis/new")) return "new";
  if (callIdFromPath(route) !== null) return "call";
  if (under(route, "/dashboard")) return "dashboard";
  if (under(route, "/leads")) return "leads";
  if (under(route, "/chats")) return "chats";
  if (under(route, "/analysis") || under(route, "/calls")) return "calls";
  if (/^\/prospects\/[^/]+$/.test(route)) return "prospect";
  if (under(route, "/prospects")) return "prospects";
  if (under(route, "/coaching")) return "coaching";
  if (under(route, "/organisation/insights")) return "insights";
  if (under(route, "/organisation/invites")) return "invites";
  if (under(route, "/organisation/people")) return "person";
  if (under(route, "/organisation")) return "organisation";
  if (under(route, "/settings")) return "settings";
  if (under(route, "/account")) return "account";
  return "page";
}

/** Settings while its section loads: the frame, side list and panels. */
function SettingsLoading() {
  const access = useWorkspaceAccess();
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      loading={!access}
      homeHref="/"
      active="account"
      mobileFit={false}
    >
      <SettingsSkeleton />
    </AcquisitionShell>
  );
}

/** The shared outline, in the frame with the right place lit. */
function OutlineLoading({
  active,
  variant = "list",
}: {
  active?: "insights" | "organisation" | "review";
  variant?: SkeletonVariant;
}) {
  const access = useWorkspaceAccess();
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      loading={!access}
      active={active}
    >
      <PageSkeleton variant={variant} />
    </AcquisitionShell>
  );
}

/**
 * The outline for the address being loaded, or for `pathname` when the
 * frame shows it before the router has moved (screen-transition.ts).
 */
export function RouteLoading({ pathname }: { pathname?: string }) {
  const current = usePathname();
  switch (routeLoadingKind(pathname ?? current)) {
    case "new":
      return <NewAnalysisSkeleton />;
    case "call":
      return <CallLoading />;
    case "dashboard":
      return <DashboardLoading />;
    case "leads":
      return <LeadsSkeleton />;
    case "chats":
      return <ChatsSkeleton />;
    case "calls":
      return <CallsLoading />;
    case "prospect":
      return <ProspectDetailLoading />;
    case "prospects":
      return <ProspectsLoading />;
    case "coaching":
      return <CoachingLoading />;
    case "insights":
      return <OutlineLoading active="insights" variant="dashboard" />;
    case "invites":
      return <OutlineLoading active="organisation" />;
    case "person":
      return <PersonLoading />;
    case "organisation":
      return <OrganisationLoading />;
    case "settings":
      return <SettingsLoading />;
    case "account":
      return <AccountLoading />;
    case "review":
      return <OutlineLoading active="review" />;
    case "page":
      return <OutlineLoading />;
    case "plain":
      // Sign in, policies, plans: their own pages, never the app's frame.
      return (
        <div
          role="status"
          aria-busy="true"
          aria-label="Loading"
          style={{ minHeight: "100dvh" }}
        />
      );
  }
}
