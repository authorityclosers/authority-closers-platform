"use client";

/** The dev-only review page's studio, seeded with the fictional offer under its own browser key. */
import { useEffect } from "react";

import { fixtureOffer } from "./offer-fixture-data";
import { OfferStudio } from "./offer-studio";
import { writeStudio } from "./offer-store";

export const FIXTURE_KEY = "ac-offer-studio-fixture";

export function OfferFixture() {
  useEffect(() => {
    const offer = fixtureOffer();
    writeStudio(FIXTURE_KEY, {
      version: 1,
      offers: [offer],
      activeId: offer.id,
    });
  }, []);
  return <OfferStudio storageKey={FIXTURE_KEY} />;
}
