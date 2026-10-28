import { Suspense } from "react";

import { LeadsRoute } from "./leads-page";
import { LeadsSkeleton } from "./leads-skeleton";
import { serverLeads } from "./leads-server";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const initial = await serverLeads(searchParams);
  return (
    <Suspense fallback={<LeadsSkeleton />}>
      <LeadsRoute initial={initial} />
    </Suspense>
  );
}
