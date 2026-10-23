"use client";

/**
 * Review (owner, 19 Oct): the reviewer's queue of real Reports, their figures,
 * and the one-by-one review of a call. The open call lives in the address
 * hash (#call=<id>), like a lead on /leads, so an alert or a link opens it.
 */

import { BarChart3, ClipboardCheck } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import { ReviewAlertsCard } from "./review-alerts-card";
import { markReviewSeen, publishReviewBadge } from "./review-badge";
import {
  callName,
  percent,
  readMetrics,
  readQueue,
  ReviewError,
  type Metrics,
  type Queue,
} from "./review-client";
import { ReviewFlow } from "./review-flow";
import styles from "./review.module.css";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function hashCall(): string | null {
  if (typeof window === "undefined") return null;
  const match = /(?:^#|&)call=([^&]+)/.exec(window.location.hash);
  const id = match ? decodeURIComponent(match[1]) : null;
  return id && UUID.test(id) ? id : null;
}

function useHashCall(): [string | null, (id: string | null) => void] {
  const [call, setCall] = useState<string | null>(null);
  useEffect(() => {
    const sync = () => setCall(hashCall());
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  const open = useCallback((id: string | null) => {
    if (id) window.location.hash = `call=${id}`;
    else
      window.history.pushState(
        null,
        "",
        window.location.pathname + window.location.search,
      );
    setCall(id);
  }, []);
  return [call, open];
}

export function ReviewSkeleton() {
  return (
    <AcquisitionShell authenticated loading active="review">
      <div className={styles.root} aria-busy="true">
        <HomeSkeleton />
      </div>
    </AcquisitionShell>
  );
}

function HomeSkeleton() {
  return (
    <>
      <div className={styles.head}>
        <span className={styles.skeleton} style={{ width: 160, height: 26 }} />
      </div>
      <div className={styles.tiles}>
        {[0, 1, 2, 3, 4].map((i) => (
          <span key={i} className={styles.skeleton} style={{ height: 64 }} />
        ))}
      </div>
      <span className={styles.skeleton} style={{ height: 52 }} />
      {[0, 1, 2, 3].map((i) => (
        <span key={i} className={styles.skeleton} style={{ height: 56 }} />
      ))}
    </>
  );
}

export function ReviewRoute() {
  const [call, open] = useHashCall();
  const [queue, setQueue] = useState<Queue | null>(null);
  const [mine, setMine] = useState<Metrics | null>(null);
  const [problem, setProblem] = useState<ReviewError | null>(null);
  const [round, setRound] = useState(0);

  useEffect(() => {
    if (call) return;
    const controller = new AbortController();
    readQueue(controller.signal)
      .then((data) => {
        setQueue(data);
        setProblem(null);
        const waiting = data.items.filter((item) => item.state !== "done");
        const newest = waiting.reduce<string | null>(
          (latest, item) =>
            latest === null || item.assigned_at > latest
              ? item.assigned_at
              : latest,
          null,
        );
        publishReviewBadge({
          reviewer: true,
          metrics: true,
          waiting: waiting.length,
          newest_at: newest,
        });
        markReviewSeen(newest);
      })
      .catch((error: Error) => {
        if (error.name !== "AbortError") setProblem(error as ReviewError);
      });
    readMetrics(controller.signal)
      .then(setMine)
      .catch(() => undefined);
    return () => controller.abort();
  }, [call, round]);

  if (call)
    return (
      <AcquisitionShell
        authenticated
        active="review"
        pageName="Review"
        mobileFit
      >
        <ReviewFlow
          key={call}
          assignmentId={call}
          onFinished={() => {
            const next = queue?.items.find(
              (item) => item.state !== "done" && item.assignment_id !== call,
            );
            setRound((value) => value + 1);
            open(next ? next.assignment_id : null);
          }}
        />
      </AcquisitionShell>
    );

  const next = queue?.items.find((item) => item.state !== "done");
  const me = mine?.me;
  return (
    <AcquisitionShell authenticated active="review" pageName="Review">
      <div className={styles.root}>
        {problem ? (
          <div className={styles.panel}>
            <h2>
              {problem.status === 403
                ? "Review is for gold reviewers"
                : "Review didn't load"}
            </h2>
            <p className={styles.muted}>
              {problem.status === 403
                ? "Ask the AC owner to add you in Admin → Reviewers → Gold reviewers."
                : problem.message}
            </p>
            {problem.status === 403 ? null : (
              <button
                type="button"
                className={styles.navBtn}
                onClick={() => setRound((value) => value + 1)}
              >
                Try again
              </button>
            )}
          </div>
        ) : !queue ? (
          <HomeSkeleton />
        ) : (
          <>
            <div className={styles.head}>
              <div>
                <h1>Review</h1>
                <p>
                  Check the AI&apos;s Report, one line at a time. Every answer
                  is a human label in the gold set.
                </p>
              </div>
              <Link className={styles.barChip} href="/review/figures">
                <BarChart3 size={14} aria-hidden="true" /> Figures
              </Link>
            </div>
            <ReviewAlertsCard />
            <div className={styles.tiles}>
              <div className={styles.tile} data-tone="accent">
                <b>{queue.calls_left}</b>
                <span>calls waiting · {queue.lines_left} lines</span>
              </div>
              <div className={styles.tile}>
                <b>{me?.today ?? "–"}</b>
                <span>lines today</span>
              </div>
              <div className={styles.tile}>
                <b>{me?.labels ?? "–"}</b>
                <span>lines in total</span>
              </div>
              <div className={styles.tile}>
                <b>
                  {me?.median_seconds != null
                    ? `${Math.round(me.median_seconds)}s`
                    : "–"}
                </b>
                <span>per line</span>
              </div>
              <div className={styles.tile}>
                <b>{percent(me?.agreement)}</b>
                <span>you agree with the AI</span>
              </div>
            </div>
            {next ? (
              <button
                type="button"
                className={styles.start}
                onClick={() => open(next.assignment_id)}
              >
                <ClipboardCheck size={18} aria-hidden="true" />
                {next.state === "in_progress" ? "Carry on" : "Start reviewing"}
              </button>
            ) : (
              <div className={styles.panel}>
                <h2>All caught up</h2>
                <p className={styles.muted}>
                  New Reports land here by themselves when a call is analysed.
                </p>
              </div>
            )}
            {queue.items.length ? (
              <section className={styles.panel} aria-label="Calls to review">
                <h2>Calls</h2>
                <ul className={styles.list}>
                  {queue.items.map((item) => (
                    <li key={item.assignment_id}>
                      <a
                        className={styles.row}
                        href={`#call=${item.assignment_id}`}
                        onClick={(event) => {
                          event.preventDefault();
                          open(item.assignment_id);
                        }}
                      >
                        <span>
                          <b>{callName(item.recorded_at)}</b>
                          <span className={styles.muted}>
                            {" "}
                            · {item.handled}/{item.total}
                            {item.mode === "brain4_blind"
                              ? " · Blind rating"
                              : item.mode === "report"
                                ? " · Report review"
                                : ""}
                          </span>
                        </span>
                        <span
                          className={styles.pill}
                          data-tone={
                            item.state === "done"
                              ? "good"
                              : item.state === "in_progress"
                                ? "warn"
                                : "accent"
                          }
                        >
                          {item.state === "done"
                            ? "Done"
                            : item.state === "in_progress"
                              ? "Started"
                              : "New"}
                        </span>
                        <span className={styles.bar}>
                          <span
                            style={{
                              width: `${(item.handled / item.total) * 100}%`,
                            }}
                          />
                        </span>
                      </a>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </>
        )}
      </div>
    </AcquisitionShell>
  );
}
