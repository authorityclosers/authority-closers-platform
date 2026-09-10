import { proxyDevelopmentAdminApi } from "@ac/operations-web/dev-proxy";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
async function proxy(request: Request): Promise<Response> {
  // Fixed app identity, never selected from a browser header/query.
  return proxyDevelopmentAdminApi(request, undefined, {
    ...process.env,
    AC_DEV_OPERATIONS_SURFACE: "coach",
    AC_DEV_LOCAL_SANDBOX_ADMIN_ORIGIN: "http://coach.localhost:3102",
  });
}
export const GET = proxy;
export const HEAD = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;
