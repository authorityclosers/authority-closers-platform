import {
  ArrowUpRight,
  Filter,
  Search,
  ShieldCheck,
  UserRoundSearch,
} from "lucide-react";
import Link from "next/link";

import { AdminShell } from "../components/admin-shell";
import { LearnerLookupForm } from "../components/admin-forms";
import {
  AuditPanel,
  CapabilityBoundary,
  PreviewNotice,
  SectionHeading,
  SourceBoundary,
} from "../components/ops-primitives";

export default function PeoplePage() {
  return (
    <AdminShell
      active="people"
      surface="people"
      eyebrow="People / tenant-scoped learner workspace"
      title="People"
      description="Manage learner visibility and future assignment workflows without guessing at people, groups, progress, or permissions."
    >
      <PreviewNotice
        title="The people read model is outside this foundation release."
        body="The shell is ready for the tenant-scoped people read path. No learner lookup is issued until the API verifies learner_diagnose, active tenant context, redaction, purpose, and audit provenance."
      />

      <section
        className="panel people-table-panel"
        aria-labelledby="people-table-title"
      >
        <div className="people-toolbar">
          <div>
            <span className="section-eyebrow">Directory / learner records</span>
            <h2 id="people-table-title">Learners</h2>
          </div>
          <div className="people-actions">
            <button className="button button-secondary" type="button" disabled>
              Invite people (unavailable)
            </button>
            <button className="button" type="button" disabled>
              Create assignment (unavailable)
            </button>
          </div>
        </div>
        <div
          className="people-filters"
          aria-label="Learner filters unavailable"
        >
          <label className="people-search">
            <Search size={17} aria-hidden="true" />
            <span className="sr-only">Search learners</span>
            <input
              type="search"
              placeholder="Search by name or email"
              disabled
            />
          </label>
          <button className="filter-button" type="button" disabled>
            <Filter size={16} aria-hidden="true" /> Group
          </button>
          <button className="filter-button" type="button" disabled>
            <Filter size={16} aria-hidden="true" /> Status
          </button>
          <button className="filter-button" type="button" disabled>
            <Filter size={16} aria-hidden="true" /> Progress
          </button>
        </div>
        <div
          className="people-table-wrap"
          role="region"
          aria-label="Learner directory empty state"
        >
          <table className="people-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Group</th>
                <th scope="col">Assigned path</th>
                <th scope="col">Progress</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td colSpan={5}>
                  <div className="empty-directory">
                    <ShieldCheck size={22} aria-hidden="true" />
                    <strong>No learner records available</strong>
                    <span>
                      The authorized people API has not returned a tenant-scoped
                      directory.
                    </span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="surface-footnote">
          <ShieldCheck size={14} aria-hidden="true" /> No names, assignments, or
          progress values are fabricated in this preview.
        </p>
      </section>

      <div className="workbench-grid">
        <section className="panel" aria-labelledby="diagnosis-panel-title">
          <SectionHeading
            eyebrow="UI-C041 / diagnosis entry"
            id="diagnosis-panel-title"
            title="Learner diagnosis"
            body="Start with an authenticated server lookup. The browser never accepts a raw subject identifier, infers a tenant, impersonates a learner, or grants access."
          />
          <LearnerLookupForm />
        </section>

        <CapabilityBoundary
          title="Read learner state"
          detail="The diagnosis result will be redacted and version-aware: enrollment, pinned version, activity state, evidence, drafts, and the next explainable action."
          permission="learner_diagnose"
          reason="No API authorization or active named actor is available in this shell."
          audit="No diagnosis request, view-as event, or learner data is written."
          actionLabel="Run diagnosis (locked)"
        />
      </div>

      <SourceBoundary
        id="people-source"
        title="Learner results are unavailable in preview."
        body="No diagnosis request has run. Until a trusted server adapter is connected, learner names, progress, drafts, evidence, and certificate state remain unknown rather than invented."
      />

      <section
        className="panel support-panel"
        aria-labelledby="support-panel-title"
      >
        <SectionHeading
          eyebrow="UI-C062–UI-C064 / support seams"
          id="support-panel-title"
          title="Append, don’t overwrite."
          body="The two support writes remain separate from diagnosis. Both require a named permission, an explicit reason, and append-only audit evidence."
        />
        <div className="support-card-grid">
          <Link className="support-card" href="/people/corrections">
            <span className="support-icon" aria-hidden="true">
              <UserRoundSearch size={18} strokeWidth={1.7} />
            </span>
            <span className="surface-eyebrow">learning_correct</span>
            <h3>Append a correction</h3>
            <p>
              Supersede a verified learning fact while preserving the original
              record.
            </p>
            <span className="inline-link">
              Open form <ArrowUpRight size={15} aria-hidden="true" />
            </span>
          </Link>
          <Link className="support-card" href="/people/grants">
            <span className="support-icon" aria-hidden="true">
              <UserRoundSearch size={18} strokeWidth={1.7} />
            </span>
            <span className="surface-eyebrow">enrollment_grant</span>
            <h3>Grant explicit free access</h3>
            <p>
              Create an audited entitlement only after a reason and provenance
              are captured.
            </p>
            <span className="inline-link">
              Open form <ArrowUpRight size={15} aria-hidden="true" />
            </span>
          </Link>
        </div>
      </section>

      <AuditPanel
        id="people-audit"
        title="Diagnosis reads leave evidence too."
        body="A support read is not invisible. The connected route will record purpose and actor-safe trace context without exposing unnecessary personal data or turning audit into analytics."
      />
    </AdminShell>
  );
}
