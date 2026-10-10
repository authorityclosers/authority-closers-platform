"use client";

import { AcquisitionShell } from "../acquisition-shell";
import { useWorkspaceAccess } from "../workspace-access";
import { OrganisationPageSkeleton } from "./organisation-skeleton";

export default function OrganisationLoading() {
  const access = useWorkspaceAccess();
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      loading={!access}
      homeHref="/"
      active="organisation"
      mobileFit={false}
    >
      <OrganisationPageSkeleton />
    </AcquisitionShell>
  );
}
