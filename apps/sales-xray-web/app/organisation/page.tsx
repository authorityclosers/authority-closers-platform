import { OrganisationView } from "./organisation-view";
import { serverOrganisation } from "./organisation-server";

/**
 * The organisation's overview: its calls, people and what keeps coming up.
 * Its settings (company details, team and roles, connections) live in
 * Settings (owner, 20 Oct). Where this server can read the API (dev), its
 * first reads are made here and the page arrives whole; elsewhere the
 * browser reads them.
 */
export default async function OrganisationPage() {
  return (
    <OrganisationView
      initial={await serverOrganisation()}
      sections={["overview"]}
    />
  );
}
