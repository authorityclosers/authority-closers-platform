"use client";

/**
 * Leads' own settings, at home in Settings (approved map, slice 5, 22 Oct 2026):
 * lead rules, lead stages and pipelines, lead sources. They are the same screens
 * Leads held. /leads?tab=team|stages|sources still opens them there too: Google's,
 * Meta's and the ad platforms' connect flows come back to those addresses.
 */

import { Users } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Empty, Skeleton } from "../ui/kit";
import { JourneyTab } from "./journey/journey-view";
import {
  LEADS_PATH,
  LeadsError,
  leadLink,
  readDesk,
  type Desk,
} from "./leads-client";
import { SourcesView } from "./sources-view";
import { TeamView } from "./team-view";
import styles from "./leads.module.css";

/** Who is reading and what kind of organisation it is: the desk, read once. */
function useDesk() {
  const [round, setRound] = useState(0);
  const [read, setRead] = useState<{
    round: number;
    desk?: Desk;
    error?: string;
  } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    readDesk(controller.signal).then(
      (desk) => setRead({ round, desk }),
      (reason: unknown) => {
        if (controller.signal.aborted) return;
        setRead({
          round,
          error:
            reason instanceof LeadsError
              ? reason.message
              : "Your leads didn't load. Try again.",
        });
      },
    );
    return () => controller.abort();
  }, [round]);
  const current = read?.round === round ? read : null;
  return {
    desk: current?.desk ?? null,
    error: current?.error ?? null,
    retry: () => setRound((value) => value + 1),
  };
}

function Waiting({
  error,
  retry,
}: {
  error: string | null;
  retry: () => void;
}) {
  if (error)
    return (
      <Empty
        icon={Users}
        title="This didn't load"
        text={error}
        action={{ label: "Try again", onClick: retry }}
      />
    );
  return (
    <div className={styles.listSkeleton} aria-busy="true" aria-label="Loading">
      <Skeleton height={86} />
      <Skeleton height={240} />
    </div>
  );
}

/** Settings → Lead rules: who takes new leads, limits, reassigning, work hours. */
export function LeadRulesPane() {
  const router = useRouter();
  return (
    <div className={styles.pane}>
      <TeamView
        onChanged={() => undefined}
        onOpen={(leadId) => router.push(leadLink(leadId))}
      />
    </div>
  );
}

/** Settings → Lead stages: the stages and pipelines, and what the ad platforms learn. */
export function LeadStagesPane() {
  const { desk, error, retry } = useDesk();
  if (!desk) return <Waiting error={error} retry={retry} />;
  return (
    <div className={styles.pane}>
      <JourneyTab canManage={desk.me.can_manage} />
    </div>
  );
}

/** Settings → Lead sources: forms, sheets, webhooks, and Import (which opens on Leads). */
export function LeadSourcesPane() {
  const router = useRouter();
  const { desk, error, retry } = useDesk();
  if (!desk) return <Waiting error={error} retry={retry} />;
  return (
    <div className={styles.pane}>
      <SourcesView
        sandbox={desk.sandbox}
        onChanged={() => undefined}
        onImport={() => router.push(`${LEADS_PATH}?import=file`)}
      />
    </div>
  );
}
