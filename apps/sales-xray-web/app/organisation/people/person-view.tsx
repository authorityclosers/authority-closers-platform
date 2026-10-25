"use client";

import { can, roleLabel } from "../roles";
import { Building2, CloudOff, UserRound } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import type { OrgRole } from "../organisation-api";
import { useDisplayDates } from "../../display-clock";
import { dismissNotice, notify } from "../../notice-center";
import { Empty, PageHeader } from "../../ui/kit";
import { SectionBoundary } from "../../ui/section-boundary";
import { useWorkspaceAccess } from "../../workspace-access";
import {
  changeRole,
  notLive,
  OrgApiError,
  readActivityDays,
  readMembers,
  readPersonActivity,
  removeMember,
  revokeInvite,
} from "../organisation-api";
import { isTestEmail } from "../organisation-view";
import {
  tallyPatterns,
  useTeamPatterns,
  type ReportPattern,
} from "../team-patterns";
import {
  findMember,
  fromOrganisation,
  fromPersonWeeks,
  PERSON_DAYS,
  PERSON_WEEKS,
  skillMatrix,
  type PersonSummary,
} from "./person-data";
import {
  CoachingPanel,
  memberName,
  OutcomesPanel,
  PersonCalls,
  PersonHeader,
  LatestCallPanel,
  PersonTiles,
  SkillsPanel,
  WeekChart,
  type PersonAction,
} from "./person-panels";
import styles from "./person.module.css";
import { SellerSections } from "./seller-profile";
import { ActivitySkeleton, PersonSkeleton } from "./person-skeleton";

/** Reports read for outcomes and skills: this person's newest ready calls. */
const REPORTS_READ = 12;
const LOAD_NOTICE = "person-load";
const ACTION_NOTICE = "person-action";

type Read<T> =
  | { status: "loading" }
  | { status: "ready"; value: T }
  | { status: "error"; message: string };

const OFFLINE = "Check your connection and try again.";

/** The server's sentence ("No organisation selected."), never a bare
 * HTTP phrase like "Not Found" or "Internal Server Error". */
function readMessage(error: unknown) {
  return error instanceof OrgApiError && /[.!?]$/.test(error.message.trim())
    ? error.message
    : OFFLINE;
}

function useRead<T>(read: (signal: AbortSignal) => Promise<T>, on: boolean) {
  const [state, setState] = useState<Read<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!on) return;
    const controller = new AbortController();
    read(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setState({ status: "ready", value });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", message: readMessage(error) });
      });
    return () => controller.abort();
  }, [read, on, attempt]);
  const retry = useCallback(() => {
    setState({ status: "loading" });
    setAttempt((value) => value + 1);
  }, []);
  return [state, retry] as const;
}

/** The person's own read; on a server without it, the organisation's. */
async function readPersonSummary(
  id: string,
  signal: AbortSignal,
): Promise<PersonSummary> {
  try {
    return fromPersonWeeks(await readPersonActivity(id, PERSON_WEEKS, signal));
  } catch (error) {
    if (!notLive(error)) throw error;
    return fromOrganisation(await readActivityDays(PERSON_DAYS, signal), id);
  }
}

/** One person in the organisation: who they are, their calls and reports. */
export function PersonView({ id }: { id: string }) {
  const access = useWorkspaceAccess();
  const authenticated = access?.authenticated === true;
  const current =
    access?.workspaces?.find(
      (item) => item.tenant_id === access.context?.tenantId,
    ) ?? null;
  const inOrganisation = authenticated && current?.kind === "organisation";
  return (
    <AcquisitionShell
      authenticated={authenticated}
      homeHref="/"
      active="organisation"
      mobileFit={false}
    >
      <div className={styles.page}>
        {access?.authenticated === false ? (
          <Empty
            icon={UserRound}
            title="Sign in to see this person"
            action={
              access.requestAccountSignIn
                ? { label: "Sign in", onClick: access.requestAccountSignIn }
                : { label: "Sign in", href: "/login" }
            }
          />
        ) : !authenticated || !access?.context ? (
          <PersonSkeleton />
        ) : !inOrganisation ? (
          <Empty
            icon={Building2}
            title="People belong to an organisation"
            text="Switch to your organisation to see its people."
            action={{ label: "Open Organisation", href: "/organisation" }}
          />
        ) : (
          <SectionBoundary name="This person" resetKey={id}>
            <PersonPage
              key={`${access.context.tenantId}:${id}`}
              id={id}
              viewerId={access.context.personId}
              viewerRole={current?.role ?? "member"}
            />
          </SectionBoundary>
        )}
      </div>
    </AcquisitionShell>
  );
}

