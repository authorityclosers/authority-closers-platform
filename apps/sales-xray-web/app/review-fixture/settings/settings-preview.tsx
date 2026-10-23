"use client";

/**
 * Settings with the Leads fixture's fictional organisation, for screenshots:
 * `?section=lead-rules|stages|sources` opens Leads' own settings in their new home
 * (approved map, slice 5, 22 Oct 2026); any other section by its id.
 * `?section=team` and `?section=organisation` read a fictional organisation
 * (tutorial 09): members with roles, an invitation waiting, a verified email
 * domain; `&invite=1` shows inviting by email, `&switcher=open` the
 * workspace switcher (../organisation/organisation-fixture).
 */

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { SettingsSectionView } from "../../settings/sections";
import { SettingsShell } from "../../settings/settings-shell";
import { isSettingsSection } from "../../settings/settings-sections";
import { FixtureWorkspace } from "../leads/leads-preview";
import { OrganisationFixture } from "../organisation/organisation-fixture";

function Section() {
  const id = useSearchParams().get("section");
  return (
    <AcquisitionShell
      authenticated
      homeHref="/"
      active="account"
      pageName="Settings"
      mobileFit={false}
    >
      <SettingsShell>
        {isSettingsSection(id) ? <SettingsSectionView id={id} /> : null}
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
