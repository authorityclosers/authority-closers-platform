"use client";

/** Sales X-Ray's alerts path, with its Next router link. A normal alert is a
    corner card (notice-center.tsx reads it); this hosts the urgent one. */
import * as Alerts from "@ac/ui/kit/alerts";
import Link from "next/link";

export * from "@ac/ui/kit/alerts";

export function AlertHost() {
  return <Alerts.AlertHost link={Link} />;
}
