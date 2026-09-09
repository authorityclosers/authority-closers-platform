/// <reference path="./styles.d.ts" />
import type { CSSProperties } from "react";
import { LearningSymbol } from "./learning-symbol";
import styles from "./reward-reveal.module.css";

/** Presentation only: the caller must confirm the reward and fresh transition. */
export function RewardReveal({
  earned,
  animate = false,
}: {
  earned: boolean;
  animate?: boolean;
}) {
  return (
    <div
      className={styles.stage}
      data-animate={animate || undefined}
      aria-hidden="true"
    >
      <div className={styles.halo} />
      <div className={styles.coin}>
        {[1, 2, 3, 4, 5].map((layer) => (
          <span
            key={layer}
            className={styles.edge}
            style={{ "--layer": layer } as CSSProperties}
          />
        ))}
        <span className={styles.face}>
          <LearningSymbol kind={earned ? "credits" : "review"} size={94} />
          <span className={styles.shine} />
        </span>
      </div>
      {animate ? (
        <div className={styles.particles}>
          {Array.from({ length: 10 }, (_, index) => (
            <i
              key={index}
              style={
                {
                  "--angle": `${index * 36}deg`,
                  "--distance": `${index % 2 ? 95 : 78}px`,
                  "--delay": `${(index % 3) * 35}ms`,
                } as CSSProperties
              }
            />
          ))}
        </div>
      ) : null}
      <span className={styles.shadow} />
    </div>
  );
}
