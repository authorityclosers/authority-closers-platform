import { notFound } from "next/navigation";

import {
  hubAddress,
  isSettingsSection,
  SETTINGS_SECTIONS,
} from "../settings-sections";
import { HubRedirect } from "../hub-redirect";
import { SettingsSectionView } from "../sections";

/** Every section address, so the static preview (output: "export") can build the page. */
export function generateStaticParams() {
  return SETTINGS_SECTIONS.map((section) => ({ section: section.id }));
}

/** One section of Settings, by its address (/settings/profile, /settings/team, …). */
export default async function SettingsSectionPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  if (!isSettingsSection(section)) notFound();
  // The organisation's sections live in its hub (owner, 23 Oct 2026).
  const hub = hubAddress(section);
  if (hub) return <HubRedirect to={hub} />;
  return <SettingsSectionView id={section} />;
}
