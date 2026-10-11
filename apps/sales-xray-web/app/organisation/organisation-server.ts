import { serverReads } from "../server-reads";
import {
  ORGANISATION_PATHS,
  type ServerOrganisation,
} from "./organisation-seed";

/**
 * The organisation's three first reads on the server (dev: the internal API
 * origin), together, as this request; null where the server cannot read.
 */
export async function serverOrganisation(): Promise<ServerOrganisation | null> {
  const keys = Object.keys(
    ORGANISATION_PATHS,
  ) as (keyof typeof ORGANISATION_PATHS)[];
  const reads = await serverReads(keys.map((key) => ORGANISATION_PATHS[key]));
  if (!reads) return null;
  return Object.fromEntries(
    keys.map((key) => [key, reads[ORGANISATION_PATHS[key]] ?? null]),
  );
}
