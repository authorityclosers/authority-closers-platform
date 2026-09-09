"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  BookOpen,
  Check,
  CircleCheck,
  ClipboardCheck,
  FilePenLine,
  Search,
} from "lucide-react";
import { LearningSymbol } from "@ac/ui";
import { loadStudioPrograms, loadStudioReadiness } from "../admin-api";
import { canUseStudioPermission, useAdminSession } from "../admin-session";
import { LoadBoundary, useStudioData } from "./studio-runtime";
import styles from "./studio-workspace.module.css";

const courseHref = (id: string) => `/studio/programs/${id}`;

export function StudioDashboard() {
  const loader = useMemo(() => () => loadStudioPrograms(), []);
  const { canRead, retry, session, state } = useStudioData(loader, "dashboard");
  const scoped =
    state.status === "ready" &&
    session.status === "ready" &&
    state.data.tenant_id === session.session.tenantId;
  const courses = scoped && state.status === "ready" ? state.data.programs : [];
  const writable =
    session.status === "ready"
      ? courses.filter(
          (course) =>
            course.access === "selected_tenant" &&
            canUseStudioPermission(session, "catalog_write", course.id),
        )
      : [];
  const next =
    writable.find((course) => course.draft_count > 0) ??
    writable[0] ??
    courses[0];
  const canShapeNext = writable.some((course) => course.id === next?.id);
  const name =
    session.status === "ready"
      ? session.session.displayName?.trim().split(/\s+/)[0]
      : null;
  return (
    <LoadBoundary
      canRead={canRead}
      onRetry={retry}
      sessionStatus={session.status}
      status={state.status}
      error={state.error}
    >
      {scoped && state.status === "ready" ? (
        <div className={styles.workspace}>
          <header className={styles.heading}>
            <div>
              <span className={styles.eyebrow}>YOUR TEACHING WORKSPACE</span>
              <h1>
                {name ? `Welcome back, ${name}.` : "Welcome to your Studio."}
              </h1>
              <p>Good teaching starts with one clear next step.</p>
            </div>
          </header>
          <section
            className={styles.overview}
            aria-label="Your course overview"
          >
            {[
              {
                label: "Courses you can access",
                value: courses.length,
                icon: BookOpen,
              },
              {
                label: "Draft versions",
                value: courses.reduce(
                  (total, course) => total + course.draft_count,
                  0,
                ),
                icon: FilePenLine,
              },
              {
                label: "Published courses",
                value: courses.filter(
                  (course) => course.current_published_version_id !== null,
                ).length,
                icon: CircleCheck,
              },
            ].map(({ label, value, icon: Icon }) => (
              <div key={label}>
                <span className={styles.statIcon}>
                  <Icon size={20} aria-hidden="true" />
                </span>
                <div>
                  <strong>{value}</strong>
                  <span>{label}</span>
                </div>
              </div>
            ))}
          </section>
          {state.data.truncated && (
            <p className={styles.note}>
              These totals cover the first 100 courses available to your
              account.
            </p>
          )}
          <div className={styles.dashboardGrid}>
            <section className={styles.focusCard}>
              <div className={styles.focusArt}>
                <LearningSymbol kind="course" size={112} />
              </div>
              <span className={styles.eyebrow}>
                {next
                  ? canShapeNext
                    ? "PICK UP YOUR COURSE"
                    : "EXPLORE YOUR COURSE"
                  : "YOUR COURSES"}
              </span>
              <h2>{next?.title ?? "No courses assigned yet."}</h2>
              <p>
                {next
                  ? canShapeNext
                    ? "Shape the lessons, check the learner preview, and get your next version ready."
                    : "Review this course and the versions available to your account."
                  : "Your assigned courses will appear here when they are ready."}
              </p>
              <Link
                className="button button-primary"
                href={next ? courseHref(next.id) : "/studio/programs"}
              >
                {next ? "Open course" : "Go to courses"}
                <ArrowRight size={18} aria-hidden="true" />
              </Link>
            </section>
            <section
              className={styles.workflowCard}
              aria-labelledby="studio-workflow-title"
            >
              <span className={styles.eyebrow}>FROM IDEA TO LEARNER</span>
              <h2 id="studio-workflow-title">A simple way to publish.</h2>
              <ol>
                <li>
                  <span>
                    <BookOpen size={19} aria-hidden="true" />
                  </span>
                  <div>
                    <strong>Build the course</strong>
                    <p>
                      Organise modules and give every lesson a clear purpose.
                    </p>
                  </div>
                </li>
                <li>
                  <span>
                    <FilePenLine size={19} aria-hidden="true" />
                  </span>
                  <div>
                    <strong>Bring the lessons to life</strong>
                    <p>
                      Add content and choose the right format for each lesson.
                    </p>
                  </div>
                </li>
                <li>
                  <span>
                    <ClipboardCheck size={19} aria-hidden="true" />
                  </span>
                  <div>
                    <strong>Review, then publish</strong>
                    <p>
                      Check the content and resolve publication checks before it
                      reaches learners.
                    </p>
                  </div>
                </li>
              </ol>
              <Link href="/studio/publication" className={styles.textLink}>
                Check publication readiness{" "}
                <ArrowRight size={17} aria-hidden="true" />
              </Link>
            </section>
          </div>
          <section
            className={styles.section}
            aria-labelledby="studio-course-overview"
          >
            <div className={styles.sectionHeading}>
              <h2 id="studio-course-overview">Your courses</h2>
              <Link href="/studio/programs" className={styles.textLink}>
                View all <ArrowRight size={16} aria-hidden="true" />
              </Link>
            </div>
            {courses.length === 0 ? (
              <p className={styles.empty}>
                No courses yet. Your assigned courses and new drafts will appear
                here.
              </p>
            ) : (
              <div className={styles.courseRows}>
                {courses.slice(0, 4).map((course) => (
                  <Link
                    key={course.id}
                    href={courseHref(course.id)}
                    className={styles.courseRow}
                  >
                    <span className={styles.courseIcon}>
                      <BookOpen size={22} aria-hidden="true" />
                    </span>
                    <div>
                      <h3>{course.title}</h3>
                      <p>
                        {course.access === "global_read_only"
                          ? "Shared course · Read only"
                          : `${course.draft_count} ${course.draft_count === 1 ? "draft" : "drafts"} · ${course.version_count} ${course.version_count === 1 ? "version" : "versions"}`}
                      </p>
                    </div>
                    <span className={styles.status}>
                      {course.current_published_version_id
                        ? "Published"
                        : "In progress"}
                    </span>
                    <ArrowRight size={18} aria-hidden="true" />
                  </Link>
                ))}
              </div>
            )}
          </section>
        </div>
      ) : null}
    </LoadBoundary>
  );
}

