"use client";

import type { ReactNode } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import { useWorkspaceAccess } from "../workspace-access";
import { SettingsShell } from "./settings-shell";

/** Settings sit in the app frame, with the account entry lit. */
export default function SettingsLayout({ children }: { children: ReactNode }) {
  const access = useWorkspaceAccess();
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      homeHref="/"
      active="account"
      mobileFit={false}
    >
      <SettingsShell>{children}</SettingsShell>
    </AcquisitionShell>
  );
}
