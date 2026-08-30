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
  { label: "Learners requiring attention", value: "—", icon: CircleAlert },
  { label: "Active enrollments", value: "—", icon: UsersRound },
  { label: "Published programs", value: "—", icon: BookOpenCheck },
  { label: "Held jobs", value: "—", icon: Activity },
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
      eyebrow="G1 / operational readiness"
      title="Learning operations"
      description="A narrow support surface for the Free Course walking skeleton: diagnose, publish, correct, grant, retry, reconcile."
    >
      <PreviewNotice />

      <section className="metrics-grid" aria-label="Operational snapshot">
        {metrics.map(({ label, value, icon: Icon }, index) => (
          <article className="metric-card" key={label}>
            <div className="metric-topline">
              <span className="metric-index">0{index + 1}</span>
              <Icon size={17} strokeWidth={1.7} aria-hidden="true" />
            </div>
            <span className="metric-label">{label}</span>
            <strong>{value}</strong>
            <small>awaiting authorized API</small>
          </article>
        ))}
      </section>

      <div className="overview-grid">
        <section
          className="panel surface-panel"
          aria-labelledby="surface-panel-title"
        >
          <SectionHeading
            eyebrow="G1 boundary / operator moves"
            id="surface-panel-title"
            title="Four surfaces. One source of truth."
            body="Each route exposes the smallest operator action needed to support the permanent learning hierarchy without opening a hidden database edit."
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
