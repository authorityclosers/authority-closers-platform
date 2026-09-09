import { type NextRequest, NextResponse } from "next/server";
import { resolveAdminServerContext } from "@ac/operations-web/server-auth";

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
  if (!context)
    return new NextResponse(null, {
      status: 307,
      headers: { Location: "/login", "Cache-Control": "no-store" },
    });
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
