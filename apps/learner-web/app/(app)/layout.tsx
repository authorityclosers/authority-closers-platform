import type { ReactNode } from "react";
import { AppUpdatesProvider } from "../components/app-updates-provider";
import { ReflexShell } from "../shell/reflex-shell";
import { isPracticeUiEnabled } from "../lib/practice-availability";
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <ReflexShell practiceEnabled={isPracticeUiEnabled(process.env)}>
      <AppUpdatesProvider>{children}</AppUpdatesProvider>
    </ReflexShell>
  );
}
