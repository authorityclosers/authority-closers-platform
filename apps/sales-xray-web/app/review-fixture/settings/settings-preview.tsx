"use client";

/**
 * Settings with the Leads fixture's fictional organisation, for screenshots:
 * `?section=lead-rules|stages|sources` opens Leads' own settings in their new home
 * (approved map, slice 5, 22 Oct 2026); any other section by its id.
 * `?section=team` and `?section=organisation` read a fictional organisation
 * (tutorial 09): members with roles, an invitation waiting, a verified email
 * domain; `&invite=1` shows inviting by email, `&switcher=open` the
 * workspace switcher (../_fixtures/organisation-fixture).
 * `?section=plan` shows Plan & usage with the plans fixture's billing and a
 * fictional analysis-time balance; `&billing=fail` keeps those reads failing.
 */

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { useBillingAccount } from "../../billing/use-billing-account";
import { SettingsSectionView } from "../../settings/sections";
import { SettingsShell } from "../../settings/settings-shell";
import { isSettingsSection } from "../../settings/settings-sections";
import { FixtureWorkspace } from "../leads/leads-preview";
import { fixtureBilling } from "../plans/fixture-billing";
import { OrganisationFixture } from "../_fixtures/organisation-fixture";

function Section() {
  const query = useSearchParams();
  const id = query.get("section");
  // Plan & usage reads the plans fixture's billing; ?billing=fail leaves
  // every read to fail, to review the "not loaded" state.
  const fixture = id === "plan" && query.get("billing") !== "fail";
  const billing = useBillingAccount(fixture, fixtureBilling);
  return (
    <AcquisitionShell
      authenticated
      homeHref="/"
      active="account"
      pageName="Settings"
      mobileFit={false}
    >
      <SettingsShell>
        {isSettingsSection(id) ? (
          <SettingsSectionView
            id={id}
            billing={fixture ? billing : undefined}
          />
        ) : null}
      </SettingsShell>
    </AcquisitionShell>
  );
}

export function SettingsPreview() {
  return (
    <FixtureWorkspace>
      <Suspense fallback={null}>
        <OrganisationFixture>
          <Section />
        </OrganisationFixture>
      </Suspense>
    </FixtureWorkspace>
  );
}
