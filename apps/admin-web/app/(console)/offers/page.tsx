import { loadConsoleAccess } from "@/app/lib/console-access";
import { isSalesXrayControl } from "@/app/lib/nav";
import { OfferStudio } from "@/app/offers/offer-studio";
import { OffersHeader } from "@/app/offers/offers-header";
import { Page, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

/**
 * Offer Studio: turn catalogue features into offers, positioning and
 * internal price tiers. Control accounts only; prices stay in Admin.
 */
export default async function OffersPage() {
  const access = await loadConsoleAccess();
  if (access.state !== "preview" && !isSalesXrayControl(access))
    return (
      <Page>
        <Unavailable
          title="Offer Studio"
          reason="Only AC's control accounts can open the Offer Studio."
        />
      </Page>
    );
  return (
    <Page>
      <OffersHeader />
      <OfferStudio />
    </Page>
  );
}
