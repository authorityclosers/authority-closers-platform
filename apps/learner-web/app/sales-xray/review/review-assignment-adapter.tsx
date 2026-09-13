"use client";

import {
  AssignedReviewForm,
  type ReviewAssignment,
  type SubmitReviewProposal,
} from "@ac/sales-xray-review-ui";

import styles from "./review-assignment.module.css";

export function ReviewAssignmentAdapter({
  assignmentId,
  assignment,
  onSubmit,
}: {
  assignmentId: string;
  assignment?: ReviewAssignment;
  onSubmit?: SubmitReviewProposal;
}) {
  if (assignment && onSubmit) {
    return <AssignedReviewForm assignment={assignment} onSubmit={onSubmit} />;
  }

  return (
    <main id="main-content" className="learner-main" tabIndex={-1}>
      <div className="page-container">
        <div className={styles.page}>
          <div className={styles.breadcrumb}>Sales Xray / Assigned review</div>
          <section className={styles.pending} aria-labelledby="review-pending-title">
            <span className={styles.eyebrow}>Assigned review</span>
            <h1 id="review-pending-title">Your review is waiting for a server assignment.</h1>
            <p>
              Assignment <code>{assignmentId}</code> will open here after AC verifies
              your signed-in identity, report revision, private clip permissions,
              and the append-only review cursor.
            </p>
            <dl>
              <div>
                <dt>Access</dt>
                <dd>Exact assignment only</dd>
              </div>
              <div>
                <dt>Reviewer</dt>
                <dd>Resolved from the signed-in account</dd>
              </div>
              <div>
                <dt>Lens</dt>
                <dd>Sales · Technical · UX (view choice only)</dd>
              </div>
            </dl>
            <p className={styles.note} role="status">
              No report, identity, playback URL, or save result is asserted until
              the review service returns the assignment DTO.
            </p>
          </section>
        </div>
      </div>
    </main>
  );
}
