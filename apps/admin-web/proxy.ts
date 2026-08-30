import { type NextRequest, NextResponse } from "next/server";

import {
  evaluateAdminAccess,
  LOCAL_PREVIEW_ENV,
  normalizeAdminRuntime,
  renderPermissionDeniedDocument,
} from "./app/lib/admin-access";
import { resolveAdminServerContext } from "./app/lib/server-auth";

const INTERNAL_HEALTH_PATH = "/healthz";
const INTERNAL_HEALTH_HOSTS = new Set(["127.0.0.1:3001", "localhost:3001"]);

function isInternalHealthRequest(request: NextRequest) {
  const requestHost = (request.headers.get("host") ?? request.nextUrl.host).toLowerCase();
  return (
    request.nextUrl.pathname === INTERNAL_HEALTH_PATH &&
    INTERNAL_HEALTH_HOSTS.has(requestHost)
  );
}

/**
 * The only production unlock is the internal API's response after it verifies
 * the opaque session cookie against canonical person, tenant, and membership
 * rows. Query/body/header role assertions never participate in this decision.
 */
export async function proxy(request: NextRequest) {
  if (isInternalHealthRequest(request)) {
    return NextResponse.json(
      { status: "ok", service: "authority-closers-admin" },
      {
        headers: {
          "Cache-Control": "no-store",
          "X-Content-Type-Options": "nosniff",
          "X-Robots-Tag": "noindex, nofollow",
        },
      },
    );
  }

  const runtime = normalizeAdminRuntime(process.env.NODE_ENV);
  const serverContext =
    runtime === "production"
      ? await resolveAdminServerContext({
          cookieHeader: request.headers.get("cookie"),
          internalApiUrl: process.env.AC_INTERNAL_API_URL,
          internalApiHost: process.env.AC_INTERNAL_API_HOST,
        })
      : null;
  const decision = evaluateAdminAccess({
    runtime,
    localPreviewEnabled: process.env[LOCAL_PREVIEW_ENV] === "1",
    serverContext,
  });

  if (decision.allowed) return NextResponse.next();

  return new NextResponse(renderPermissionDeniedDocument(), {
    status: 403,
    headers: {
      "Cache-Control": "no-store",
      "Content-Security-Policy":
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
      "Content-Type": "text/html; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
      "X-Robots-Tag": "noindex, nofollow",
    },
  });
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml).*)",
  ],
};
