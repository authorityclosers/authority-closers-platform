import type { ReactNode } from "react";

import {
  consoleEnvironment,
  loadConsoleAccess,
  loadConsoleWorkspaces,
} from "@/app/lib/console-access";
import { ConsoleShell } from "@/app/ui/shell";

/** Every console page shares one frame; who is signed in is read once, on the server. */
export default async function ConsoleLayout({
  children,
}: {
  children: ReactNode;
}) {
  const access = await loadConsoleAccess();
  const workspaces = await loadConsoleWorkspaces(access);
  return (
    <ConsoleShell
      access={access}
      environment={consoleEnvironment()}
      workspaces={workspaces}
    >
      {children}
    </ConsoleShell>
  );
}
