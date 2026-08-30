import { BookOpenCheck, GitBranch } from "lucide-react";

import { AdminShell } from "../components/admin-shell";
import { PublishVersionForm } from "../components/admin-forms";
import {
  AuditPanel,
  CapabilityBoundary,
  PreviewNotice,
  PrimitiveSequence,
  SectionHeading,
  SourceBoundary,
} from "../components/ops-primitives";

const publishGates = [
  {
    gate: "Immutable version",
    requirement: "Publish a versioned Program → Module → Activity tree.",
    preview: "No version selected",
  },
  {
    gate: "Tenant scope",
    requirement:
      "Resolve the active tenant and prevent cross-tenant identifiers.",
    preview: "Not verifiable",
  },
  {
    gate: "Named permission",
    requirement: "Require catalog_publish on a named admin actor.",
    preview: "Not present",
  },
  {
    gate: "Append-only audit",
    requirement: "Record the immutable transition and trace context.",
    preview: "Not written",
  },
];

export default function CatalogPage() {
  return (
    <AdminShell
      active="catalog"
      eyebrow="UXS-0241–UXS-0250 / catalog / version publish preview"
      title="Publish only what can be explained."
      description="A version gate for the permanent learning hierarchy. Draft content stays out of learner reads until a named admin can authorize an immutable transition."
    >
      <PreviewNotice
        title="No draft version is being presented as publishable."
        body="The catalog API is not connected, so this route shows the publish contract and permanent activity sequence without inventing a program, version, status, or count."
      />

      <div className="workbench-grid">
        <section
          className="panel publish-panel"
          aria-labelledby="publish-panel-title"
        >
          <SectionHeading
            eyebrow="Catalog gate"
            id="publish-panel-title"
            title="Version publish preview"
            body="Review the checks that must pass before a version can become learner-visible. The browser cannot promote a draft by itself."
          />
          <div className="version-placeholder">
            <div className="placeholder-icon" aria-hidden="true">
              <BookOpenCheck size={21} strokeWidth={1.6} />
            </div>
            <div>
              <span className="state-label">NO VERSION SELECTED</span>
              <h3>Waiting for an authorized catalog response</h3>
              <p>
                A connected response will identify the tenant, immutable
                version, topology, and current transition without exposing draft
                payloads to learners.
              </p>
            </div>
          </div>
          <p className="table-scroll-hint" id="publish-gate-table-help">
            Keyboard users can focus this region and scroll horizontally when
            columns exceed the viewport.
          </p>
          <div
            className="table-wrap"
            role="region"
            aria-labelledby="publish-gate-caption"
            aria-describedby="publish-gate-table-help"
            tabIndex={0}
          >
            <table className="gate-table">
              <caption id="publish-gate-caption">
                Publish transition gate contract
              </caption>
              <thead>
                <tr>
                  <th scope="col">Gate</th>
                  <th scope="col">Requirement</th>
                  <th scope="col">Preview result</th>
                </tr>
              </thead>
              <tbody>
                {publishGates.map((gate) => (
                  <tr key={gate.gate}>
                    <th scope="row">{gate.gate}</th>
                    <td>{gate.requirement}</td>
                    <td>
                      <span className="table-status">{gate.preview}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <PublishVersionForm />
        </section>

        <CapabilityBoundary
          title="Promote immutable version"
          detail="Publishing is a one-way visibility transition for a versioned tree. The connected API must validate the full topology before learner reads can see it."
          permission="catalog_publish"
          reason="No named admin actor or authorized catalog endpoint is connected."
          audit="No version transition or catalog audit event is written."
          actionLabel="Publish version (locked)"
        />
      </div>

      <div className="catalog-detail-grid">
        <section className="panel" aria-labelledby="topology-title">
          <SectionHeading
            eyebrow="Permanent primitive"
            id="topology-title"
            title="The tree stays small and durable."
            body="The first slice exposes only the approved learning loop. Activity kinds remain versioned and explainable."
            action={
              <span className="topology-mark" aria-hidden="true">
                <GitBranch size={20} strokeWidth={1.6} />
              </span>
            }
          />
          <div
            className="topology-path"
            aria-label="Permanent content hierarchy"
          >
            <span>PROGRAM</span>
            <b aria-hidden="true">→</b>
            <span>MODULE</span>
            <b aria-hidden="true">→</b>
            <span>ACTIVITY</span>
          </div>
          <PrimitiveSequence />
          <p className="deferred-note">
            <span>Deferred from G1</span> Paid commerce, community, voice
            simulation, autonomous official scoring, and broad B2B controls.
          </p>
        </section>

        <AuditPanel
          id="catalog-audit"
          title="Publication is an auditable transition."
          body="The catalog route will record who published which version, in which tenant context, under which permission. This preview creates no audit event."
        />
      </div>

      <SourceBoundary
        id="catalog-source"
        title="Catalog versions are unavailable in preview."
        body="No catalog request has run. Draft and published versions can appear only after a tenant-scoped server response, so no program name, count, or publication status is asserted here."
      />
    </AdminShell>
  );
}
