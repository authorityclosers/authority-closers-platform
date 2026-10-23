import { notFound } from "next/navigation";

import { normalizeEconomics } from "../../economics/economics-data";
import { EconomicsView } from "../../economics/economics-view";
import { Page, PageHeader } from "../../ui/kit";
import { economicsFixture } from "./economics-fixture";

/**
 * Local review of the economics page with illustrative numbers (no API, no account). Never
 * in a production build.
 */
export default function EconomicsFixturePage() {
  if (process.env.NODE_ENV !== "development") notFound();
  return (
    <Page wide>
      <PageHeader
        title="Economics"
        context={["Fixture: illustrative numbers"]}
      />
      <EconomicsView economics={normalizeEconomics(economicsFixture())} />
    </Page>
  );
}
