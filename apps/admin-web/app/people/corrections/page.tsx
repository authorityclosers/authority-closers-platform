import { ArrowLeft, FileCheck2 } from "lucide-react";
import Link from "next/link";

import { AdminShell } from "../../components/admin-shell";
import { CorrectionForm } from "../../components/admin-forms";
import {
  AuditPanel,
  CapabilityBoundary,
  PreviewNotice,
  SectionHeading,
} from "../../components/ops-primitives";

const correctionInvariants = [
  "Original evidence remains immutable and addressable.",
  "A superseding event carries actor, reason, provenance, and tenant context.",
  "The correction is idempotent and explainable from its append-only chain.",
];

export default function CorrectionsPage() {
  return (
    <AdminShell
      active="people"
      activeSupport="correction"
      eyebrow="People / append-only correction"
      title="Correct the record without erasing it."
      description="A bounded form for verified learning corrections. It previews the write contract and never mutates evidence from the browser."
    >
      <div className="breadcrumb-row">
        <Link className="back-link" href="/people">
          <ArrowLeft size={15} aria-hidden="true" /> Back to people
        </Link>
        <span className="route-code">FUTURE COMMAND / APPEND CORRECTION</span>
      </div>

      <PreviewNotice
        title="The append boundary is visible before the write exists."
        body="The form is structurally inert and accepts no identifiers or draft values. A trusted lookup, permission check, and review response must exist before this seam can be replaced."
      />

      <div className="workbench-grid">
        <section className="panel" aria-labelledby="correction-form-title">
          <SectionHeading
            eyebrow="Correction intent"
            id="correction-form-title"
            title="Verified supersession"
            body="A trusted lookup must resolve the source and eligible supersession event before review. A direct edit, pasted ID, or destructive delete is not part of this surface."
          />
          <CorrectionForm />
        </section>

        <CapabilityBoundary
          title="Append correction"
          detail="The API should validate tenant ownership, the named correction kind, a non-blank reason, and a valid supersession chain before accepting this command."
          permission="learning_correct"
          reason="No named admin actor or authorized correction endpoint is connected."
          audit="No event is appended; original evidence remains untouched."
          actionLabel="Append correction (locked)"
        />
      </div>

      <section
        className="invariant-panel"
        aria-labelledby="correction-invariants-title"
      >
        <div className="invariant-heading">
          <span className="section-eyebrow">
            <FileCheck2 size={14} aria-hidden="true" /> Non-destructive
            invariant
          </span>
          <h2 id="correction-invariants-title">A correction is a new fact.</h2>
        </div>
        <ul className="invariant-list">
          {correctionInvariants.map((invariant) => (
            <li key={invariant}>{invariant}</li>
          ))}
        </ul>
      </section>

      <AuditPanel
        id="correction-audit"
        title="Correction audit stays separate from telemetry."
        body="When enabled, this command will produce append-only audit evidence. It must never be routed through product analytics or used as a hidden progress shortcut."
      />
    </AdminShell>
  );
}
