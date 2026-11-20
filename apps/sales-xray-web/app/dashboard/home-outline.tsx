"use client";

/**
 * Home's outline before it has read anything: the route's loading screen, and
 * the page until the workspace list says who is looking. A seller sees Dipak's
 * work queue, an owner Team today (round 2, 20 Nov 2026), each in its place and waiting, as the
 * page draws them while its reads are on the way, so the page takes over
 * without a jump. Which one: the role this device saw last, a seller's until
 * it has seen one (orchestrator, 9 Nov 2026: the route drew the old
 * dashboard's outline, "Last 30 days" and a chart, for 1 to 7 s on 3G).
 */

import { QueueOutline } from "./home-queue";
import { TeamMore, useKeptSides } from "./sales-home";
import { TeamTodayOutline } from "./team-today";
import { ScopeRow } from "./scope-row";
import styles from "./sales-home.module.css";

const nothing = () => {};

export function HomeOutline({ manager }: { manager: boolean }) {
  const sides = useKeptSides(null);
  return (
    <div
      className={styles.home}
      aria-busy="true"
      aria-label="Loading Home"
      inert
    >
      {manager ? (
        <>
          <ScopeRow value="team" onChange={nothing} />
          <div className={styles.mode} data-mode="team" data-still="">
            <TeamTodayOutline more={<TeamMore sellers={0} />} />
          </div>
        </>
      ) : (
        <div className={styles.mode} data-mode="mine" data-still="">
          <QueueOutline access={sides} />
        </div>
      )}
    </div>
  );
}
