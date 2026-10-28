import { settingsPath } from "../settings/settings-sections";

/** Saved Leads settings links use the same destination as today's gear. */
export function legacyLeadSettings(search: string): string | null {
  const query = new URLSearchParams(search);
  const tab = query.get("tab");
  const section =
    tab === "team"
      ? "lead-rules"
      : tab === "sources" || tab === "stages"
        ? tab
        : null;
  if (!section) return null;
  query.delete("tab");
  const suffix = query.toString();
  return `${settingsPath(section)}${suffix ? `?${suffix}` : ""}`;
}
