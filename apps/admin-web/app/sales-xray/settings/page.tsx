import { ProviderControls } from "../provider-controls";
import { MinuteAccountAdminPanel } from "../minute-account-admin";

export const dynamic = "force-dynamic";

export default function SalesXraySettingsPage() {
  return (
    <ProviderControls>
      <MinuteAccountAdminPanel />
    </ProviderControls>
  );
}
