import { publicOrigin } from "../oauth-discovery";
import { robotsTxt } from "../robots-txt";

export const dynamic = "force-dynamic";

/** Which pages crawlers may read: production's public policy pages only (robots-txt.ts). */
export function GET(request: Request) {
  const origin = publicOrigin(request.headers);
  return new Response(robotsTxt(origin ? new URL(origin).host : null), {
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "public, max-age=300",
    },
  });
}
