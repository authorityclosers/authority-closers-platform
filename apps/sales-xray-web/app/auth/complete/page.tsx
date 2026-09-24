import { AuthCompleteClient } from "./auth-complete-client";
import { parseAuthCompletionQuery } from "../../account-auth-client";

export default async function AuthCompletePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const completion = parseAuthCompletionQuery(await searchParams);
  return (
    <AuthCompleteClient
      flow={completion?.flow ?? null}
      result={completion?.result ?? null}
    />
  );
}
