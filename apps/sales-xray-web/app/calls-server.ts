import { CALLS_LIST_PATH } from "./calls-seed";
import { serverReads, type ServerRead } from "./server-reads";

/**
 * The Calls list's first page read on the server (dev: the internal API
 * origin), as this request; null where the server cannot read (the browser
 * then reads as before).
 */
export async function serverCallsList(): Promise<ServerRead> {
  const reads = await serverReads([CALLS_LIST_PATH]);
  return reads?.[CALLS_LIST_PATH] ?? null;
}
