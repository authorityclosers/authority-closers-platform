export const dynamic = "force-static";

export function GET() {
  return Response.json({
    status: "ok",
    service: "sales-xray-web",
    release_id: process.env.AC_RELEASE_ID ?? "local-unreleased",
  });
}
