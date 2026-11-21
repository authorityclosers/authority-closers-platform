import { redirect } from "next/navigation";

import { serverReads, serverReadsBuilt } from "../server-reads";
import { hubQueryTarget } from "../settings/settings-sections";
import { OrganisationHub } from "./org-hub";
import { serverOrganisation } from "./organisation-server";

/**
 * The organisation's hub (owner, 23 Oct 2026): Overview, Team, Analytics,
 * Insights, Leads setup, Connections, AI on calls, Company and Plan & billing
 * as tabs (org-hub.tsx). Where this server can read the API (dev), the
 * analytics' first reads are made here and the tab arrives whole; elsewhere
 * the browser reads them.
 */
export default async function OrganisationPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  // An organisation's /organisation (any tab but Analytics) is a Settings
  // address: the server sends it there at once, with one read of who you are
  // here, instead of the page waiting 4-8 s for the workspace in the browser
  // (sx-redesign, 21 Nov 2026). A personal workspace (404), a guest, an
  // in-app navigation or a server without reads keeps the browser's check.
  if (serverReadsBuilt()) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(await searchParams))
      for (const one of [value ?? []].flat()) query.append(key, one);
    const target = hubQueryTarget(query);
    if (target) {
      const reads = await serverReads(["/v1/organisation"]);
      if (reads?.["/v1/organisation"]?.status === 200) redirect(target);
    }
  }
  return <OrganisationHub initial={await serverOrganisation()} />;
}
