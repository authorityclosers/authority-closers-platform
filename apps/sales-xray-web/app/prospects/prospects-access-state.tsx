import Link from "next/link";

import type { WorkspaceAccessValue } from "../workspace-access";
import { PageSkeleton } from "../shell/page-skeleton";
import informationStyles from "../prospect-information.module.css";
import styles from "./prospects.module.css";

/** Presentation only; the workspace provider and API retain access authority. */
export function ProspectsAccessState({
  access,
}: {
  access: WorkspaceAccessValue | null;
}) {
  if (
    !access ||
    access.authenticated === null ||
    access.status === "loading" ||
    access.status === "selecting"
  )
    return (
      <div aria-busy="true" aria-label="Checking prospect access">
        <PageSkeleton variant="list" />
      </div>
    );
  if (access.authenticated === false)
    return (
      <section className={styles.empty} aria-label="Prospects account access">
        <h1 className={styles.emptyTitle}>Sign in to see your prospects</h1>
        <p className={styles.emptyText}>
          Your saved prospects and their call history appear in your workspace.
        </p>
        <Link
          href="/login"
          prefetch={false}
          className={`${styles.retryBtn} ${styles.accessAction}`}
          onClick={(event) => {
            if (!access.requestAccountSignIn) return;
            event.preventDefault();
            access.requestAccountSignIn();
          }}
        >
          Sign in
        </Link>
      </section>
    );
  if (access.status === "unavailable")
    return (
      <div className={informationStyles.cornerError} role="alert">
        <span>Workspace access is unavailable.</span>
        <button
          type="button"
          className={styles.retryBtn}
          onClick={access.retry}
        >
          Try again
        </button>
      </div>
    );
  return (
    <p className={styles.emptyText}>
      Choose your signed-in workspace to see prospects.
    </p>
  );
}
