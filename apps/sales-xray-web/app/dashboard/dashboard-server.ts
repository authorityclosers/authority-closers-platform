import { serverReads } from "../server-reads";
import { DASHBOARD_PATHS, type ServerDashboard } from "./dashboard-seed";

/**
 * The dashboard's four reads on the server (dev: the internal API origin),
 * together, as this request. Null where the server cannot read (the browser
 * then reads as before).
 */
export async function serverDashboard(): Promise<ServerDashboard | null> {
  const keys = Object.keys(DASHBOARD_PATHS) as (keyof typeof DASHBOARD_PATHS)[];
  const reads = await serverReads(keys.map((key) => DASHBOARD_PATHS[key]));
  if (!reads) return null;
  return Object.fromEntries(
    keys.map((key) => [key, reads[DASHBOARD_PATHS[key]] ?? null]),
  );
}
