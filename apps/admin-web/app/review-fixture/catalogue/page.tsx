import { notFound } from "next/navigation";

import { CatalogueBody } from "../../catalogue/catalogue-body";
import { Page } from "../../ui/kit";

/**
 * Local review of the Feature catalogue (no API, no account; the catalogue
 * is generated data with fictional-fixture screenshots). Never in a
 * production build.
 */
export default async function CatalogueFixturePage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { q } = await searchParams;
  return (
    <Page>
      <CatalogueBody query={q ?? ""} />
    </Page>
  );
}
