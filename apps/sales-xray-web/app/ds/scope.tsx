"use client";

/**
 * Where the AC design system (./index.tsx) draws in Sales X-Ray: Pulse's colour roles
 * (ui/pulse-tokens.css) and the design system's scales (./scale.css) apply inside this
 * scope, and every link in it is Next's own, so pages move without a reload.
 */

import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

import { DsProvider } from "./index";
import "./scale.css";

type LinkProps = ComponentProps<typeof DsProvider>["link"];

export function DsScope({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div data-pulse-scope="" className={className}>
      <DsProvider link={Link as unknown as LinkProps}>{children}</DsProvider>
    </div>
  );
}
