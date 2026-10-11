import { ChevronRight, Compass } from "lucide-react";

import { CourseActivity } from "@/app/components/admin-dashboard";
import { loadConsoleAccess } from "@/app/lib/console-access";
import { visibleNavigation } from "@/app/lib/nav";
import { Empty, List, Page, PageHeader, Panel, Row } from "@/app/ui/kit";

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

export default async function HomePage() {
  const access = await loadConsoleAccess();
  const groups = visibleNavigation(access).filter((group) => group.label);
  const name = access.displayName?.split(/\s+/)[0];
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
