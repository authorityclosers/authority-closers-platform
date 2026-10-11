import { Suspense } from "react";
import { CoachingRoute, CoachingSkeleton } from "./coaching-page";
import { requestedCall } from "./coaching-read";
import { loadServerCoaching } from "./coaching-server";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (process.env.AC_SALES_XRAY_STATIC_PREVIEW === "1")
    return (
      <Suspense fallback={<CoachingSkeleton />}>
        <CoachingRoute />
      </Suspense>
    );
  const query = await searchParams;
  const callId = requestedCall(query.call);
  const team = !callId && query.view === "team";
  const result =
    query.call !== undefined && !callId
      ? ({
          data: null,
          error: "This call link is invalid. Open the call’s report again.",
        } as const)
      : await loadServerCoaching(team ? "team" : callId);
  return (
    <Suspense fallback={<CoachingSkeleton />}>
      <CoachingRoute
        initialCallId={callId}
        initialTeam={team}
        initialResult={result}
      />
    </Suspense>
  );
}
