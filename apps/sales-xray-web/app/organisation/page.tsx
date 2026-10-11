import { OrganisationView } from "./organisation-view";
import { serverOrganisation } from "./organisation-server";

/**
 * The organisation: company, members, teams, usage and shared credits. Where
 * this server can read the API (dev), its first reads are made here and the
 * page arrives whole; elsewhere the browser reads them.
 */
export default async function OrganisationPage() {
  return <OrganisationView initial={await serverOrganisation()} />;
}
