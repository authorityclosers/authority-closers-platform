"use client";

import { ProspectsListView } from "../../../prospects/prospects-list-view";
import { WorkspaceAccessContext } from "../../../workspace-access";

const context = {
  personId: "00000000-0000-0000-0000-000000000001",
  tenantId: "00000000-0000-0000-0000-000000000002",
  sessionId: "00000000-0000-0000-0000-000000000003",
};

/** Only the bounded browser proof supplies invented rows at the API port. */
export function ProspectLibraryFixture() {
  return (
    <WorkspaceAccessContext.Provider
      value={{ status: "ready", authenticated: true, context, retry: () => {} }}
    >
      <ProspectsListView />
    </WorkspaceAccessContext.Provider>
  );
}
