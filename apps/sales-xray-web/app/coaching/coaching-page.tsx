"use client";

import { FileSearch, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import {
  Button,
  Empty,
  kitStyles,
  PageHeader,
  Panel,
  QueryTabs,
} from "../ui/kit";
import { StandaloneStudio } from "../standalone-studio";
import { useWorkspaceAccess } from "../workspace-access";
import { CallCoachingStory } from "./call-coaching";
import {
  isCallCoaching,
  isTeamCoaching,
  readCoaching,
  requestedCall,
  type CoachingResult,
} from "./coaching-read";
import { callDate } from "./coaching-ui";
import { TeamCoachingStory } from "./team-coaching";
import { CoachingSkeleton } from "./coaching-skeleton";
import { CoachingStory } from "./my-coaching";
import { requestedSkill, type RequestedSkill } from "./focus-request";
import styles from "./coaching.module.css";

export { CoachingSkeleton, CoachingStory };

function CoachingResultBody({
  result,
  callId,
  requestedFocus,
  retry,
}: {
  result: CoachingResult | null;
  callId: string | null;
  requestedFocus?: RequestedSkill;
  retry: () => void;
}) {
  const data = result?.data;
  return (
    <>
      {data ? (
        isCallCoaching(data) ? (
          <CallCoachingStory coaching={data} />
        ) : isTeamCoaching(data) ? (
          <TeamCoachingStory coaching={data} />
        ) : (
          <CoachingStory coaching={data} requestedFocus={requestedFocus} />
        )
      ) : result?.error ? (
        <Panel title="Coaching">
          <Empty
            icon={FileSearch}
            title="Coaching is temporarily unavailable"
            text="Your calls and reports are unaffected. Open the call to check its report and analysis status."
            action={{
              href: callId ? `/analysis/calls/${callId}` : "/analysis/calls",
              label: callId ? "Open the call" : "Open calls",
            }}
          />
        </Panel>
      ) : (
        <CoachingSkeleton />
      )}
      {result?.error ? (
        <aside className={styles.error} role="alert">
          <p>{result.error}</p>
          <div className={styles.actions}>
            <Button onClick={retry}>
              <RefreshCw size={14} aria-hidden="true" />
              Try again
            </Button>
          </div>
        </aside>
      ) : null}
    </>
  );
}

function AccountCoaching({
  personId,
  tenantId,
  sessionId,
  requestedFocus,
  callId,
  initialResult,
  invalidCall,
  team,
}: {
  personId: string;
  tenantId: string;
  sessionId: string;
  requestedFocus?: RequestedSkill;
  callId: string | null;
  initialResult: CoachingResult | null;
  invalidCall: boolean;
  team: boolean;
}) {
  const [result, setResult] = useState<CoachingResult | null>(initialResult);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (invalidCall) return;
    if (attempt === 0 && initialResult !== null) return;
    const controller = new AbortController();
    void readCoaching(team ? "team" : callId, {
      signal: controller.signal,
    }).then((view) => {
      if (controller.signal.aborted) return;
      if (
        view.data &&
        (view.data.person_id !== personId ||
          view.data.tenant_id !== tenantId ||
          (view.data.session_id != null && view.data.session_id !== sessionId))
      )
        setResult({ data: null, error: "Your workspace changed. Try again." });
      else setResult(view);
    });
    return () => controller.abort();
  }, [
    attempt,
    personId,
    tenantId,
    sessionId,
    callId,
    initialResult,
    invalidCall,
    team,
  ]);
  return (
    <CoachingResultBody
      result={result}
      callId={callId}
      requestedFocus={requestedFocus}
      retry={() => {
        if (!invalidCall) setResult(null);
        setAttempt((value) => value + 1);
      }}
    />
  );
}

