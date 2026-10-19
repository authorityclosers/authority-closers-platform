import { normalizeIntegrations } from "@/app/integrations/integrations-data";
import { IntegrationsView } from "@/app/integrations/integrations-view";
import { adminRead } from "@/app/lib/server-api";
import { Page, PageHeader, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

export default async function IntegrationsPage() {
  const result = await adminRead(
    "/v1/admin/integrations",
    normalizeIntegrations,
  );
  return (
    <Page>
      <PageHeader
        title="Integrations"
        context={[
          "API keys, webhooks and connected apps across every organisation. Organisations set these up themselves in Sales Xray (Settings → Integrations); here you can see them and stop one at once.",
        ]}
      />
      {result.ok ? (
        <IntegrationsView data={result.data} />
      ) : (
        <Unavailable title="Integrations" reason={result.error} />
      )}
    </Page>
  );
}
