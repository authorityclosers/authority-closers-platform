import type { ReactNode } from "react";

import {
  consoleEnvironment,
  loadConsoleAccess,
} from "@/app/lib/console-access";
import { ConsoleShell } from "@/app/ui/shell";

/** Every console page shares one frame; who is signed in is read once, on the server. */
export default async function ConsoleLayout({
  children,
}: {
  children: ReactNode;
}) {
  const access = await loadConsoleAccess();
  return (
    <ConsoleShell access={access} environment={consoleEnvironment()}>
      {children}
    </ConsoleShell>
  );
}