function PersonPage({
  id,
  viewerId,
  viewerRole,
}: {
  id: string;
  viewerId: string;
  viewerRole: OrgRole;
}) {
  const router = useRouter();
  const dates = useDisplayDates();
  const [members, retryMembers] = useRead(readMembers, true);
  const readSummary = useCallback(
    (signal: AbortSignal) => readPersonSummary(id, signal),
    [id],
  );
  // Your own activity, or everyone's for those who see the team.
  const [activity, retryActivity] = useRead(
    readSummary,
    can(viewerRole, "team.view") || id === viewerId,
  );
  const [busy, setBusy] = useState(false);

  // The directory read names the person: when it fails, a corner card. A
  // failed activity read says so in its own place (below), once.
  const failed = members.status === "error";
  const failure = members.status === "error" ? members.message : undefined;
  useEffect(() => {
    if (!failed) return;
    notify({
      id: LOAD_NOTICE,
      tone: "error",
      title: "Some of this page could not be loaded.",
      message: failure,
      action: { label: "Try again", run: retryMembers },
    });
    return () => dismissNotice(LOAD_NOTICE);
  }, [failed, failure, retryMembers]);

  const member =
    members.status === "ready" ? findMember(members.value, id) : null;
  const personId = member?.personId ?? (member ? null : id);
  const isYou = personId === viewerId;
  const canManage = can(viewerRole, "members.manage");
  // Your own activity, or everyone's for those who see the team.
  const sees = can(viewerRole, "team.view") || isYou;

  if (members.status === "loading") return <PersonSkeleton />;
  if (members.status === "ready" && !member)
    return (
      <Empty
        icon={UserRound}
        title="This person isn't in the organisation"
        text="They may have left, or the link is for another organisation."
        action={{ label: "See everyone", href: "/organisation?tab=members" }}
      />
    );

  const run = async (action: PersonAction) => {
    if (!member) return;
    setBusy(true);
    try {
      if (action.kind === "role" && member.status === "active")
        await changeRole(member.personId, action.role);
      else if (action.kind === "remove")
        await (member.status === "invited"
          ? revokeInvite(member.inviteId)
          : removeMember(member.personId));
      notify({
        id: ACTION_NOTICE,
        tone: "success",
        title:
          action.kind === "remove"
            ? `${memberName(member)} ${member.status === "invited" ? "is no longer invited" : "was removed"}`
            : `${memberName(member)} is now ${roleLabel(action.role)}`,
        timeout: 4000,
      });
      if (action.kind === "remove") router.push("/organisation?tab=members");
      else retryMembers();
    } catch (error) {
      notify({
        id: ACTION_NOTICE,
        tone: "error",
        title: "That change was not saved.",
        message:
          error instanceof OrgApiError
            ? error.message
            : "Check your connection and try again.",
      });
    } finally {
      setBusy(false);
    }
  };

  const manageable =
    !!member &&
    canManage &&
    !isYou &&
    member.role !== "owner" &&
    (member.status === "invited" ||
      viewerRole === "owner" ||
      member.role === "member");

  return (
    <>
      {member ? (
        <PersonHeader
          member={member}
          isYou={isYou}
          test={isTestEmail(member.email)}
          canChangeRole={
            viewerRole === "owner" && manageable && member.status === "active"
          }
          canRemove={manageable}
          busy={busy}
          dates={dates}
          onAction={(action) => void run(action)}
        />
      ) : (
        <PageHeader title="Person" />
      )}
      {member?.status === "invited" ? (
        <Empty
          icon={UserRound}
          title="No calls yet: invitation sent"
          text="Their calls, reports and charts appear here once they join and analyse a call."
        />
      ) : !sees ? (
        <p className={styles.quietLine}>
          You see your own calls and reports here, not a teammate&apos;s.
        </p>
      ) : activity.status === "ready" && personId ? (
        <SellerSections
          personId={personId}
          isYou={isYou}
          canManage={can(viewerRole, "leads.manage")}
          firstName={
            (member ? memberName(member) : "This person").split(/\s+/)[0]
          }
          overview={
            <PersonActivityView
              summary={activity.value}
              personId={personId}
              isYou={isYou}
              firstName={
                (member ? memberName(member) : "This person").split(/\s+/)[0]
              }
            />
          }
        />
      ) : activity.status === "loading" ? (
        <ActivitySkeleton />
      ) : activity.status === "error" ? (
        <Empty
          icon={CloudOff}
          title={
            isYou
              ? "Your calls and reports couldn't be loaded"
              : "Their calls and reports couldn't be loaded"
          }
          text={activity.message}
          action={{ label: "Try again", onClick: retryActivity }}
        />
      ) : null}
    </>
  );
}

