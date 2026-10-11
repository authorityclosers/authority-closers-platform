import { CallsLibrary } from "../../calls-library";
import { serverCallsList } from "../../calls-server";

/**
 * Calls: where this server can read the API (dev), the list's first page is
 * read here, with the session, and the page arrives whole (owner, 11 Oct:
 * "server-side data like Pulse"); elsewhere the browser reads it.
 */
export default async function AnalysisCallsPage() {
  return <CallsLibrary insights initial={await serverCallsList()} />;
}
