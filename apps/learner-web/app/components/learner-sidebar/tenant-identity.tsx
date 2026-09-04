"use client";

import Link from "next/link";
import type { TenantIdentityConfig } from "./sidebar-types";

export type TenantIdentityProps = {
  identity?: TenantIdentityConfig;
  collapsed?: boolean;
  className?: string;
  onClick?: () => void;
};

export function TenantIdentity({
  identity,
  collapsed = false,
  className = "",
  onClick,
}: TenantIdentityProps) {
  const homeHref = identity?.homeHref ?? "/home";
  const academyName = identity?.academyName ?? "";
  const tenantName = identity?.tenantName ?? "";
  const attributionText =
    identity?.attribution ?? (tenantName ? `by ${tenantName}` : "");
  const fullLabel = attributionText
    ? `${academyName} — ${attributionText}`
    : academyName;

  return (
    <Link
      className={`learner-sidebar-wordmark tenant-identity${
        collapsed ? " is-collapsed" : ""
      }${className ? ` ${className}` : ""}`}
      href={homeHref}
      prefetch={false}
      aria-label={fullLabel || undefined}
      title={collapsed && fullLabel ? fullLabel : undefined}
      onClick={onClick}
    >
      <span className="learner-sidebar-wordmark__mark" aria-hidden="true">
        {identity?.mark ?? identity?.logo}
      </span>
      <span className="brand-title-full tenant-identity__copy">
        <span className="tenant-identity__primary">{academyName}</span>
        {attributionText ? (
          <span className="tenant-identity__attribution">
            {attributionText}
          </span>
        ) : null}
      </span>
    </Link>
  );
}
