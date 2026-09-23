import { AuthCompleteClient } from "./auth-complete-client";

export default async function AuthCompletePage({
  searchParams,
}: {
  searchParams: Promise<{ flow?: string | string[] }>;
}) {
  const flow = (await searchParams).flow;
  return <AuthCompleteClient flow={typeof flow === "string" ? flow : null} />;
}
