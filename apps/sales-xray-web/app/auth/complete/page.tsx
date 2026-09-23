import { AuthCompleteClient } from "./auth-complete-client";

export default async function AuthCompletePage({
  searchParams,
}: {
  searchParams: Promise<{ flow?: string | string[] }>;
}) {
  const staticPreview = process.env.AC_SALES_XRAY_STATIC_PREVIEW === "1";
  const flow = staticPreview ? null : (await searchParams).flow;
  return <AuthCompleteClient flow={typeof flow === "string" ? flow : null} />;
}
