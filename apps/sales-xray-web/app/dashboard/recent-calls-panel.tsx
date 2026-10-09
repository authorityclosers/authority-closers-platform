"use client";
import { useState } from "react";
import { FolderOpen, Plus } from "lucide-react";
import Link from "next/link";
import { OperationalPanel, OperationalEmpty } from "../ui/operational-panel";
import { RecentCallsList, RecentCallsSkeleton } from "./recent-calls";
import type { DashboardSnapshot } from "../session-data";
import styles from "./dashboard.module.css";
export function RecentCallsPanel({
  recentState,
  isAccountEmpty,
}: {
  recentState: DashboardSnapshot["recent"];
  isAccountEmpty: boolean;
}) {
  const [hiddenRecent, setHiddenRecent] = useState(0);
  const recent = recentState.status === "ready" ? recentState.value : null;
  return (
    <OperationalPanel
      id="panel-recent-calls"
      title="Recent calls"
      sub="Latest processed audio recordings and evaluations"
      action={
        recent && recent.length > 0
          ? {
              href: "/analysis/calls",
              label: "View all calls",
              badge: hiddenRecent > 0 ? `+${hiddenRecent}` : undefined,
            }
          : undefined
      }
      className={styles.tableCard}
    >
      {recentState.status === "loading" ? (
        <RecentCallsSkeleton />
      ) : recentState.status === "error" ? (
        <RecentCallsSkeleton />
      ) : recent === null || recent.length === 0 ? (
        <OperationalEmpty
          icon={FolderOpen}
          title={isAccountEmpty ? "Analyse your first call" : "No calls yet"}
          description={
            isAccountEmpty
              ? "Upload a sales call to start your analysis."
              : "No calls yet"
          }
          action={
            <Link href="/analysis/new" className={styles.primaryAction}>
              <Plus size={16} aria-hidden="true" />
              <span>New analysis</span>
            </Link>
          }
        />
      ) : (
        <RecentCallsList calls={recent} onHiddenChange={setHiddenRecent} />
      )}
    </OperationalPanel>
  );
}
