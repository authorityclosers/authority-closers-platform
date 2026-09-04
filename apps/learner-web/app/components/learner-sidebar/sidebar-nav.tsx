"use client";

import React from "react";
import { SidebarNavItem } from "./sidebar-nav-item";
import type { SidebarNavSection } from "./sidebar-types";

export type SidebarNavProps = {
  sections: SidebarNavSection[];
  collapsed?: boolean;
  density?: "comfortable" | "compact";
  className?: string;
  ariaLabel?: string;
  onNavigate?: () => void;
};

export function SidebarNav({
  sections,
  collapsed = false,
  density = "comfortable",
  className = "",
  ariaLabel = "Learner workspace sections",
  onNavigate,
}: SidebarNavProps) {
  return (
    <nav
      className={`learner-sidebar__nav sidebar-nav${className ? ` ${className}` : ""}`}
      aria-label={ariaLabel}
    >
      {sections.map((section) => (
        <div key={section.id} className="sidebar-nav__section">
          {section.label && !collapsed ? (
            <p className="learner-sidebar__section-label sidebar-nav__section-label">
              {section.label}
            </p>
          ) : null}
          <ul className="sidebar-nav__list">
            {section.items.map((item) => (
              <SidebarNavItem
                key={item.id}
                item={item}
                collapsed={collapsed}
                density={density}
                onNavigate={onNavigate}
              />
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}
