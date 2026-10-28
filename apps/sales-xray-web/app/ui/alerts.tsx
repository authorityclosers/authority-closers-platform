"use client";

/** Sales X-Ray's existing alerts path, with its Next router link. */
import * as Alerts from "@ac/ui/kit/alerts";
import Link from "next/link";

export * from "@ac/ui/kit/alerts";

export function AlertHost() {
  return <Alerts.AlertHost link={Link} />;
}
