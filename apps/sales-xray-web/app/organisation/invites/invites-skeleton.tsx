"use client";

import { Skeleton } from "../../ui/kit";
import styles from "./invites.module.css";

/**
 * Invitations' loading outline, so nothing moves when the page arrives. Its own file, so
 * the frame's route outlines don't load the whole screen (24 Oct 2026).
 */
export function InvitesSkeleton({ bare = false }: { bare?: boolean }) {
  const rows = (
    <div className={styles.skeleton} role="status" aria-busy="true">
      <span className="visually-hidden">Loading your invitations</span>
      <Skeleton width="38%" height={14} />
      <Skeleton height={40} />
    </div>
  );
  if (bare) return rows;
  return (
    <div className={styles.page}>
      <div className={styles.skeletonHead}>
        <Skeleton width={140} height={20} />
      </div>
      {rows}
    </div>
  );
}
