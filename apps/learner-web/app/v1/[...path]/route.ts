import { proxyDevelopmentLearnerApi } from "../../lib/dev-api-proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

async function proxy(request: Request): Promise<Response> {
  return proxyDevelopmentLearnerApi(request);
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const HEAD = proxy;
export const OPTIONS = proxy;
