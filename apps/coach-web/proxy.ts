import { type NextRequest, NextResponse } from "next/server";
import { resolveAdminServerContext } from "@ac/operations-web/server-auth";

const COACH_PUBLIC_HOSTS = new Set([
  "coach-staging.authorityclosers.com",
  "coach.authorityclosers.com",
]);

function loginRedirect(request: NextRequest) {
  const host = (
    request.headers.get("host") ?? request.nextUrl.host
  ).toLowerCase();
  if (!COACH_PUBLIC_HOSTS.has(host))
    return new NextResponse(null, {
      status: 421,
      headers: { "cache-control": "no-store" },
    });
  const response = NextResponse.redirect(
    new URL("/login", `https://${host}`),
    307,
  );
  response.headers.set("cache-control", "no-store");
  return response;
}

export async function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname;
  if (
    path === "/healthz" &&
    ["127.0.0.1:3002", "localhost:3002"].includes(
      request.headers.get("host") ?? "",
    )
  ) {
    return NextResponse.json(
      { status: "ok", service: "authority-closers-coach" },
      { headers: { "cache-control": "no-store" } },
    );
  }
  if (path === "/login" || path.startsWith("/v1/")) return NextResponse.next();
  if (
    process.env.NODE_ENV === "development" &&
    process.env.AC_DEV_LOCAL_SANDBOX_ENABLED === "true"
  )
    return NextResponse.next();
  const context = await resolveAdminServerContext({
    cookieHeader: request.headers.get("cookie"),
    internalApiUrl: process.env.AC_INTERNAL_API_URL,
    internalApiHost: process.env.AC_INTERNAL_API_HOST,
  });
  if (!context) return loginRedirect(request);
  if (
    !context.studioCapabilities.some(
      (item) => item.tenant_id === context.tenantId,
    )
  ) {
    return new NextResponse(
      "Academy Studio access is not assigned to this account.",
      {
        status: 403,
        headers: {
          "cache-control": "no-store",
          "x-content-type-options": "nosniff",
        },
      },
    );
  }
  return NextResponse.next();
}
export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml).*)",
  ],
};
