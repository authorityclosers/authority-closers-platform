"use client";

import { AcquisitionShell } from "../acquisition-shell";
import { useWorkspaceAccess } from "../workspace-access";
import { CoachingSkeleton } from "./coaching-skeleton";

/** The frame stays put while the server read streams in: no layout shift. */
export default function Loading() {
  const access = useWorkspaceAccess();
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      loading={!access}
    >
      <CoachingSkeleton />
    </AcquisitionShell>
  );
}
