"use client";

/**
 * Home's outline before it has read anything: the route's loading screen, and
 * the page until the workspace list says who is looking. A seller sees Dipak's
 * own blocks, an owner the team's floor, each in its place and waiting, as the
 * page draws them while its reads are on the way, so the page takes over
 * without a jump. Which one: the role this device saw last, a seller's until
 * it has seen one (orchestrator, 9 Nov 2026: the route drew the old
 * dashboard's outline, "Last 30 days" and a chart, for 1 to 7 s on 3G).
 */

import { ModeSwitch } from "./mode-switch";
import { OutcomeTiles, TILE_SETS } from "./outcome-tiles";
import { TeamMore, useKeptSides } from "./sales-home";
import { SellerOutline } from "./seller-home";
import { FloorOutline } from "./team-floor";
import revenue from "./revenue.module.css";
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
          <div className={revenue.endOnly}>
            <ModeSwitch value="team" onChange={nothing} />
          </div>
          <div className={styles.mode} data-mode="team" data-still="">
            <FloorOutline
              outcomes={
                <OutcomeTiles
                  period={7}
                  onPeriod={nothing}
                  performance={null}
                  failed={false}
                  tiles={TILE_SETS.outcomes}
                  layout="grid"
                />
              }
              more={<TeamMore sellers={0} />}
            />
          </div>
        </>
      ) : (
        <div className={styles.mode} data-mode="mine" data-still="">
          <SellerOutline access={sides} />
        </div>
      )}
    </div>
  );
}
