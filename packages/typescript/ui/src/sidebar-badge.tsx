import React from "react";

export type BadgeVariant = "dot" | "count" | "progress" | "new";

export type SidebarBadgeConfig = {
  variant: BadgeVariant;
  count?: number;
  label?: string;
  progress?: number; // 0 to 100
};

export type SidebarBadgeProps = {
  badge?: SidebarBadgeConfig;
  className?: string;
};

export function SidebarBadge({ badge, className = "" }: SidebarBadgeProps) {
  if (!badge) return null;

  const { variant, count, label, progress } = badge;

  if (variant === "dot") {
    return (
      <>
        <span
          className={`sidebar-badge sidebar-badge--dot${className ? ` ${className}` : ""}`}
          aria-hidden="true"
        />
        <span className="sr-only">{label ?? "Unread notification"}</span>
      </>
    );
  }

  if (variant === "count") {
    if (typeof count !== "number" || count <= 0) return null;
    const displayCount = count > 99 ? "99+" : String(count);
    return (
      <span
        className={`sidebar-badge sidebar-badge--count${className ? ` ${className}` : ""}`}
        aria-label={label ?? `${displayCount} unread`}
      >
        <span aria-hidden="true">{displayCount}</span>
      </span>
    );
  }

  if (variant === "new") {
    return (
      <span
        className={`sidebar-badge sidebar-badge--new${className ? ` ${className}` : ""}`}
        aria-label={label ?? "New item"}
      >
        <span aria-hidden="true">New</span>
      </span>
    );
  }

  if (variant === "progress") {
    if (typeof progress !== "number" || progress < 0) return null;
    const clamped = Math.min(100, Math.max(0, Math.round(progress)));
    return (
      <span
        className={`sidebar-badge sidebar-badge--progress${className ? ` ${className}` : ""}`}
        aria-label={label ?? `${clamped}% completed`}
      >
        <span className="sidebar-badge__progress-track" aria-hidden="true">
          <span
            className="sidebar-badge__progress-fill"
            style={{ width: `${clamped}%` }}
          />
        </span>
        <span className="sidebar-badge__progress-number" aria-hidden="true">
          {clamped}%
        </span>
      </span>
    );
  }

  return null;
}
