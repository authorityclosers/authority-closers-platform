import { ArrowUpRight, Database, FileWarning, RefreshCcw } from "lucide-react";
import Link from "next/link";

import { AdminShell } from "../components/admin-shell";
import {
  HeldJobRetryForm,
  ReconciliationForm,
} from "../components/admin-forms";
import {
  AuditPanel,
  CapabilityBoundary,
  PreviewNotice,
  SectionHeading,
  SourceBoundary,
} from "../components/ops-primitives";

const operationMetrics = [
  { label: "Restore-held projection", value: "—" },
  { label: "Retry eligibility projection", value: "—" },
  { label: "Reconciliation projection", value: "—" },
];

export default function LearningOperationsPage() {
  return (
    <AdminShell
      active="operations"
      eyebrow="UXS-0271–UXS-0280 / learning operations / held side effects"
      title="Recovery policy stops before send."
      description="A narrow preview of held-job retry and explicit restore reconciliation contracts. No queue or live job state is connected."
    >
      <PreviewNotice
        title="No queue state is asserted."
        body="This route documents retry and reconciliation boundaries only. It does not claim a job is held, retryable, restored, or released."
      />

      <section
        className="metrics-grid ops-metrics"
        aria-label="Operations snapshot"
      >
        {operationMetrics.map(({ label, value }, index) => (
          <article className="metric-card" key={label}>
            <div className="metric-topline">
              <span className="metric-index">0{index + 1}</span>
              <Database size={17} strokeWidth={1.7} aria-hidden="true" />
            </div>
            <span className="metric-label">{label}</span>
            <strong>{value}</strong>
            <small>awaiting operations API</small>
          </article>
        ))}
      </section>

      <div className="workbench-grid operations-grid">
        <section className="panel" aria-labelledby="held-job-title">
          <SectionHeading
            eyebrow="Held job retry"
            id="held-job-title"
            title="Retry only a valid held job."
            body="A future retry is a named, idempotent command. A trusted lookup must first resolve an eligible job; the browser cannot accept a raw job ID."
            action={
              <span className="operation-icon held-icon" aria-hidden="true">
                <RefreshCcw size={20} strokeWidth={1.6} />
              </span>
            }
          />
          <HeldJobRetryForm />
        </section>

        <CapabilityBoundary
          title="Retry a held job"
          detail="The API must verify job ownership, a retryable state, idempotency, and an attributable reason before a worker can receive the intent."
          permission="job_retry"
          reason="No named operations actor or authorized retry endpoint is connected."
          audit="No retry intent, delivery, or external provider call is created."
          actionLabel="Retry held job (locked)"
        />
      </div>

      <div className="workbench-grid operations-grid">
        <section className="panel" aria-labelledby="reconciliation-title">
          <SectionHeading
            eyebrow="Restore reconciliation"
            id="reconciliation-title"
            title="Name the release set."
            body="Recovery review is explicit: a trusted source must resolve the exact eligible job set before an operator can review a reconciliation reason."
            action={
              <span className="operation-icon recovery-icon" aria-hidden="true">
                <FileWarning size={20} strokeWidth={1.6} />
              </span>
            }
          />
          <ReconciliationForm />
        </section>

        <CapabilityBoundary
          title="Reconcile restore hold"
          detail="Reconciliation is a separate permissioned command. It does not release the entire queue, and startup or readiness cannot stand in for it."
          permission="recovery_reconcile"
          reason="No named operations actor or recovery reconciliation endpoint is connected."
          audit="No held job is acknowledged, released, or sent to a provider."
          actionLabel="Reconcile release set (locked)"
        />
      </div>

      <SourceBoundary
        id="operations-source"
        title="Queue state is unavailable in preview."
        body="No queue request has run. A tenant-scoped operations adapter must provide a projection before an operator can inspect a job; IDs, retry counts, and restore timestamps remain unknown."
        source="tenant-scoped operations API"
      />

      <section className="recovery-note" aria-labelledby="recovery-note-title">
        <div className="recovery-note-icon" aria-hidden="true">
          <FileWarning size={21} strokeWidth={1.6} />
        </div>
        <div>
          <span className="section-eyebrow">Recovery invariant</span>
          <h2 id="recovery-note-title">A restore hold must be explicit.</h2>
          <p>
            If the operations API reports a restored job, policy requires it to
            stay held until an authorized actor reconciles an explicit release
            set. This preview reports no current job state.
          </p>
        </div>
        <Link className="inline-link" href="/people">
          Return to diagnosis <ArrowUpRight size={15} aria-hidden="true" />
        </Link>
      </section>

      <AuditPanel
        id="operations-audit"
        title="Recovery decisions need durable evidence."
        body="Retry and reconciliation will write separate audit evidence with the actor, tenant, reason, job set, idempotency key, and trace. This shell leaves the chain untouched."
        fields={[
          "Named operations actor and tenant context",
          "Held-state precondition and explicit job set",
          "Reason, restore evidence, and idempotency key",
          "Audit event plus request and trace context",
        ]}
      />
    </AdminShell>
  );
}
