"use client";

import { can, ROLE_HINT, roleLabel } from "../roles";
import {
  ArrowLeft,
  Building2,
  ChevronRight,
  Phone,
  ShieldCheck,
  Smartphone,
  UserRound,
} from "lucide-react";
import Link from "next/link";
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
  readMemberPhotos,
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
import family from "../family.module.css";
import { captureBadge, useCaptureTeam } from "../capture-setup-panel";
import { saveOwnDisplayName } from "./person-name-client";
import { PersonWork } from "./person-work";
import { SellerSections } from "./seller-profile";
import { PersonSkeleton } from "./person-skeleton";

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
  // A teammate's page is for those who see the team (roles.ts "team.view");
  // anyone else reads one calm line, and nothing is asked of the server.
  const teammateHidden =
    inOrganisation &&
    !can(current?.role, "team.view") &&
    id !== access?.context?.personId.toLowerCase();
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
        ) : !authenticated || !access?.context || !access.workspaces ? (
          // Until the workspace's role is known the page waits and asks
          // nothing (the test robot, 31 Oct 2026: a seller's visit read a
          // teammate's coaching, a 404, before the role arrived).
          <PersonSkeleton />
        ) : !inOrganisation ? (
          <Empty
            icon={Building2}
            title="People belong to an organisation"
            text="Switch to your organisation to see its people."
            action={{ label: "Open Organisation", href: "/organisation" }}
          />
        ) : teammateHidden ? (
          <Empty
            icon={UserRound}
            title="Only owners and managers can see a teammate's page"
            text="You see your own calls and reports, not a teammate's."
            action={{ label: "Back to Organisation", href: "/organisation" }}
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
  // Today's counts from their activity, for the Today card.
  const [today, setToday] = useState<Readonly<Record<string, number>> | null>(
    null,
  );
  // Role & access and Remove open the header's sheet at that step.
  const [request, setRequest] = useState<{ step: "role" | "remove" } | null>(
    null,
  );
  // Their phone, from Sellers' phones, for those who see the team's phones.
  const capture = useCaptureTeam(can(viewerRole, "leads.manage"));
  // Their photo (v0.93): initials while it loads or when there is none.
  const [photos, setPhotos] = useState<Record<string, string>>({});
  useEffect(() => {
    const control = new AbortController();
    void readMemberPhotos(control.signal).then(setPhotos);
    return () => control.abort();
  }, []);

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

  const phone =
    personId && capture.team
      ? (capture.team.people.find((row) => row.person_id === personId) ?? null)
      : null;
  const phoneBadge = phone ? captureBadge(phone) : null;
  const canChangeRole =
    viewerRole === "owner" && manageable && member?.status === "active";
  const firstName = (member ? memberName(member) : "This person").split(
    /\s+/,
  )[0];
  const callsHref = personId
    ? `/analysis/calls?rep=${encodeURIComponent(personId)}`
    : null;
  return (
    <>
      <Link href="/settings/team" className={styles.backLink}>
        <ArrowLeft size={18} aria-hidden="true" />
        Team
      </Link>
      {member ? (
        <PersonHeader
          request={request}
          chips={
            phoneBadge && member.status === "active" ? (
              <span className={family.chip} data-tone={phoneBadge.tone}>
                {phone?.state === "set_up" ? "Phone ready" : phoneBadge.label}
              </span>
            ) : null
          }
          actions={
            sees && callsHref && member.status === "active" ? (
              <Link className={family.primary} href={callsHref}>
                <Phone size={17} aria-hidden="true" />
                {isYou ? "See my calls" : `See ${firstName}'s calls`}
              </Link>
            ) : null
          }
          member={member}
          isYou={isYou}
          photoUrl={member.personId ? (photos[member.personId] ?? null) : null}
          test={isTestEmail(member.email)}
          canChangeRole={canChangeRole}
          canRemove={manageable}
          onRename={
            isYou && member.status === "active"
              ? async (name) => {
                  try {
                    await saveOwnDisplayName(name);
                    retryMembers();
                    notify({
                      id: "person-name",
                      tone: "success",
                      title: "Display name saved",
                      timeout: 3000,
                    });
                  } catch (error) {
                    notify({
                      id: "person-name",
                      tone: "error",
                      title: "Display name wasn't saved",
                      message: error instanceof Error ? error.message : OFFLINE,
                    });
                    throw error;
                  }
                }
              : undefined
          }
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
      ) : personId ? (
        <SellerSections
          personId={personId}
          isYou={isYou}
          canManage={can(viewerRole, "leads.manage")}
          canSeeTeam={can(viewerRole, "team.view")}
          firstName={firstName}
          today={today}
          cards={
            <>
              {phone ? (
                <section className={family.card} aria-label="Phone setup">
                  <div className={family.row}>
                    <span className={family.tile}>
                      <Smartphone aria-hidden="true" />
                    </span>
                    <span className={family.rowText}>
                      <span className={family.rowTitle}>Phone setup</span>
                      <span className={family.chips}>
                        {phoneBadge ? (
                          <span
                            className={family.chip}
                            data-tone={phoneBadge.tone}
                          >
                            {phone.state === "set_up"
                              ? "Call recording on"
                              : phoneBadge.label}
                          </span>
                        ) : null}
                        {(phone.phones?.length
                          ? phone.phones
                          : phone.phone
                            ? [phone.phone]
                            : []
                        ).map((name) => (
                          <span key={name} className={family.chip}>
                            {name}
                          </span>
                        ))}
                        {phone.recording?.last_at ? (
                          <span className={family.chip}>
                            {`Last file ${new Date(
                              phone.recording.last_at,
                            ).toLocaleString("en-IN", {
                              day: "numeric",
                              month: "short",
                              hour: "numeric",
                              minute: "2-digit",
                              timeZone: "Asia/Kolkata",
                            })}`}
                          </span>
                        ) : null}
                      </span>
                    </span>
                    <span />
                  </div>
                </section>
              ) : null}
              {member && member.status === "active" ? (
                <section className={family.card} aria-label="Role and access">
                  <div className={family.row}>
                    <span className={family.tile}>
                      <ShieldCheck aria-hidden="true" />
                    </span>
                    <span className={family.rowText}>
                      <span className={family.rowTitle}>Role &amp; access</span>
                      <span className={family.rowSub} data-wrap="">
                        {roleLabel(member.role)}: {ROLE_HINT[member.role]}
                      </span>
                    </span>
                    {canChangeRole ? (
                      <button
                        type="button"
                        className={family.outline}
                        disabled={busy}
                        onClick={() => setRequest({ step: "role" })}
                      >
                        Change role
                      </button>
                    ) : (
                      <span />
                    )}
                  </div>
                </section>
              ) : null}
            </>
          }
          overview={
            <>
              <PersonWork
                key={personId}
                personId={personId}
                onToday={setToday}
                saved={
                  activity.status === "ready" ? activity.value.data.listed : []
                }
              />
              {activity.status === "ready" ? (
                <details className={styles.reports}>
                  <summary className={styles.reportToggle}>
                    <span>
                      Reports and coaching
                      <small>
                        {activity.value.data.reportsReady} ready · charts,
                        skills and calls
                      </small>
                    </span>
                    <ChevronRight size={18} aria-hidden="true" />
                  </summary>
                  <PersonActivityView
                    summary={activity.value}
                    personId={personId}
                    isYou={isYou}
                  />
                </details>
              ) : activity.status === "error" ? (
                <p className={`${styles.quietLine} ${styles.retryLine}`}>
                  Reports are unavailable.{" "}
                  <button
                    type="button"
                    className={styles.retryChip}
                    onClick={retryActivity}
                  >
                    Try again
                  </button>
                </p>
              ) : activity.status === "loading" ? (
                <p className={styles.quietLine}>Reading saved calls…</p>
              ) : (
                <p className={styles.quietLine}>
                  Reports appear after a recorded call is analysed.
                </p>
              )}
            </>
          }
        />
      ) : null}
      {member && manageable ? (
        <button
          type="button"
          className={family.dangerText}
          disabled={busy}
          onClick={() => setRequest({ step: "remove" })}
        >
          {member.status === "invited"
            ? "Revoke invitation"
            : "Remove from team"}
        </button>
      ) : null}
    </>
  );
}

function PersonActivityView({
  summary,
  personId,
  isYou,
}: {
  summary: PersonSummary;
  personId: string;
  isYou: boolean;
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
    return <CoachingPanel isYou={isYou} personId={personId} />;

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
