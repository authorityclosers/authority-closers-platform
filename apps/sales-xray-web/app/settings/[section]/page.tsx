import { notFound } from "next/navigation";

import { isSettingsSection } from "../settings-sections";
import { SettingsSectionView } from "../sections";

/** One section of Settings, by its address (/settings/profile, /settings/team, …). */
export default async function SettingsSectionPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  if (!isSettingsSection(section)) notFound();
  return <SettingsSectionView id={section} />;
}