export function CoachingPage({
  requestedFocus,
  callId = null,
  initialResult = null,
  invalidCall = false,
  team = false,
}: {
  requestedFocus?: RequestedSkill;
  callId?: string | null;
  initialResult?: CoachingResult | null;
  invalidCall?: boolean;
  team?: boolean;
} = {}) {
  const access = useWorkspaceAccess();
  const ready =
    access?.status === "ready" && access.authenticated && access.context;
  const scope = ready
    ? JSON.stringify([ready.personId, ready.tenantId, ready.sessionId])
    : null;
  const [seedScope, setSeedScope] = useState<string | null>(scope);
  if (scope !== null && seedScope === null) setSeedScope(scope);
  const seed =
    initialResult &&
    (!seedScope || seedScope === scope) &&
    (!ready ||
      !initialResult.data ||
      (initialResult.data.person_id === ready.personId &&
        initialResult.data.tenant_id === ready.tenantId &&
        (!initialResult.data.session_id ||
          initialResult.data.session_id === ready.sessionId)))
      ? initialResult
      : null;
  const authenticated =
    access?.authenticated === true ||
    ((!access || access.status === "loading") && !!seed?.data);
  const awaitingAccess = !access || access.status === "loading";
  const workspace = ready
    ? access?.workspaces?.find((item) => item.tenant_id === ready.tenantId)
    : undefined;
  // A hint only: the server decides Team access on every read.
  const showTeam =
    team ||
    (workspace?.kind === "organisation" &&
      (workspace.role === "owner" || workspace.role === "admin"));
  const seededCall =
    callId && seed?.data && isCallCoaching(seed.data) ? seed.data : null;
  return (
    <AcquisitionShell
      authenticated={authenticated}
      loading={awaitingAccess && !seed}
    >
      <div className={styles.root}>
        <PageHeader
          title={
            callId
              ? "Coaching for this call"
              : team
                ? "Team coaching"
                : "My coaching"
          }
          context={
            callId
              ? [
                  seededCall?.call_label ?? "One focus from this call’s report",
                  seededCall?.focus
                    ? callDate(seededCall.focus.selected_at)
                    : "",
                ]
              : team
                ? ["Anonymous totals from your team’s analysed calls"]
                : ["Your focus, mission and progress across calls"]
          }
          back={
            callId
              ? { href: `/analysis/calls/${callId}`, label: "Back to report" }
              : undefined
          }
          actions={
            callId ? (
              <Link className={kitStyles.button} href="/coaching">
                My coaching
              </Link>
            ) : undefined
          }
        />
        {!callId && showTeam ? (
          <QueryTabs
            base="/coaching"
            param="view"
            current={team ? "team" : "me"}
            items={[
              { key: "me", label: "My coaching" },
              { key: "team", label: "Team" },
            ]}
          />
        ) : null}
        {ready ? (
          <AccountCoaching
            key={JSON.stringify([scope, callId, team, seed])}
            personId={ready.personId}
            tenantId={ready.tenantId}
            sessionId={ready.sessionId}
            requestedFocus={requestedFocus}
            callId={callId}
            initialResult={seed}
            invalidCall={invalidCall}
            team={team}
          />
        ) : awaitingAccess ? (
          <CoachingResultBody
            result={seed}
            callId={callId}
            requestedFocus={requestedFocus}
            retry={() => access?.retry()}
          />
        ) : (
          <Panel title="Coaching">
            <Empty
              icon={FileSearch}
              title={
                access.authenticated === false
                  ? "Sign in for your Coaching"
                  : "Choose your workspace"
              }
              text="Coaching follows your own analysed calls in the selected workspace."
              action={
                access.authenticated === false
                  ? { href: "/login", label: "Sign in" }
                  : undefined
              }
            />
          </Panel>
        )}
      </div>
    </AcquisitionShell>
  );
}

/** Static preview and local checks use the same single read; hosted pages arrive with server data. */
export function CoachingRoute({
  initialResult = null,
  initialCallId = null,
  initialTeam = false,
}: {
  initialResult?: CoachingResult | null;
  initialCallId?: string | null;
  initialTeam?: boolean;
} = {}) {
  const access = useWorkspaceAccess();
  const query = useSearchParams();
  const callId = requestedCall(query.get("call"));
  const team = !callId && query.get("view") === "team";
  const invalidCall =
    query.has("call") && (!callId || query.getAll("call").length !== 1);
  const seed = invalidCall
    ? ({
        data: null,
        error: "This call link is invalid. Open the call’s report again.",
      } as const)
    : callId === initialCallId && team === initialTeam
      ? initialResult
      : null;
  const page = (
    <CoachingPage
      callId={callId}
      initialResult={seed}
      invalidCall={invalidCall}
      team={team}
      requestedFocus={requestedSkill(query.get("focus"))}
    />
  );
  return access ? page : <StandaloneStudio>{page}</StandaloneStudio>;
}
