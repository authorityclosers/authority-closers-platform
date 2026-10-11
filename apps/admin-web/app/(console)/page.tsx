import { ChevronRight, Compass } from "lucide-react";

import { normalizeQueue } from "@/app/calls/call-data";
import { CourseActivity } from "@/app/components/admin-dashboard";
import { normalizeHealth } from "@/app/health/health-data";
import { loadConsoleAccess } from "@/app/lib/console-access";
import { visibleNavigation } from "@/app/lib/nav";
import { adminRead } from "@/app/lib/server-api";
import {
  Empty,
  Kpi,
  List,
  Page,
  PageHeader,
  Panel,
  Row,
  Tiles,
  Unavailable,
} from "@/app/ui/kit";

const PURPOSE: Record<string, string> = {
  "/calls": "Listen, read and judge each analysed call, side by side",
  "/gold": "Dipak's labels, and how the AI compares with them",
  "/reviewers": "Assignments and invitations for outside reviewers",
  "/health": "Stuck, failed and retried analyses; durations and cost",
  "/usage": "What people do in Sales Xray, from product events",
  "/outcomes": "Won, lost and follow-ups that reps record",
  "/sales-xray/providers": "Models, routes, prices and benchmarks",
  "/sales-xray/analysis": "Prompt versions, limits and report language",
  "/sales-xray/execution": "Pause new analyses and set the spend limit",
  "/sales-xray/minutes": "Find an account and grant analysis minutes",
  "/synthetic": "The fictional test calls, read-only",
  "/people": "Members, learners and their course records",
  "/platform/organisations": "Teams, members, owners and invitations",
  "/platform?tab=billing": "Orders, payments, refunds and subscriptions",
  "/platform": "Every academy on the platform",
  "/releases": "What runs where, and what's waiting to ship",
  "/updates": "What's new notes shown in Sales Xray",
  "/safety": "Sensitive passages withheld from transcripts",
  "/learning-operations": "Held jobs and restore reconciliation",
  "/studio": "Courses and lessons, in the coach workspace",
};

/** Today at a glance, for the accounts that review calls: both reads go together. */
const loadToday = () =>
  Promise.all([
    adminRead("/v1/admin/conversation/calls?limit=1", normalizeQueue),
    adminRead("/v1/admin/conversation/health?days=1", normalizeHealth),
  ]);

function Today({
  data: [queue, health],
}: {
  data: Awaited<ReturnType<typeof loadToday>>;
}) {
  if (!queue.ok && !health.ok)
    return <Unavailable title="Today's calls" reason={queue.error} />;
  return (
    <Tiles label="Today">
      {queue.ok ? (
        <>
          <Kpi
            label="Reports ready"
            value={queue.data.counts.ready}
            note={
              queue.data.truncated ? "Among the newest 500 calls" : "All calls"
            }
            href="/calls?status=ready"
          />
          <Kpi
            label="Analysing now"
            value={queue.data.counts.analysing}
            href="/calls?status=analysing"
          />
          <Kpi
            label="Failed calls"
            value={queue.data.counts.failed}
            tone={queue.data.counts.failed ? "bad" : "good"}
            href="/calls?status=failed"
          />
        </>
      ) : null}
      {health.ok ? (
        <>
          <Kpi
            label="Reports made today"
            value={
              health.data.byStage.find((row) => row.stage === "C5")?.counts
                .succeeded ?? 0
            }
            href="/health?days=1"
          />
          <Kpi
            label="Failed jobs today"
            value={health.data.byStatus.dead_letter}
            tone={health.data.byStatus.dead_letter ? "bad" : "good"}
            href="/health?days=1"
          />
          <Kpi
            label="Stuck now"
            value={health.data.stuck.length}
            tone={health.data.stuck.length ? "warn" : "good"}
            href="/health?days=1"
          />
        </>
      ) : null}
    </Tiles>
  );
}

export default async function HomePage() {
  const access = await loadConsoleAccess();
  const groups = visibleNavigation(access).filter((group) => group.label);
  const name = access.displayName?.split(/\s+/)[0];
  const today = groups.some((group) =>
    group.items.some((item) => item.href === "/calls"),
  )
    ? await loadToday()
    : null;
  return (
    <Page>
      <PageHeader
        title={name ? `Welcome back, ${name}` : "Admin"}
        context={[
          access.state === "preview"
            ? "Local preview: no session, no data"
            : (access.email ?? "Session not confirmed"),
        ]}
      />
      {today ? <Today data={today} /> : null}
      {groups.length === 0 ? (
        <Panel title="Nothing to open yet">
          <Empty
            icon={Compass}
            title="Your account has no admin sections"
            text="Ask an owner to grant the access you need. Sign out and back in once they have."
          />
        </Panel>
      ) : (
        groups.map((group) => (
          <Panel key={group.label} title={group.label}>
            <List label={group.label}>
              {group.items.map((item) => (
                <Row
                  key={item.href}
                  href={item.href}
                  title={item.label}
                  meta={[PURPOSE[item.href] ?? ""]}
                  end={<ChevronRight size={14} aria-hidden="true" />}
                />
              ))}
            </List>
          </Panel>
        ))
      )}
      <CourseActivity />
    </Page>
  );
}