const checks: Record<string, string> = {
  version_not_draft: "This version is no longer a draft.",
  structure_invalid: "Check lesson order and required activities.",
  provenance_incomplete: "Record the content source and review.",
  content_digest_mismatch: "Review the latest content changes.",
  supersession_required: "Choose the published version this draft replaces.",
};

export function StudioPublicationQueue() {
  const loader = useMemo(() => () => loadStudioReadiness(), []);
  const { canRead, retry, session, state } = useStudioData(
    loader,
    "publication",
  );
  const [filter, setFilter] = useState<"all" | "ready" | "needs-work">("all");
  const [search, setSearch] = useState("");
  const scoped =
    state.status === "ready" &&
    session.status === "ready" &&
    state.data.tenant_id === session.session.tenantId;
  const drafts = scoped && state.status === "ready" ? state.data.drafts : [];
  const visible = drafts.filter(
    (draft) =>
      (filter === "all" || draft.ready === (filter === "ready")) &&
      draft.program_title.toLowerCase().includes(search.toLowerCase().trim()),
  );
  return (
    <LoadBoundary
      canRead={canRead}
      onRetry={retry}
      sessionStatus={session.status}
      status={state.status}
      error={state.error}
    >
      {scoped && state.status === "ready" ? (
        <div className={styles.workspace}>
          <header className={styles.heading}>
            <div>
              <span className={styles.eyebrow}>BEFORE YOU PUBLISH</span>
              <h1>Ready for your learners?</h1>
              <p>
                Work through the checks, preview your lessons, then publish from
                the course.
              </p>
            </div>
            <button className="button button-secondary" onClick={retry}>
              Refresh checks
            </button>
          </header>
          <div className={styles.filterBar}>
            <div className={styles.filters} aria-label="Filter drafts">
              {(
                [
                  ["all", "All drafts"],
                  ["ready", "Ready for review"],
                  ["needs-work", "Needs attention"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={filter === value}
                  onClick={() => setFilter(value)}
                >
                  {label}
                </button>
              ))}
            </div>
            <label className={styles.search}>
              <Search size={18} aria-hidden="true" />
              <input
                aria-label="Find a draft course"
                placeholder="Find a course"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
          </div>
          <section
            className={styles.publicationList}
            aria-label="Draft publication checks"
          >
            {visible.map((draft) => (
              <article
                key={draft.program_version_id}
                className={styles.publicationCard}
              >
                <div className={styles.publicationTop}>
                  <span className={styles.courseIcon}>
                    <ClipboardCheck size={22} aria-hidden="true" />
                  </span>
                  <span
                    className={draft.ready ? styles.ready : styles.attention}
                  >
                    {draft.ready ? "Ready for review" : "Needs attention"}
                  </span>
                </div>
                <h2>{draft.program_title}</h2>
                <p className={styles.note}>
                  Draft · Version {draft.version_number}
                </p>
                {draft.ready ? (
                  <p className={styles.checkPassed}>
                    <Check size={17} aria-hidden="true" /> Publication checks
                    passed. Review the content before publishing.
                  </p>
                ) : (
                  <ul>
                    {draft.blockers.map((blocker) => (
                      <li key={blocker}>
                        {checks[blocker] ??
                          "Open the course to check an additional publication requirement."}
                      </li>
                    ))}
                  </ul>
                )}
                <Link
                  href={courseHref(draft.program_id)}
                  className="button button-secondary"
                >
                  Review course <ArrowRight size={17} aria-hidden="true" />
                </Link>
              </article>
            ))}
            {visible.length === 0 && (
              <div className={styles.empty}>
                <CircleCheck size={32} aria-hidden="true" />
                <h2>
                  {drafts.length === 0
                    ? "No drafts waiting for review"
                    : "No matching drafts"}
                </h2>
                <p>
                  {drafts.length === 0
                    ? "When you create a draft, its publication checks will appear here."
                    : "Try another course name or filter."}
                </p>
                <Link href="/studio/programs" className={styles.textLink}>
                  Go to courses <ArrowRight size={16} aria-hidden="true" />
                </Link>
              </div>
            )}
          </section>
          {state.data.truncated && (
            <p className={styles.note}>
              Showing checks for the oldest 100 drafts available to you.
            </p>
          )}
          <p className={styles.note}>
            Checks reflect the latest response from your academy. Refresh after
            editing a course.
          </p>
        </div>
      ) : null}
    </LoadBoundary>
  );
}

/** Labels, never permissions: mutations continue to enforce persisted scope. */
export function StudioAccountAccess() {
  const state = useAdminSession();
  if (state.status !== "ready")
    return <p role="status">Checking your account…</p>;
  const capabilities = state.session.studioCapabilities.filter(
    (capability) => capability.tenant_id === state.session.tenantId,
  );
  return (
    <dl className={styles.accountDetails}>
      <div>
        <dt>Name</dt>
        <dd>{state.session.displayName || "Not set"}</dd>
      </div>
      <div>
        <dt>Email</dt>
        <dd>{state.session.email}</dd>
      </div>
      {(
        [
          ["catalog_read", "View courses"],
          ["catalog_write", "Edit courses"],
          ["catalog_publish", "Publish courses"],
        ] as const
      ).map(([permission, label]) => {
        const assigned = capabilities.filter(
          (item) => item.permission === permission,
        );
        return (
          <div key={permission}>
            <dt>{label}</dt>
            <dd>
              {assigned.some((item) => item.scope_kind === "tenant")
                ? "Academy-wide"
                : assigned.length
                  ? "Assigned courses"
                  : "Not assigned"}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
