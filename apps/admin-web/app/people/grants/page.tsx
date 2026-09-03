import { ArrowLeft, KeyRound } from "lucide-react";
import Link from "next/link";

import { AdminShell } from "../../components/admin-shell";
import { ManualGrantForm } from "../../components/admin-forms";
import {
  AuditPanel,
  CapabilityBoundary,
  PreviewNotice,
  SectionHeading,
} from "../../components/ops-primitives";

const grantInvariants = [
  "Access comes from an explicit enrollment and entitlement transaction.",
  "The target, program version, reason, provenance, and actor are auditable.",
  "Analytics, ERP, and provider callbacks cannot create access implicitly.",
];

export default function GrantsPage() {
  return (
    <AdminShell
      active="people"
      activeSupport="grant"
      eyebrow="People / explicit free enrollment"
      title="Grant access with a reason."
      description="A narrow manual-grant seam for support and admin actors. It previews explicit entitlement provenance without creating access."
    >
      <div className="breadcrumb-row">
        <Link className="back-link" href="/people">
          <ArrowLeft size={15} aria-hidden="true" /> Back to people
        </Link>
        <span className="route-code">FUTURE COMMAND / ENROLLMENT GRANT</span>
      </div>

      <PreviewNotice
        title="Entitlement creation is explicitly paused."
        body="The form is structurally inert and accepts no learner or program identifier. A trusted lookup and named permission must resolve a review target before this seam can be replaced."
      />

      <div className="workbench-grid">
        <section className="panel" aria-labelledby="grant-form-title">
          <SectionHeading
            eyebrow="Grant intent"
            id="grant-form-title"
            title="Explicit free enrollment"
            body="The API must resolve the learner, tenant, and immutable published version before creating an audited entitlement."
          />
          <ManualGrantForm />
        </section>

        <CapabilityBoundary
          title="Create enrollment grant"
          detail="A successful command would be idempotent, tenant-safe, and coupled to durable outbox intent for any approved follow-up communication."
          permission="enrollment_grant"
          reason="No named admin actor or authorized enrollment-grant endpoint is connected."
          audit="No entitlement, enrollment, outbox intent, or audit event is created."
          actionLabel="Create grant (locked)"
        />
      </div>

      <section
        className="invariant-panel"
        aria-labelledby="grant-invariants-title"
      >
        <div className="invariant-heading">
          <span className="section-eyebrow">
            <KeyRound size={14} aria-hidden="true" /> Access invariant
          </span>
          <h2 id="grant-invariants-title">A grant is not a shortcut.</h2>
        </div>
        <ul className="invariant-list">
          {grantInvariants.map((invariant) => (
            <li key={invariant}>{invariant}</li>
          ))}
        </ul>
      </section>

      <AuditPanel
        id="grant-audit"
        title="The reason travels with the entitlement."
        body="The connected command will keep grant provenance in the audit channel, distinct from downstream telemetry, so later diagnosis can explain why access exists."
      />
    </AdminShell>
  );
}
