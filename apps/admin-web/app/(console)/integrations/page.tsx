import { normalizeIntegrations } from "@/app/integrations/integrations-data";
import { IntegrationsView } from "@/app/integrations/integrations-view";
import { StaffKeys } from "@/app/integrations/staff-keys";
import { normalizeStaffKeys } from "@/app/integrations/staff-keys-data";
import { adminRead } from "@/app/lib/server-api";
import { Page, PageHeader, Panel, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

export default async function IntegrationsPage() {
  const [result, keys] = await Promise.all([
    adminRead("/v1/admin/integrations", normalizeIntegrations),
    adminRead("/v1/admin/staff-keys", normalizeStaffKeys),
  ]);
  return (
    <Page>
      <PageHeader
        title="Integrations"
        context={[
          "API keys, webhooks and connected apps across every organisation. Organisations set these up themselves in Sales Xray (Settings → Integrations); here you can see them and stop one at once.",
        ]}
      />
      {keys.ok ? (
        <Panel title="Your staff keys" sub="Admin command line and MCP">
          <StaffKeys data={keys.data} />
        </Panel>
      ) : null}
      {result.ok ? (
        <IntegrationsView data={result.data} />
      ) : (
        <Unavailable title="Integrations" reason={result.error} />
      )}
    </Page>
  );
}
