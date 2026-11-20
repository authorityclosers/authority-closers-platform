import { notFound } from "next/navigation";

import { isSettingsSection, SETTINGS_SECTIONS } from "../settings-sections";
import { SettingsSectionView } from "../sections";

/** Every section address, so the static preview (output: "export") can build the page. */
export function generateStaticParams() {
  return SETTINGS_SECTIONS.map((section) => ({ section: section.id }));
}

/**
 * One section of Settings, by its address (/settings/profile, /settings/team,
 * …). The organisation's sections open here too (round-2 board 7, 20 Nov
 * 2026), not in its hub.
 */
export default async function SettingsSectionPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  if (!isSettingsSection(section)) notFound();
  return <SettingsSectionView id={section} />;
}
