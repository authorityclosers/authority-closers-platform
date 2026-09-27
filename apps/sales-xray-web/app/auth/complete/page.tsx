import { AuthCompleteClient } from "./auth-complete-client";
import { parseAuthCompletionQuery } from "../../account-auth-client";

export default async function AuthCompletePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const staticPreview = process.env.AC_SALES_XRAY_STATIC_PREVIEW === "1";
  const completion = staticPreview
    ? null
    : parseAuthCompletionQuery(await searchParams);
  return (
    <AuthCompleteClient
      flow={completion?.flow ?? null}
      result={completion?.result ?? null}
    />
  );
}
