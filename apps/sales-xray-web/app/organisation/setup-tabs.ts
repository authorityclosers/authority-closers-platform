import { can } from "./roles";
import { HUB_TABS, type HubTab } from "./hub-tabs";

/**
 * The organisation hub's sections that change how it works: lead setup
 * (routing rules, the chip choices and "Try a lead"), connections, AI on
 * calls and the plan. They need roles.ts "leads.manage"; a Viewer sees the
 * team and changes nothing (Roles B, 27 Oct 2026).
 */
export const SETUP_TABS: ReadonlySet<string> = new Set([
  "leads",
  "connections",
  "call-ai",
  "plan",
]);

/**
 * The hub's tabs a role sees: the managers' ones with team.view, setup with
 * leads.manage too, and Plan & billing only for those who see billing.
 */
export function hubTabsFor(role: string | null | undefined): HubTab[] {
  const manager = can(role, "team.view");
  const manages = can(role, "leads.manage");
  const billing = can(role, "billing.view");
  return HUB_TABS.filter(
    (tab) =>
      (manager || !tab.managers) &&
      (manages || !SETUP_TABS.has(tab.id)) &&
      (billing || tab.id !== "plan"),
  );
}
