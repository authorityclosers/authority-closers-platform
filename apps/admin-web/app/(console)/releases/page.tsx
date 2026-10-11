import { Rocket } from "lucide-react";

import { Empty, List, Page, PageHeader, Panel, Row } from "@/app/ui/kit";

/**
 * Releases & status. Admin release controls (ADR 0034: the engine's request
 * inbox and the Admin release routes) are not built yet, so this page shows
 * how releases move today rather than invented status.
 */
export default function ReleasesPage() {
  return (
    <Page>
      <PageHeader
        title="Releases & status"
        context={["What runs where, and how a change reaches production"]}
      />
      <Panel title="How releases move today">
        <List label="Release path">
          <Row
            title="Merge to main"
            meta={[
              "The train merges green strike pull requests about every two hours",
            ]}
          />
          <Row
            title="Staging"
            meta={[
              "Deploys main automatically; admin-staging.authorityclosers.com",
            ]}
          />
          <Row
            title="Development"
            meta={["Picks up main within ten minutes"]}
          />
          <Row
            title="Production"
            meta={["The same build, promoted on the owner's “ship it”"]}
          />
        </List>
      </Panel>
      <Panel title="Release controls">
        <Empty
          icon={Rocket}
          title="Not connected yet"
          text="Promoting and checking releases from Admin needs the release engine's request inbox and the Admin release routes (ADR 0034), which aren't built. Until then the owner promotes production through the release engine."
        />
      </Panel>
    </Page>
  );
}
