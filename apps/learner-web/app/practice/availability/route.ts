import { isPracticeUiEnabled } from "../../lib/practice-availability";

// Same immutable image, request-time environment. No identity or tenant selectors.
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json(
    { enabled: isPracticeUiEnabled(process.env) },
    { headers: { "cache-control": "private, no-store" } },
  );
}
