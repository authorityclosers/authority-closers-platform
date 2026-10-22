import { notFound } from "next/navigation";

import { OffersHeader } from "../../offers/offers-header";
import { OfferFixture } from "../../offers/offer-fixture";
import { Page } from "../../ui/kit";

/**
 * Local review of the Offer Studio with one fictional offer (no API, no
 * account; its own browser key, so real drafts are never touched). Never in
 * a production build.
 */
export default function OffersFixturePage() {
  if (process.env.NODE_ENV !== "development") notFound();
  return (
    <Page>
      <OffersHeader />
      <OfferFixture />
    </Page>
  );
}
