import { serverReads } from "../../server-reads";
import { INSIGHTS_PATH, filtersFrom, queryOf } from "./insights-data";
import { InsightsPage } from "./insights-page";

/**
 * Insights, the company view for owners and admins (AUT-1798). Where this
 * server can read the API (dev), the aggregates and the first calls are read
 * here, together, and the page arrives whole; elsewhere the browser reads.
 */
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const filters = filtersFrom(await searchParams);
  const query = queryOf(filters);
  const paths = [INSIGHTS_PATH + query, `${INSIGHTS_PATH}/calls${query}`];
  const reads = await serverReads(paths, 2500);
  return (
    <InsightsPage
      filters={filters}
      initial={reads?.[paths[0]] ?? null}
      initialCalls={reads?.[paths[1]] ?? null}
    />
  );
}
