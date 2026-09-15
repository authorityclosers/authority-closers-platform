"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  BookOpen,
  ClipboardCheck,
  Gauge,
  MessagesSquare,
  Settings2,
  UsersRound,
} from "lucide-react";
import { loadStudioPrograms, type StudioPrograms } from "../lib/admin-api";
import {
  canBrowseStudio,
  canManageSalesXray,
  canUseAdminPermission,
  useAdminSession,
} from "../lib/admin-session";
import styles from "./admin-dashboard.module.css";

type Snapshot =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; data: StudioPrograms };
function CourseSnapshot({ tenantId }: { tenantId: string }) {
  const [snapshot, setSnapshot] = useState<Snapshot>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const fetcher: typeof fetch = (input, init) =>
      fetch(input, { ...init, signal: controller.signal });
    void loadStudioPrograms(fetcher)
      .then((data) => {
        if (controller.signal.aborted) return;
        if (data.tenant_id !== tenantId) throw new Error("Workspace changed");
        setSnapshot({ status: "ready", data });
      })
      .catch(() => {
        if (!controller.signal.aborted) setSnapshot({ status: "error" });
      });
    return () => controller.abort();
  }, [tenantId, attempt]);
  if (snapshot.status === "loading")
    return (
      <section className={styles.snapshot} role="status" aria-busy="true">
        <h2>Course activity</h2>
        <p>Loading your academy’s course activity…</p>
      </section>
    );
  if (snapshot.status === "error")
    return (
      <section className={styles.snapshot} role="alert">
        <h2>Course activity could not load</h2>
        <p>Your workspace controls are still available below.</p>
        <button
          className="button button-secondary"
          onClick={() => {
            setSnapshot({ status: "loading" });
            setAttempt((value) => value + 1);
          }}
        >
          Try again
        </button>
      </section>
    );
  const courses = snapshot.data.programs.filter(
    (item) => item.access === "selected_tenant",
  );
  const published = courses.filter(
    (item) => item.current_published_version_id !== null,
  ).length;
  const drafts = courses.reduce((sum, item) => sum + item.draft_count, 0);
  return (
    <section
      className={styles.snapshot}
      aria-labelledby="course-activity-title"
    >
      <div className={styles.sectionHeading}>
        <h2 id="course-activity-title">Course activity</h2>
        <Link href="/studio/programs">
          Manage courses <ArrowUpRight size={15} aria-hidden="true" />
        </Link>
      </div>
      <dl className={styles.metrics}>
        <div>
          <dt>Academy courses</dt>
          <dd>{courses.length}</dd>
        </div>
        <div>
          <dt>Published courses</dt>
          <dd>{published}</dd>
        </div>
        <div>
          <dt>Draft versions</dt>
          <dd>{drafts}</dd>
        </div>
      </dl>
      {courses.length > 0 ? (
        <div className={styles.publication}>
          <div
            className={styles.track}
            role="img"
            aria-label={`${published} of ${courses.length} listed academy courses have a published version`}
          >
            <span style={{ width: `${(published / courses.length) * 100}%` }} />
          </div>
          <p>
            {published} published · {courses.length - published} without a
            published version
          </p>
        </div>
      ) : (
        <p>Create your first course to begin building your academy.</p>
      )}
      {snapshot.data.truncated && (
        <p className={styles.note}>
          These counts cover the current course list. Open Courses to explore
          the full catalogue.
        </p>
      )}
    </section>
  );
}

export function AdminDashboard() {
  const state = useAdminSession();
  const studio = canBrowseStudio(state);
  const sales = canManageSalesXray(state);
  const controls = [
    {
      title: "People",
      text: "Find academy members and manage their course access.",
      href: "/people",
      icon: UsersRound,
      allowed: canUseAdminPermission(state, "learner_diagnose"),
    },
    {
      title: "Academy Studio",
      text: "Edit lessons, add videos and publish your courses.",
      href: "/studio/programs",
      icon: BookOpen,
      allowed: studio,
    },
    {
      title: "Sales Xray",
      text: "See analysis setup and open your conversation controls.",
      href: "/sales-xray",
      icon: MessagesSquare,
      allowed: sales,
    },
    {
      title: "Review workspace",
      text: "Invite reviewers, assign calls and read their feedback.",
      href: "/sales-xray/review",
      icon: ClipboardCheck,
      allowed: sales,
    },
    {
      title: "Provider settings",
      text: "Manage your configured providers and analysis routes.",
      href: "/sales-xray/settings",
      icon: Settings2,
      allowed: sales,
    },
    {
      title: "Learning operations",
      text: "Inspect pending work and recover interrupted jobs.",
      href: "/learning-operations",
      icon: Gauge,
      allowed:
        canUseAdminPermission(state, "job_retry") ||
        canUseAdminPermission(state, "recovery_reconcile"),
    },
  ].filter((item) => item.allowed);
  return (
    <div className={styles.dashboard}>
      {studio && state.status === "ready" && (
        <CourseSnapshot
          key={`${state.session.sessionId}:${state.session.tenantId}`}
          tenantId={state.session.tenantId}
        />
      )}
      <section aria-labelledby="workspace-controls-title">
        <div className={styles.sectionHeading}>
          <div>
            <h2 id="workspace-controls-title">Your workspace</h2>
            <p>Choose what you want to work on.</p>
          </div>
        </div>
        <div className={styles.controlGrid}>
          {controls.map(({ title, text, href, icon: Icon }) => (
            <Link className={styles.control} href={href} key={href}>
              <span className={styles.controlIcon}>
                <Icon size={22} aria-hidden="true" />
              </span>
              <ArrowUpRight
                className={styles.arrow}
                size={19}
                aria-hidden="true"
              />
              <h3>{title}</h3>
              <p>{text}</p>
              <span className={styles.open}>Open {title.toLowerCase()}</span>
            </Link>
          ))}
        </div>
        {controls.length === 0 && (
          <p>No workspace controls are assigned to this account yet.</p>
        )}
      </section>
    </div>
  );
}
