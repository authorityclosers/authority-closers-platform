"use client";

import { Building2, UserRound } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { useDisplayDates } from "../../display-clock";
import { dismissNotice, notify } from "../../notice-center";
import { Empty, PageHeader } from "../../ui/kit";
import { SectionBoundary } from "../../ui/section-boundary";
import { useWorkspaceAccess } from "../../workspace-access";
import {
  changeRole,
  OrgApiError,
  readActivityDays,
  readMembers,
  removeMember,
  revokeInvite,
  type OrgActivity,
} from "../organisation-api";
import { isTestEmail } from "../organisation-view";
import {
  tallyPatterns,
  useTeamPatterns,
  type ReportPattern,
} from "../team-patterns";
import {
  findMember,
  PERSON_DAYS,
  personActivity,
  skillMatrix,
  weeklyTotals,
} from "./person-data";
import {
  CoachingPanel,
  memberName,
  OutcomesPanel,
  PersonCalls,
  PersonHeader,
  PersonTiles,
  SkillsPanel,
  WeekChart,
  type PersonAction,
} from "./person-panels";
import styles from "./person.module.css";
import { ActivitySkeleton, PersonSkeleton } from "./person-skeleton";

/** Reports read for outcomes and skills: this person's newest ready calls. */
const REPORTS_READ = 12;
const LOAD_NOTICE = "person-load";
const ACTION_NOTICE = "person-action";

type Read<T> =
  | { status: "loading" }
  | { status: "ready"; value: T }
  | { status: "error"; message: string };

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
        setState({
          status: "error",
          message:
            error instanceof OrgApiError
              ? error.message
              : "Check your connection and try again.",
        });
      });
    return () => controller.abort();
  }, [read, on, attempt]);
  const retry = useCallback(() => {
    setState({ status: "loading" });
    setAttempt((value) => value + 1);
  }, []);
  return [state, retry] as const;
}

const readTwelveWeeks = (signal: AbortSignal) =>
  readActivityDays(PERSON_DAYS, signal);

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
  viewerRole: "owner" | "admin" | "member";
}) {
  const router = useRouter();
  const dates = useDisplayDates();
  const [members, retryMembers] = useRead(readMembers, true);
  const [activity, retryActivity] = useRead(readTwelveWeeks, true);
  const [busy, setBusy] = useState(false);

  const failed = members.status === "error" || activity.status === "error";
  useEffect(() => {
    if (!failed) return;
    notify({
      id: LOAD_NOTICE,
      tone: "error",
      title: "Some of this page could not be loaded.",
      message:
        members.status === "error"
          ? members.message
          : activity.status === "error"
            ? activity.message
            : undefined,
      action: {
        label: "Try again",
        run: () => {
          if (members.status === "error") retryMembers();
          if (activity.status === "error") retryActivity();
        },
      },
    });
    return () => dismissNotice(LOAD_NOTICE);
  }, [failed, members, activity, retryMembers, retryActivity]);

  const member =
    members.status === "ready" ? findMember(members.value, id) : null;
  const personId = member?.personId ?? (member ? null : id);
  const isYou = personId === viewerId;
  const canManage = viewerRole === "owner" || viewerRole === "admin";
  // Members see their own activity only; owners and admins see everyone's.
  const sees = canManage || isYou;

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
            : `${memberName(member)} is now ${action.role === "admin" ? "an admin" : "a member"}`,
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
          Only owners and admins see a teammate&apos;s calls and reports.
        </p>
      ) : activity.status === "ready" && personId ? (
        <PersonActivityView
          activity={activity.value}
          personId={personId}
          isYou={isYou}
          firstName={
            (member ? memberName(member) : "This person").split(/\s+/)[0]
          }
        />
      ) : activity.status === "loading" ? (
        <ActivitySkeleton />
      ) : null}
    </>
  );
}

function PersonActivityView({
  activity,
  personId,
  isYou,
  firstName,
}: {
  activity: OrgActivity;
  personId: string;
  isYou: boolean;
  firstName: string;
}) {
  const dates = useDisplayDates();
  const data = useMemo(
    () => personActivity(activity, personId),
    [activity, personId],
  );
  const weeks = useMemo(() => weeklyTotals(data.listed), [data]);
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
        <CoachingPanel isYou={isYou} firstName={firstName} />
      </>
    );

  return (
    <>
      <PersonTiles data={data} weeks={weeks} dates={dates} />
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
        <CoachingPanel isYou={isYou} firstName={firstName} />
      </div>
      <SkillsPanel
        rows={rows}
        calls={data.listed}
        reading={reading}
        dates={dates}
      />
      <PersonCalls data={data} dates={dates} />
    </>
  );
}
