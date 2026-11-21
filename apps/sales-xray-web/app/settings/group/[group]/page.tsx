import { notFound } from "next/navigation";

import {
  GROUP_SLUG,
  SETTINGS_GROUPS,
  groupBySlug,
} from "../../settings-sections";
import { SettingsGroupView } from "../../settings-hub";

/** Every group's address, so the static preview (output: "export") can build the page. */
export function generateStaticParams() {
  return SETTINGS_GROUPS.map((group) => ({ group: GROUP_SLUG[group] }));
}

/**
 * One group of Settings, by its address (/settings/group/leads, …): the
 * hub's card opens it (sx-redesign pick C, owner 21 Nov 2026), and it lists
 * the group's sections, each one tap from its own page.
 */
export default async function SettingsGroupPage({
  params,
}: {
  params: Promise<{ group: string }>;
}) {
  const { group } = await params;
  const found = groupBySlug(group);
  if (!found) notFound();
  return <SettingsGroupView group={found} />;
}
