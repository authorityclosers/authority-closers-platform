import { loadConsoleAccess } from "@/app/lib/console-access";
import { isSalesXrayControl } from "@/app/lib/nav";
import { CatalogueBody } from "@/app/catalogue/catalogue-body";
import { Page, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

/**
 * Everything the AC platform does, from the code (scripts/catalogue). For
 * staff building offers; internal only, like every Admin page.
 */
export default async function CataloguePage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const access = await loadConsoleAccess();
  if (access.state !== "preview" && !isSalesXrayControl(access))
    return (
      <Page>
        <Unavailable
          title="Feature catalogue"
          reason="Only AC's control accounts can open the catalogue."
        />
      </Page>
    );
  const { q } = await searchParams;
  return (
    <Page>
      <CatalogueBody query={q ?? ""} />
    </Page>
  );
}