function PersonActivityView({
  summary,
  personId,
  isYou,
  firstName,
}: {
  summary: PersonSummary;
  personId: string;
  isYou: boolean;
  firstName: string;
}) {
  const dates = useDisplayDates();
  const { data, weeks } = summary;
  const reportIds = useMemo(
    () =>
      data.listed
        .filter((call) => call.hasReport)
        .slice(0, REPORTS_READ)
        .map((call) => call.id),
    [data],
  );
  const { reads } = useTeamPatterns(reportIds);
  const ready = reportIds.flatMap((callId) => {
    const read = reads.get(callId);
    return read?.status === "ready" && read.pattern
      ? [{ callId, pattern: read.pattern as ReportPattern }]
      : [];
  });
  const reading = reportIds.some((callId) => !reads.has(callId));
  const call = (callId: string) => {
    const row = data.listed.find((item) => item.id === callId);
    return {
      id: callId,
      ownerName: row?.ownerName ?? null,
      label: row?.label ?? null,
      createdAt: row?.createdAt ?? "",
    };
  };
  const tally = tallyPatterns(
    ready.map(({ callId, pattern }) => ({ call: call(callId), pattern })),
  );
  const rows = skillMatrix(ready);

  if (data.calls === 0 && data.listed.length === 0)
    return (
      <>
        <PersonTiles data={data} weeks={weeks} dates={dates} />
        <Empty
          icon={UserRound}
          title={
            isYou
              ? "No calls in the last 12 weeks"
              : `${firstName} has no calls in the last 12 weeks`
          }
          text="Charts and report findings appear after the first analysed call."
        />
        <CoachingPanel isYou={isYou} personId={personId} />
      </>
    );

  return (
    <>
      <PersonTiles data={data} weeks={weeks} dates={dates} />
      <div className={styles.grid}>
        <CoachingPanel isYou={isYou} personId={personId} />
        <LatestCallPanel data={data} dates={dates} />
      </div>
      <div className={styles.grid}>
        <WeekChart
          title="Calls per week"
          weeks={weeks}
          metric="calls"
          unit="calls"
          dates={dates}
        />
        <WeekChart
          title="Minutes per week"
          weeks={weeks}
          metric="minutes"
          unit="min"
          dates={dates}
        />
        <OutcomesPanel tally={tally} reading={reading} />
      </div>
      <SkillsPanel
        rows={rows}
        calls={data.listed}
        reading={reading}
        dates={dates}
      />
      <PersonCalls
        data={data}
        dates={dates}
        callsHref={`/analysis/calls?rep=${encodeURIComponent(personId)}`}
      />
    </>
  );
}
