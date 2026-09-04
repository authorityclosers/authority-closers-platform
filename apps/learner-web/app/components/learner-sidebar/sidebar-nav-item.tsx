"use client";

import Link from "next/link";
import React, { useState, useTransition } from "react";
import { SidebarBadge } from "./sidebar-badge";
import { SidebarTooltip } from "./sidebar-tooltip";
import type { SidebarNavItemConfig } from "./sidebar-types";

export type SidebarNavItemProps = {
  item: SidebarNavItemConfig;
  collapsed?: boolean;
  density?: "comfortable" | "compact";
  depth?: number;
  onNavigate?: () => void;
};

export function SidebarNavItem({
  item,
  collapsed = false,
  density = "comfortable",
  depth = 0,
  onNavigate,
}: SidebarNavItemProps) {
  const [isPending, startTransition] = useTransition();
  const [localPending, setLocalPending] = useState(false);

  if (item.visible === false) {
    return null;
  }

  const effectiveDensity = item.density ?? (depth > 0 ? "compact" : density);
  const isCurrent = Boolean(item.current);
  const isDisabled = Boolean(item.disabled);
  const titleText = item.title ?? item.label;

  const handleClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (isDisabled) {
      e.preventDefault();
      return;
    }
    setLocalPending(true);
    startTransition(() => {
      onNavigate?.();
      item.onClick?.();
    });
    try {
      window.dispatchEvent(
        new CustomEvent("ac:ui-nav-click", {
          detail: { destination: item.href, label: item.label },
        }),
      );
    } catch {
      // Non-window fallback
    }
  };

  const navLinkClass = [
    "learner-nav__link",
    "sidebar-nav-item",
    `sidebar-nav-item--${effectiveDensity}`,
    depth > 0 ? `sidebar-nav-item--depth-${depth}` : "",
    isCurrent ? "is-current" : "",
    isDisabled ? "is-disabled" : "",
    isPending || localPending ? "is-pending" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const linkContent = (
    <span className="sidebar-nav-item__inner">
      {item.icon ? (
        <span
          className="learner-nav__icon sidebar-nav-item__icon"
          aria-hidden="true"
        >
          {item.icon}
        </span>
      ) : null}
      <span className="learner-nav__label sidebar-nav-item__label">
        {item.label}
      </span>
      {item.badge ? (
        <span className="sidebar-nav-item__badge-wrapper">
          <SidebarBadge badge={item.badge} />
        </span>
      ) : null}
      {isDisabled && item.disabledReason ? (
        <span className="sr-only">({item.disabledReason})</span>
      ) : null}
    </span>
  );

  const navElement = item.external ? (
    <a
      className={navLinkClass}
      href={item.href}
      aria-current={isCurrent ? "page" : undefined}
      aria-disabled={isDisabled ? "true" : undefined}
      tabIndex={isDisabled ? -1 : undefined}
      title={titleText}
      onClick={handleClick}
    >
      {linkContent}
    </a>
  ) : (
    <Link
      className={navLinkClass}
      href={item.href}
      prefetch={false}
      aria-current={isCurrent ? "page" : undefined}
      aria-disabled={isDisabled ? "true" : undefined}
      tabIndex={isDisabled ? -1 : undefined}
      title={titleText}
      onClick={handleClick}
    >
      {linkContent}
    </Link>
  );

  const wrappedElement = (
    <SidebarTooltip
      active={collapsed}
      content={item.label}
      disabledReason={isDisabled ? item.disabledReason : undefined}
    >
      {navElement}
    </SidebarTooltip>
  );

  const hasChildren = Boolean(item.children && item.children.length > 0);

  return (
    <li
      className={`sidebar-nav-item-container${hasChildren ? " has-children" : ""}`}
    >
      {wrappedElement}
      {hasChildren && !collapsed ? (
        <ul
          className="sidebar-nav__sublist"
          aria-label={`${item.label} subsections`}
        >
          {item.children!.map((child) => (
            <SidebarNavItem
              key={child.id}
              item={child}
              collapsed={collapsed}
              density="compact"
              depth={depth + 1}
              onNavigate={onNavigate}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}
