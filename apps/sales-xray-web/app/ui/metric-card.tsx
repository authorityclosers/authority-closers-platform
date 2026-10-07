import type { CSSProperties, ReactNode } from "react";
import Link from "next/link";
import {
  ArrowDownRight,
  ArrowUpRight,
  Minus,
  type LucideIcon,
} from "lucide-react";

import styles from "./metric-card.module.css";

export interface MetricDeltaData {
  value: number;
  previous?: number;
  label?: string;
}

export interface MetricCardProps {
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
  context?: ReactNode;
  source?: ReactNode;
  delta?: MetricDeltaData | ReactNode;
  aside?: ReactNode;
  icon?: LucideIcon;
  iconTone?: "teal" | "amber" | "neutral" | "info";
  href?: string;
  status?: "loading" | "error" | "ready";
  className?: string;
  id?: string;
  style?: CSSProperties;
}

export function MetricCard({
  label,
  value,
  unit,
  context,
  source,
  delta,
  aside,
  icon: Icon,
  iconTone = "neutral",
  href,
  status = "ready",
  className,
  id,
  style,
}: MetricCardProps) {
  const isUnknown = value === null || value === undefined || value === "";
  const isLoading = status === "loading";
  const isError = status === "error";

  const renderDelta = () => {
    if (!delta) return null;
    if (
      typeof delta === "object" &&
      delta !== null &&
      "value" in delta &&
      typeof (delta as MetricDeltaData).value === "number"
    ) {
      const d = delta as MetricDeltaData;
      return (
        <MetricDelta value={d.value} previous={d.previous} label={d.label} />
      );
    }
    return <span className={styles.deltaWrapper}>{delta}</span>;
  };

  const content = (
    <>
      <div className={styles.cardHead}>
        {Icon ? (
          <div className={styles.iconWrap} data-tone={iconTone}>
            <Icon size={18} aria-hidden="true" />
          </div>
        ) : (
          <span />
        )}
        {aside && <div className={styles.asideSlot}>{aside}</div>}
      </div>

      <div className={styles.valueRow}>
        <div className={styles.valueMain}>
          {isLoading ? (
            <span className={styles.skeleton} aria-label="Loading" />
          ) : isError ? (
            <span className={styles.skeleton} aria-hidden="true" />
          ) : (
            <strong className={styles.value}>
              {isUnknown ? "—" : value}
              {unit ? <small className={styles.unit}>{unit}</small> : null}
            </strong>
          )}
          {renderDelta()}
        </div>
      </div>

      <div className={styles.label}>{label}</div>

      {(context !== undefined && context !== null && context !== "") ||
      (source !== undefined && source !== null && source !== "") ? (
        <div className={styles.cardFooter}>
          {context ? <span className={styles.context}>{context}</span> : null}
          {source ? <span className={styles.source}>{source}</span> : null}
        </div>
      ) : (
        <div className={styles.cardFooterPlaceholder} />
      )}
    </>
  );

  if (href) {
    return (
      <Link
        id={id}
        href={href}
        data-pulse-adapted="true"
        className={`${styles.card} ${styles.cardLink}${className ? ` ${className}` : ""}`}
        style={style}
      >
        {content}
      </Link>
    );
  }

  return (
    <div
      id={id}
      data-pulse-adapted="true"
      className={`${styles.card}${className ? ` ${className}` : ""}`}
      style={style}
    >
      {content}
    </div>
  );
}

export function MetricDelta({
  value,
  previous,
  label,
}: {
  value: number;
  previous?: number;
  label?: string;
}) {
  if (previous === undefined || previous === null) {
    return null;
  }
  if (!previous && !value) {
    return (
      <span className={`${styles.delta} ${styles.deltaFlat}`} title={label}>
        <Minus size={12} aria-hidden="true" />
        <span>0</span>
        {label ? <span className={styles.deltaLabel}> {label}</span> : null}
      </span>
    );
  }
  if (!previous) {
    return (
      <span className={`${styles.delta} ${styles.deltaUp}`} title={label}>
        <ArrowUpRight size={13} aria-hidden="true" />
        <span className={styles.srOnly}>new: </span>
        <span>new</span>
        {label ? <span className={styles.deltaLabel}> {label}</span> : null}
      </span>
    );
  }
  const pct = Math.round(((value - previous) / previous) * 100);
  if (pct === 0) {
    return (
      <span className={`${styles.delta} ${styles.deltaFlat}`} title={label}>
        <Minus size={12} aria-hidden="true" />
        <span>0%</span>
        {label ? <span className={styles.deltaLabel}> {label}</span> : null}
      </span>
    );
  }
  const isUp = pct > 0;
  const Icon = isUp ? ArrowUpRight : ArrowDownRight;
  return (
    <span
      className={`${styles.delta} ${isUp ? styles.deltaUp : styles.deltaDown}`}
      title={label}
    >
      <Icon size={13} aria-hidden="true" />
      <span className={styles.srOnly}>
        {isUp ? "increase: " : "decrease: "}
      </span>
      <span>{Math.abs(pct)}%</span>
      {label ? <span className={styles.deltaLabel}> {label}</span> : null}
    </span>
  );
}

export function MetricBand({
  children,
  className,
  columns = 4,
  label = "Key operational metrics",
}: {
  children: ReactNode;
  className?: string;
  columns?: 3 | 4 | 5 | 6;
  label?: string;
}) {
  return (
    <section
      data-pulse-adapted="true"
      className={`${styles.metricBand}${className ? ` ${className}` : ""}`}
      data-columns={columns}
      aria-label={label}
    >
      {children}
    </section>
  );
}
