"use client";

/** Sales X-Ray's existing kit path, with its Next router link. */
import * as Kit from "@ac/ui/kit/kit";
import Link from "next/link";
import type { ComponentProps } from "react";

export * from "@ac/ui/kit/kit";
export type { IconComponent, IconComponent as LucideIcon } from "@ac/ui/kit";

export function PageHeader(
  props: Omit<ComponentProps<typeof Kit.PageHeader>, "link">,
) {
  return <Kit.PageHeader {...props} link={Link} />;
}

export function Panel(props: Omit<ComponentProps<typeof Kit.Panel>, "link">) {
  return <Kit.Panel {...props} link={Link} />;
}

export function Kpi(props: Omit<ComponentProps<typeof Kit.Kpi>, "link">) {
  return <Kit.Kpi {...props} link={Link} />;
}

export function Empty(props: Omit<ComponentProps<typeof Kit.Empty>, "link">) {
  return <Kit.Empty {...props} link={Link} />;
}

export function QueryTabs(
  props: Omit<ComponentProps<typeof Kit.QueryTabs>, "link">,
) {
  return <Kit.QueryTabs {...props} link={Link} />;
}

export function Row(props: Omit<ComponentProps<typeof Kit.Row>, "link">) {
  return <Kit.Row {...props} link={Link} />;
}

export function ActionRow(
  props: Omit<ComponentProps<typeof Kit.ActionRow>, "link">,
) {
  return <Kit.ActionRow {...props} link={Link} />;
}
