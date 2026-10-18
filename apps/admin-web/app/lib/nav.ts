/**
 * The console's navigation and who sees each item. Visibility is a hint
 * only: every page's API read and every command is re-checked by the API
 * (operations tenant, admin_surface, platform_* grants, Sales Xray control
 * accounts). Nothing here grants access.
 */

export type ConsoleAccess = Readonly<{
  /** verified: read from the API; preview: local preview with no session. */
  state: "verified" | "preview" | "unavailable";
  email: string | null;
  displayName: string | null;
  role: string | null;
  permissions: readonly string[];
  platform: readonly string[];
}>;

/** Mirrors canManageSalesXray in @ac/operations-web and CONTROL_ACCOUNTS in provider_admin.py. */
const SALES_XRAY_CONTROL_ACCOUNTS = new Set([
  "admin@authorityclosers.com",
  "dipak@authorityclosers.com",
  "suyash@authorityclosers.com",
]);

export function isSalesXrayControl(access: ConsoleAccess): boolean {
  return (
    access.state === "verified" &&
    SALES_XRAY_CONTROL_ACCOUNTS.has(
      (access.email ?? "").trim().toLowerCase(),
    ) &&
    ["owner", "admin"].includes(access.role ?? "") &&
    access.permissions.includes("admin_surface")
  );
}

export type NavIcon =
  | "home"
  | "calls"
  | "gold"
  | "reviewers"
  | "health"
  | "usage"
  | "company"
  | "outcomes"
  | "providers"
  | "analysis"
  | "execution"
  | "minutes"
  | "synthetic"
  | "people"
  | "organisations"
  | "billing"
  | "academies"
  | "learning"
  | "studio"
  | "releases"
  | "updates"
  | "safety";

type Need =
  | { kind: "console" }
  | { kind: "salesXray" }
  | { kind: "permission"; any: readonly string[] }
  | { kind: "platform"; any: readonly string[] }
  | { kind: "salesXrayAndPlatform"; any: readonly string[] };

export type NavItem = Readonly<{
  href: string;
  label: string;
  icon: NavIcon;
  need: Need;
  /** Shown in the phone bottom bar. */
  phone?: boolean;
  /** Listed once its screen is built (AUT-1798 builds them in order). */
  soon?: boolean;
  /** Other paths whose pages belong to this item (its subpages elsewhere). */
  also?: readonly string[];
}>;

export type NavGroup = Readonly<{ label: string; items: readonly NavItem[] }>;

