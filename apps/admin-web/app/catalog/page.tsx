import {
  BookOpenCheck,
  AlertTriangle,
  ChevronDown,
  CheckCircle2,
  GitBranch,
  MessageSquare,
  PenLine,
  Play,
  RefreshCcw,
  X,
} from "lucide-react";

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
      surface="studio"
      eyebrow="Course studio / outline preview"
      title="Course outline"
      description="A three-pane studio foundation for the versioned learning hierarchy. Content editing and publishing remain unavailable until a trusted catalog API is connected."
    >
      <PreviewNotice
        title="Studio is in preview mode."
        body="The outline below is a contract preview of the approved learning loop. It does not assert saved content, a draft version, publishing status, activity media, or learner visibility."
      />

      <section className="studio-workspace" aria-label="Course studio preview">
        <aside
          className="studio-outline panel"
          aria-labelledby="studio-outline-title"
        >
          <div className="studio-panel-heading">
            <div>
              <span className="section-eyebrow">Content / outline</span>
              <h2 id="studio-outline-title">Free course</h2>
            </div>
            <span className="status-badge status-badge-muted">Preview</span>
          </div>
          <div className="studio-outline-meta">
            Module 1 <span>•</span> foundation loop
          </div>
          <ol className="outline-list">
            <li className="outline-item outline-item-active">
              <span className="outline-icon outline-icon-video">
                <Play size={15} aria-hidden="true" />
              </span>
              <span>
                <strong>1.1 Video</strong>
                <small>Watch / pending media</small>
              </span>
            </li>
            <li className="outline-item">
              <span className="outline-icon outline-icon-reflection">
                <PenLine size={15} aria-hidden="true" />
              </span>
              <span>
                <strong>1.2 Reflection</strong>
                <small>Reflect / evidence</small>
              </span>
            </li>
            <li className="outline-item">
              <span className="outline-icon outline-icon-implement">
                <CheckCircle2 size={15} aria-hidden="true" />
              </span>
              <span>
                <strong>1.3 Implementation</strong>
                <small>Implement / evidence</small>
              </span>
            </li>
            <li className="outline-item">
              <span className="outline-icon outline-icon-review">
                <MessageSquare size={15} aria-hidden="true" />
              </span>
              <span>
                <strong>1.4 Review</strong>
                <small>Review / pending reviewer</small>
              </span>
            </li>
            <li className="outline-item">
              <span className="outline-icon outline-icon-improve">
                <RefreshCcw size={15} aria-hidden="true" />
              </span>
              <span>
                <strong>1.5 Improve</strong>
                <small>Improve / next attempt</small>
              </span>
            </li>
          </ol>
          <p className="studio-disabled-note">
            Adding sections and activities will be enabled only after the
            catalog read/write contract is wired.
          </p>
        </aside>
        <section
          className="studio-activity panel"
          aria-labelledby="studio-activity-title"
        >
          <div className="studio-panel-heading">
            <div>
              <span className="section-eyebrow">
                Activity / selected contract
              </span>
              <h2 id="studio-activity-title">Video</h2>
            </div>
            <button
              className="icon-button"
              type="button"
              aria-label="Delete activity (unavailable)"
              disabled
            >
              <X size={18} aria-hidden="true" />
            </button>
          </div>
          <div className="activity-preview-card">
            <span className="outline-icon outline-icon-video">
              <Play size={18} aria-hidden="true" />
            </span>
            <div>
              <span className="activity-kind">Video activity</span>
              <strong>Approved lesson asset pending</strong>
              <p>
                Playback, transcript, duration, and resource metadata will
                appear here only after an authorized media configuration is
                returned.
              </p>
            </div>
          </div>
          <div className="studio-form-grid">
            <div className="studio-field">
              <span>Activity type</span>
              <div>
                Video <ChevronDown size={15} aria-hidden="true" />
              </div>
            </div>
            <div className="studio-field">
              <span>Availability</span>
              <div>Unavailable in preview</div>
            </div>
          </div>
          <div className="studio-warning">
            <AlertTriangle size={19} aria-hidden="true" />
            <div>
              <strong>Media configuration is not connected</strong>
              <p>
                No transcript or playable media is asserted. Learner-facing
                delivery remains subject to the content/provider gates.
              </p>
            </div>
            <button className="button button-secondary" type="button" disabled>
              Resolve (unavailable)
            </button>
          </div>
          <div className="studio-section-divider">
            <span>Completion rules</span>
            <small>Read-only contract</small>
          </div>
          <label className="studio-radio">
            <input type="radio" checked disabled />{" "}
            <span>
              <strong>Require full completion</strong>
              <small>Final rule is owned by the published version.</small>
            </span>
          </label>
        </section>
        <aside
          className="studio-settings panel"
          aria-label="Studio settings preview"
        >
          <div className="studio-tabs" aria-label="Studio settings sections">
            <span className="studio-tab studio-tab-active">Settings</span>
            <span className="studio-tab">Resources (0)</span>
          </div>
          <div className="studio-setting-group">
            <span className="section-eyebrow">Availability</span>
            <strong>Not set</strong>
            <p>
              Scheduling is unavailable until the catalog API returns a version.
            </p>
          </div>
          <div className="studio-setting-group">
            <span className="section-eyebrow">Prerequisites</span>
            <strong>Not configured</strong>
            <p>No activity prerequisites are asserted by this preview.</p>
          </div>
          <div className="studio-setting-group">
            <span className="section-eyebrow">Visibility</span>
            <strong>Not set</strong>
            <p>
              Learner visibility is determined by publication, not this shell.
            </p>
          </div>
        </aside>
      </section>

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
