import { notFound } from "next/navigation";

import { normalizeTimeline } from "../../sellers/seller-data";
import { SellerTimeline } from "../../sellers/seller-timeline";
import { Page, PageHeader } from "../../ui/kit";
import { sellerFixture } from "./seller-fixture";

/**
 * Local review of Admin → Sellers → What happened with a fictional seller (no
 * API, no account). ?state=clean or ?state=empty for the other cases. Never in
 * a production build.
 */
export default async function SellerFixturePage({
  searchParams,
}: {
  searchParams: Promise<{ state?: string }>;
}) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { state } = await searchParams;
  const timeline = normalizeTimeline(
    sellerFixture(state === "clean" || state === "empty" ? state : "gap"),
  );
  return (
    <Page wide>
      <PageHeader
        title={timeline.person.name ?? "Seller"}
        back={{ href: "/sellers", label: "Sellers" }}
        context={["What happened", "Fixture: a fictional seller"]}
      />
      <SellerTimeline timeline={timeline} />
    </Page>
  );
}