export const NAVIGATION: readonly NavGroup[] = [
  {
    label: "",
    items: [
      {
        href: "/",
        label: "Home",
        icon: "home",
        need: { kind: "console" },
        phone: true,
      },
    ],
  },
  {
    label: "Review",
    items: [
      {
        href: "/calls",
        label: "Calls",
        icon: "calls",
        need: { kind: "salesXray" },
        phone: true,
      },
      {
        href: "/gold",
        label: "Gold set",
        icon: "gold",
        need: { kind: "salesXray" },
        phone: true,
      },
      {
        href: "/reviewers",
        label: "Reviewers",
        icon: "reviewers",
        also: ["/sales-xray/review"],
        need: { kind: "salesXray" },
      },
    ],
  },
  {
    label: "Insights",
    items: [
      {
        href: "/company",
        label: "Company",
        icon: "company",
        need: { kind: "salesXray" },
        phone: true,
      },
      {
        href: "/health",
        label: "Analysis health",
        icon: "health",
        need: { kind: "salesXray" },
        phone: true,
      },
      {
        href: "/usage",
        label: "Usage & cost",
        icon: "usage",
        need: { kind: "salesXray" },
      },
      {
        href: "/outcomes",
        label: "Deal outcomes",
        icon: "outcomes",
        need: { kind: "salesXray" },
      },
    ],
  },
  {
    label: "Sales Xray setup",
    items: [
      {
        href: "/sales-xray/providers",
        label: "Providers & costs",
        icon: "providers",
        need: { kind: "salesXray" },
      },
      {
        href: "/sales-xray/analysis",
        label: "Analysis settings",
        icon: "analysis",
        need: { kind: "salesXray" },
      },
      {
        href: "/sales-xray/execution",
        label: "Execution & budget",
        icon: "execution",
        need: { kind: "salesXray" },
      },
      {
        href: "/sales-xray/minutes",
        label: "Minutes",
        icon: "minutes",
        need: { kind: "salesXrayAndPlatform", any: ["platform_access_manage"] },
      },
      {
        href: "/synthetic",
        label: "Synthetic data",
        icon: "synthetic",
        need: { kind: "salesXray" },
      },
    ],
  },
  {
    label: "Accounts",
    items: [
      {
        href: "/people",
        label: "People",
        icon: "people",
        need: { kind: "permission", any: ["learner_diagnose"] },
      },
      {
        href: "/platform/organisations",
        label: "Organisations",
        icon: "organisations",
        need: { kind: "platform", any: ["platform_tenants_read"] },
      },
      {
        // /platform is the only path platform-only operators are admitted to (proxy.ts).
        href: "/platform?tab=billing",
        label: "Billing",
        icon: "billing",
        need: { kind: "platform", any: ["platform_billing_manage"] },
      },
      {
        href: "/platform",
        label: "Academies",
        icon: "academies",
        need: { kind: "platform", any: ["platform_tenants_read"] },
      },
    ],
  },
  {
    label: "Platform",
    items: [
      {
        href: "/releases",
        label: "Releases & status",
        icon: "releases",
        need: { kind: "platform", any: ["platform_release_manage"] },
      },
      {
        href: "/updates",
        label: "Product updates",
        icon: "updates",
        need: { kind: "salesXray" },
      },
      {
        href: "/safety",
        label: "Safety",
        icon: "safety",
        need: { kind: "platform", any: ["platform_content_safety_manage"] },
      },
      {
        href: "/learning-operations",
        label: "Learning operations",
        icon: "learning",
        need: { kind: "permission", any: ["job_retry", "recovery_reconcile"] },
      },
      {
        href: "/studio",
        label: "Academy Studio",
        icon: "studio",
        need: {
          kind: "permission",
          any: ["catalog_read", "catalog_write", "catalog_publish"],
        },
      },
    ],
  },
];

export function canSee(item: NavItem, access: ConsoleAccess): boolean {
  if (access.state === "preview") return true;
  if (access.state !== "verified") return item.need.kind === "console";
  const need = item.need;
  switch (need.kind) {
    case "console":
      return (
        access.permissions.includes("admin_surface") ||
        access.platform.length > 0
      );
    case "salesXray":
      return isSalesXrayControl(access);
    case "permission":
      return (
        access.permissions.includes("admin_surface") &&
        need.any.some((p) => access.permissions.includes(p))
      );
    case "platform":
      return need.any.some((p) => access.platform.includes(p));
    case "salesXrayAndPlatform":
      return (
        isSalesXrayControl(access) &&
        need.any.some((p) => access.platform.includes(p))
      );
  }
}

export function visibleNavigation(access: ConsoleAccess): NavGroup[] {
  return NAVIGATION.map((group) => ({
    label: group.label,
    items: group.items.filter((item) => !item.soon && canSee(item, access)),
  })).filter((group) => group.items.length > 0);
}

/** True when `href` (path plus optional query) describes the current location. */
function matches(
  href: string,
  pathname: string,
  search: URLSearchParams,
): boolean {
  const [path = "/", query = ""] = href.split("?");
  if (query) {
    if (pathname !== path) return false;
    for (const [key, value] of new URLSearchParams(query))
      if (search.get(key) !== value) return false;
    return true;
  }
  return path === "/"
    ? pathname === "/"
    : pathname === path || pathname.startsWith(`${path}/`);
}

/** The item a location belongs to: the most specific matching href wins. */
export function activeHref(
  pathname: string,
  groups: readonly NavGroup[],
  search: string = "",
): string | null {
  const params = new URLSearchParams(search);
  let best: string | null = null;
  let bestLength = 0;
  for (const group of groups)
    for (const item of group.items)
      for (const href of [item.href, ...(item.also ?? [])])
        if (matches(href, pathname, params) && href.length > bestLength) {
          best = item.href;
          bestLength = href.length;
        }
  return best;
}
