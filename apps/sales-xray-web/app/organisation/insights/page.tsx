import { serverReads } from "../../server-reads";
import {
  DEFAULT_FILTERS,
  INSIGHTS_PATH,
  filtersFrom,
  queryOf,
  viewFrom,
} from "./insights-data";
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
  // A static preview build has no request: it starts on the default filters
  // and the browser reads the address.
  const staticPreview = process.env.AC_SALES_XRAY_STATIC_PREVIEW === "1";
  const params = staticPreview ? {} : await searchParams;
  const filters = staticPreview ? DEFAULT_FILTERS : filtersFrom(params);
  const query = queryOf(filters);
  const paths = [INSIGHTS_PATH + query, `${INSIGHTS_PATH}/calls${query}`];
  const reads = await serverReads(paths, 2500);
  return (
    <InsightsPage
      filters={filters}
      view={viewFrom(params)}
      initial={reads?.[paths[0]] ?? null}
      initialCalls={reads?.[paths[1]] ?? null}
    />
  );
}
