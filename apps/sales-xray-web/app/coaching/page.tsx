import { Suspense } from "react";
import { CoachingRoute, CoachingSkeleton } from "./coaching-page";
import { PAGE } from "./coaching-copy";
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
  const person = callId ? null : requestedCall(query.person);
  const team = !callId && !person && query.view === "team";
  const result =
    query.call !== undefined && !callId
      ? ({
          data: null,
          error: PAGE.badCallLink,
        } as const)
      : !callId && query.person !== undefined && !person
        ? ({
            data: null,
            error: PAGE.badTeamLink,
          } as const)
        : await loadServerCoaching(
            team ? "team" : person ? `person:${person}` : callId,
          );
  return (
    <Suspense fallback={<CoachingSkeleton />}>
      <CoachingRoute
        initialCallId={callId}
        initialTeam={team}
        initialPerson={person}
        initialResult={result}
      />
    </Suspense>
  );
}
