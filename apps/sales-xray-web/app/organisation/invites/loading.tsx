"use client";

import { AcquisitionShell } from "../../acquisition-shell";
import { useWorkspaceAccess } from "../../workspace-access";
import { InvitesSkeleton } from "./invites-skeleton";

export default function InvitesLoading() {
  const access = useWorkspaceAccess();
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      loading={!access}
      homeHref="/"
      active="organisation"
      mobileFit={false}
    >
      <InvitesSkeleton />
    </AcquisitionShell>
  );
}
