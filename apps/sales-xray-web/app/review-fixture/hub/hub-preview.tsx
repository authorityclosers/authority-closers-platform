"use client";

/**
 * The organisation hub with the fictional organisation, for screenshots and
 * tutorials: /review-fixture/hub, with ?tab=team|analytics|leads|connections|
 * call-ai|company and ?part= as on /organisation. Its reads are answered in
 * the browser (../_fixtures/organisation-fixture, inside the Leads fixture).
 */

import { Suspense } from "react";

import { OrganisationHub } from "../../organisation/org-hub";
import { OrganisationFixture } from "../_fixtures/organisation-fixture";
import { FixtureWorkspace } from "../leads/leads-preview";

export function HubPreview() {
  return (
    <FixtureWorkspace>
      <Suspense fallback={null}>
        <OrganisationFixture>
          <OrganisationHub base="/review-fixture/hub" />
        </OrganisationFixture>
      </Suspense>
    </FixtureWorkspace>
  );
}
