"use client";

import type { CSSProperties } from "react";

import styles from "./page-skeleton.module.css";

export type SkeletonVariant =
  | "dashboard"
  | "list"
  | "account"
  | "studio"
  | "call";

// Fixed heights so server and client render the same placeholder wave.
const WAVE = Array.from({ length: 64 }, (_, index) => {
  const envelope = Math.abs(Math.sin(index * 0.19) * Math.cos(index * 0.05));
  return Math.round(18 + 70 * (0.3 + 0.7 * envelope));
});

function Bar({
  w,
  h,
  r,
  className = "",
}: {
  w: string | number;
  h: string | number;
  r?: string | number;
  className?: string;
}) {
  return (
    <span
      className={`${styles.block} ${className}`}
      style={{ width: w, height: h, borderRadius: r } as CSSProperties}
    />
  );
}

/**
 * Content-area placeholder shaped like the real screen. It fades in only if
 * loading lasts long enough to notice, so quick loads never flash; one light
 * sheen passes across every placeholder together.
 */
export function PageSkeleton({ variant }: { variant: SkeletonVariant }) {
  return (
    <div className={styles.skeleton} data-variant={variant} aria-hidden="true">
      {variant === "dashboard" ? (
        <div className={styles.dashboard}>
          <div className={styles.stack}>
            <Bar w="min(360px, 70%)" h={34} r={10} />
            <Bar w="min(240px, 50%)" h={14} />
          </div>
          <div className={styles.kpiRow}>
            {Array.from({ length: 4 }, (_, index) => (
              <div key={index} className={styles.card}>
                <Bar w={40} h={40} r={12} />
                <div className={styles.stack}>
                  <Bar w="60%" h={12} />
                  <Bar w="40%" h={22} r={8} />
                </div>
              </div>
            ))}
          </div>
          <div className={styles.analyticsRow}>
            <div className={`${styles.card} ${styles.tall}`}>
              <Bar w="30%" h={14} />
              <Bar w="100%" h="100%" r={12} />
            </div>
            <div className={`${styles.card} ${styles.tall}`}>
              <Bar w="45%" h={14} />
              <Bar w="100%" h="100%" r={12} />
            </div>
          </div>
          <div className={styles.rows}>
            {Array.from({ length: 4 }, (_, index) => (
              <div key={index} className={styles.row}>
                <Bar w={32} h={32} r={9} />
                <Bar w="28%" h={12} />
                <Bar w="14%" h={12} className={styles.pushRight} />
              </div>
            ))}
          </div>
        </div>
      ) : variant === "list" ? (
        <div className={styles.list}>
          <div className={styles.listHead}>
            <Bar w={180} h={24} r={8} />
            <Bar w={260} h={36} r={999} className={styles.pushRight} />
          </div>
          {Array.from({ length: 7 }, (_, index) => (
            <div key={index} className={styles.row}>
              <Bar w={36} h={36} r={10} />
              <div className={styles.stack}>
                <Bar w={`${34 + ((index * 13) % 22)}%`} h={13} />
                <Bar w="18%" h={10} />
              </div>
              <Bar w={84} h={24} r={999} className={styles.pushRight} />
            </div>
          ))}
        </div>
      ) : variant === "account" ? (
        <div className={styles.account}>
          <div className={styles.accountNav}>
            {Array.from({ length: 5 }, (_, index) => (
              <Bar key={index} w="100%" h={34} r={9} />
            ))}
          </div>
          <div className={styles.card}>
            <Bar w="30%" h={20} r={8} />
            {Array.from({ length: 4 }, (_, index) => (
              <div key={index} className={styles.settingRow}>
                <Bar w="26%" h={13} />
                <Bar w={140} h={32} r={8} className={styles.pushRight} />
              </div>
            ))}
          </div>
        </div>
      ) : variant === "call" ? (
        <div className={styles.call}>
          <div className={styles.center}>
            <Bar w={150} h={10} />
            <Bar w="min(460px, 80%)" h={40} r={12} />
            <Bar w="min(380px, 70%)" h={14} />
          </div>
          <div className={styles.wave}>
            {WAVE.map((height, index) => (
              <span
                key={index}
                className={styles.waveBar}
                style={{ height: `${height}%` } as CSSProperties}
              />
            ))}
          </div>
          <div className={styles.stages}>
            {Array.from({ length: 3 }, (_, index) => (
              <div key={index} className={styles.stack}>
                <Bar w="100%" h={4} r={4} />
                <Bar w="55%" h={13} />
                <Bar w="35%" h={10} />
              </div>
            ))}
          </div>
          <div className={styles.foot}>
            <Bar w={36} h={36} r={10} />
            <Bar w={160} h={13} />
            <Bar w={110} h={34} r={999} className={styles.pushRight} />
            <Bar w={130} h={34} r={999} />
          </div>
        </div>
      ) : (
        <div className={styles.studio}>
          <div className={styles.stack}>
            <Bar w="min(460px, 80%)" h={38} r={12} />
            <Bar w="min(320px, 60%)" h={14} />
          </div>
          <div className={styles.drop}>
            <Bar w={58} h={58} r={999} />
            <Bar w={240} h={16} />
            <Bar w={180} h={11} />
            <Bar w={120} h={38} r={10} />
          </div>
        </div>
      )}
    </div>
  );
}
