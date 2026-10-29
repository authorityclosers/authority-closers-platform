/**
 * Where Leads keeps its last answers on this device (list-cache.ts), and
 * forgetting them: signing out and Refresh app data clear them. Apart from
 * the list's code, so those paths do not load Leads.
 */
export const LEADS_CACHE_SLOT = "sx:leads-cache:v1";

export function forgetLeadData() {
  try {
    window.localStorage.removeItem(LEADS_CACHE_SLOT);
  } catch {
    // Storage refused: nothing was kept.
  }
}
