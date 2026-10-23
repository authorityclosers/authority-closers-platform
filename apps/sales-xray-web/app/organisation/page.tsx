import { OrganisationHub } from "./org-hub";
import { serverOrganisation } from "./organisation-server";

/**
 * The organisation's hub (owner, 23 Oct 2026): Overview, Team, Analytics,
 * Insights, Leads setup, Connections, AI on calls, Company and Plan & billing
 * as tabs (org-hub.tsx). Where this server can read the API (dev), the
 * analytics' first reads are made here and the tab arrives whole; elsewhere
 * the browser reads them.
 */
export default async function OrganisationPage() {
  return <OrganisationHub initial={await serverOrganisation()} />;
}
