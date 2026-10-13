// Reuse G's approved fictional read-only Insights harness bootstrap replies.
import { journeyApi } from "../../../apps/sales-xray-web/scripts/release-journeys.mjs";

const [method, pathname, search = ""] = process.argv.slice(2);
if (!["GET", "HEAD"].includes(method) || !pathname?.startsWith("/v1/")) {
  throw new Error("The fictional reply helper accepts only /v1/ GET and HEAD");
}
process.stdout.write(
  JSON.stringify(journeyApi().respond(method, pathname, search)),
);
