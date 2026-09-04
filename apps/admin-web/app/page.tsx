import {
  Activity,
  ArrowUpRight,
  BookOpenCheck,
  CircleAlert,
  UsersRound,
} from "lucide-react";
import Link from "next/link";

import { AdminShell } from "./components/admin-shell";
import {
  AuditPanel,
  PreviewNotice,
  SectionHeading,
} from "./components/ops-primitives";

const metrics = [
  {
    label: "Active learners",
    value: "Not measured",
    detail: "No organization read model in this release",
    icon: UsersRound,
  },
  {
    label: "Assigned learning",
    value: "Not measured",
    detail: "No assignment read model in this release",
    icon: BookOpenCheck,
  },
  {
    label: "Completion rate",
    value: "Not measured",
    detail: "No aggregate read model in this release",
    icon: Activity,
  },
  {
    label: "Evidence awaiting review",
    value: "Not measured",
    detail: "No review queue read model in this release",
    icon: CircleAlert,
  },
];

const surfaces = [
  {
    eyebrow: "01 / PEOPLE",
    title: "Diagnose a learner",
    body: "Inspect redacted, tenant-scoped learning state when a named support or admin actor is authorized.",
    permission: "learner_diagnose",
    href: "/people",
  },
  {
    eyebrow: "02 / CATALOG",
    title: "Preview a version publish",
    body: "Review the immutable Program → Module → Activity boundary before a named admin can publish.",
    permission: "catalog_publish",
    href: "/catalog",
  },
  {
    eyebrow: "03 / OPERATIONS",
    title: "Hold, retry, reconcile",
    body: "Keep restored side effects held until an operations actor names an explicit release set.",
    permission: "job_retry · recovery_reconcile",
    href: "/learning-operations",
  },
  {
    eyebrow: "04 / SUPPORT",
    title: "Correct or grant",
    body: "Use append-only correction and explicit access-grant seams with a reason and provenance.",
    permission: "learning_correct · enrollment_grant",
    href: "/people/corrections",
  },
];

export default function AdminHome() {
  return (
    <AdminShell
      active="overview"
      surface="organization"
      eyebrow="Organization overview / read-only foundation"
      title="Organization overview"
      description="A clear starting point for tenant-scoped learning operations. Session and role status remain visible in the header; operational records stay unavailable until their authorized APIs exist."
    >
      <PreviewNotice />

      <section className="metrics-grid" aria-label="Operational snapshot">
        {metrics.map(({ label, value, detail, icon: Icon }, index) => (
          <article className="metric-card" key={label}>
            <div className="metric-topline">
              <span className="metric-index">0{index + 1}</span>
              <Icon size={17} strokeWidth={1.7} aria-hidden="true" />
            </div>
            <span className="metric-label">{label}</span>
            <strong className="metric-value-text">{value}</strong>
            <small>{detail}</small>
          </article>
        ))}
      </section>

      <div className="overview-grid">
        <section
          className="panel surface-panel"
          aria-labelledby="surface-panel-title"
        >
          <SectionHeading
            eyebrow="Admin foundation / available routes"
            id="surface-panel-title"
            title="A focused workspace for the first release."
            body="Navigate the available foundation surfaces below. Every privileged action remains server-authorized and visibly locked when its target or API is outside this release."
          />
          <div className="surface-card-grid">
            {surfaces.map((surface) => (
              <article className="surface-card" key={surface.title}>
                <span className="surface-eyebrow">{surface.eyebrow}</span>
                <h3>{surface.title}</h3>
                <p>{surface.body}</p>
                <code>{surface.permission}</code>
                <Link className="inline-link" href={surface.href}>
                  Open preview <ArrowUpRight size={15} aria-hidden="true" />
                </Link>
              </article>
            ))}
          </div>
        </section>

        <AuditPanel
          id="overview-audit"
          title="Operator evidence is part of the action."
          body="No admin action is recorded by this shell. Once the API seam exists, every privileged read or write must carry actor, tenant, purpose, reason, provenance, and trace context."
        />
      </div>
    </AdminShell>
  );
}
