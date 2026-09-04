"use client";

import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import React from "react";

export type SidebarCollapseButtonProps = {
  collapsed: boolean;
  onToggle: () => void;
  className?: string;
  "aria-expanded"?: boolean;
  "aria-controls"?: string;
};

export function SidebarCollapseButton({
  collapsed,
  onToggle,
  className = "",
  "aria-expanded": ariaExpanded,
  "aria-controls": ariaControls = "learner-sidebar",
}: SidebarCollapseButtonProps) {
  const label = collapsed ? "Expand sidebar" : "Collapse sidebar";
  const expandedValue = ariaExpanded !== undefined ? ariaExpanded : !collapsed;

  const handleClick = () => {
    onToggle();
    try {
      window.dispatchEvent(
        new CustomEvent("ac:learner-sidebar-preference", {
          detail: { collapsed: !collapsed },
        }),
      );
    } catch {
      // Ignored in non-browser environments
    }
  };

  const classes = [
    "learner-sidebar-toggle",
    collapsed ? "is-collapsed" : "",
    className && className !== "learner-sidebar-toggle" ? className : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      type="button"
      className={classes}
      onClick={handleClick}
      aria-label={label}
      aria-expanded={expandedValue}
      aria-controls={ariaControls}
      title={label}
    >
      {collapsed ? (
        <PanelLeftOpen size={18} strokeWidth={1.85} aria-hidden="true" />
      ) : (
        <PanelLeftClose size={18} strokeWidth={1.85} aria-hidden="true" />
      )}
      <span className="sr-only learner-sidebar-toggle__label">
        {collapsed ? "Expand" : "Collapse"}
      </span>
    </button>
  );
}
