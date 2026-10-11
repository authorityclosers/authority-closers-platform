import { BarChart3 } from "lucide-react";

import { CompanyView } from "@/app/company/company-view";
import {
  INSIGHTS_PATH,
  filtersFrom,
  parseCallPage,
  parseCompany,
} from "@/app/company/company-data";
import { adminRead } from "@/app/lib/server-api";
import { Empty, Page, PageHeader, Panel, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

/**
 * The company view (AUT-1798): one organisation's calls, combined, exactly as
 * its owners see Insights in Sales Xray. Read-only, for AC staff; the
 * sandbox's synthetic history is labelled.
 */
export default async function CompanyPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const filters = filtersFrom(params);
  const organisation =
    typeof params.organisation === "string" &&
    /^[0-9a-f-]{36}$/i.test(params.organisation)
      ? params.organisation
      : null;
  const query = new URLSearchParams();
  if (organisation) query.set("organisation", organisation);
  if (filters.range !== "90d") query.set("range", filters.range);
  for (const name of ["person", "team", "outcome", "language"] as const) {
    const value = filters[name];
    if (value) query.set(name, value);
  }
  const text = query.toString();
  const result = await adminRead(
    INSIGHTS_PATH + (text ? `?${text}` : ""),
    parseCompany,
  );
  const chosen = result.ok ? result.data.organisation : null;
  const offset = Math.max(
    0,
    Math.min(1_000_000, Number.parseInt(String(params.offset ?? "0"), 10) || 0),
  );
  const callQuery = new URLSearchParams(query);
  if (chosen) callQuery.set("organisation", chosen.id);
  if (offset) callQuery.set("offset", String(offset));
  const calls =
    result.ok && chosen
      ? await adminRead(`${INSIGHTS_PATH}/calls?${callQuery}`, parseCallPage)
      : null;
  if (!result.ok)
    return (
      <Page>
        <PageHeader title="Company view" />
        <Unavailable title="Company view" reason={result.error} />
      </Page>
    );
  if (!chosen || !result.data.overview)
    return (
      <Page>
        <PageHeader title="Company view" />
        <Panel title="No organisations">
          <Empty
            icon={BarChart3}
            title="No organisation is served by Sales Xray yet"
            text="Once an organisation has Sales Xray, its calls appear here, combined, as its owners see them."
          />
        </Panel>
      </Page>
    );
  return (
    <CompanyView
      organisations={result.data.organisations}
      organisation={chosen}
      overview={result.data.overview}
      filters={filters}
      calls={calls?.ok ? calls.data : null}
      callsError={calls && !calls.ok ? calls.error : null}
      offset={offset}
    />
  );
}
