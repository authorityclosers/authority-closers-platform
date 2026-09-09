import { type NextRequest, NextResponse } from "next/server";
import { coachAppOrigin } from "@ac/operations-web/origins";

import {
  evaluateAdminAccess,
  canAccessAdminPath,
  LOCAL_PREVIEW_ENV,
  normalizeAdminRuntime,
  renderPermissionDeniedDocument,
} from "./app/lib/admin-access";
import { developmentAdminLoginMode } from "./app/lib/dev-api-proxy";
import {
  resolveAdminServerContext,
  resolvePlatformServerContext,
} from "./app/lib/server-auth";

const INTERNAL_HEALTH_PATH = "/healthz";
const INTERNAL_HEALTH_HOSTS = new Set(["127.0.0.1:3001", "localhost:3001"]);
const ADMIN_PUBLIC_HOSTS = new Set([
  "admin-staging.authorityclosers.com",
  "admin.authorityclosers.com",
]);

function isInternalHealthRequest(request: NextRequest) {
  const requestHost = (
    request.headers.get("host") ?? request.nextUrl.host
  ).toLowerCase();
  return (
    request.nextUrl.pathname === INTERNAL_HEALTH_PATH &&
    INTERNAL_HEALTH_HOSTS.has(requestHost)
  );
}

function sameOriginRedirect(request: NextRequest, path: string) {
  const host = (
    request.headers.get("host") ?? request.nextUrl.host
  ).toLowerCase();
  if (!ADMIN_PUBLIC_HOSTS.has(host))
    return new NextResponse(null, {
      status: 421,
      headers: { "cache-control": "no-store" },
    });
  const response = NextResponse.redirect(new URL(path, `https://${host}`), 307);
  response.headers.set("cache-control", "no-store");
  return response;
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

  // Authentication pages are public; capability checks still guard every workspace.
  if (request.nextUrl.pathname === "/login") return NextResponse.next();

  if (
    /^\/studio(?:\/|$)/.test(request.nextUrl.pathname) ||
    request.nextUrl.pathname === "/catalog"
  ) {
    const origin = coachAppOrigin(
      process.env.AC_COACH_APP_URL,
      process.env.NODE_ENV,
    );
    if (!origin)
      return new NextResponse(
        "Academy Studio is moving to its own workspace. Please try again shortly.",
        { status: 503, headers: { "cache-control": "no-store" } },
      );
    if (!["GET", "HEAD"].includes(request.method))
      return new NextResponse(null, {
        status: 405,
        headers: { "cache-control": "no-store", allow: "GET, HEAD" },
      });
    const path =
      request.nextUrl.pathname === "/catalog"
        ? "/studio/programs"
        : request.nextUrl.pathname;
    // Never forward query strings or cookies between application origins.
    const redirect = NextResponse.redirect(new URL(path, origin), 302);
    redirect.headers.set("cache-control", "no-store");
    return redirect;
  }

  const runtime = normalizeAdminRuntime(process.env.NODE_ENV);
  if (
    runtime === "production" &&
    (request.nextUrl.pathname === "/platform" ||
      request.nextUrl.pathname === "/")
  ) {
    const platform = await resolvePlatformServerContext({
      cookieHeader: request.headers.get("cookie"),
      internalApiUrl: process.env.AC_INTERNAL_API_URL,
      internalApiHost: process.env.AC_INTERNAL_API_HOST,
    });
    if (platform) {
      if (request.nextUrl.pathname === "/")
        return sameOriginRedirect(request, "/platform");
      const response = NextResponse.next();
      response.headers.set("cache-control", "private, no-store");
      return response;
    }
    if (request.nextUrl.pathname === "/platform")
      return sameOriginRedirect(request, "/login");
  }
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
    localPreviewEnabled:
      process.env[LOCAL_PREVIEW_ENV] === "1" ||
      developmentAdminLoginMode(process.env, process.env.NODE_ENV) !== null,
    serverContext,
  });

  if (
    runtime === "production" &&
    serverContext === null &&
    !request.nextUrl.pathname.startsWith("/v1/")
  ) {
    return sameOriginRedirect(request, "/login");
  }

  const studioScopeDenied =
    serverContext !== null &&
    (!serverContext.permissions.includes("admin_surface") ||
      !canAccessAdminPath(serverContext, request.nextUrl.pathname));
  if (decision.allowed && !studioScopeDenied) {
    return NextResponse.next();
  }

  return new NextResponse(renderPermissionDeniedDocument(studioScopeDenied), {
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
