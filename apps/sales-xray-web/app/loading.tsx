"use client";

import { AcquisitionShell } from "./acquisition-shell";
import { PageSkeleton } from "./shell/page-skeleton";
import { useWorkspaceAccess } from "./workspace-access";

/** Shown by Next.js while the root (studio) page suspends. */
export default function Loading() {
  const access = useWorkspaceAccess();
  const authenticated = access?.authenticated === true;
  return (
    <AcquisitionShell authenticated={authenticated} active="analyse">
      <PageSkeleton variant="studio" />
    </AcquisitionShell>
  );
}
