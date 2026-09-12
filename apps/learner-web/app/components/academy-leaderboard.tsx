"use client";

import { AlertCircle, ArrowRight, RefreshCw, Trophy } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";

import {
  ApiError,
  createLearnerApi,
  isAbortError,
  type CommunityLeaderboardResponse,
  type LearnerApi,
} from "../lib/learner-api";
import { ROUTES } from "../lib/routes";
import styles from "./academy-leaderboard.module.css";

const defaultApi = createLearnerApi();
export const ACADEMY_LEADERBOARD_PAGE_SIZE = 25;
export const ACADEMY_LEADERBOARD_REQUEST_TIMEOUT_MS = 10_000;

type LeaderboardApi = Pick<LearnerApi, "communityLeaderboard">;
type LoadState = "loading" | "ready" | "error";

class LeaderboardRequestTimeout extends Error {}

function errorCopy(error: unknown): {
  title: string;
  detail: string;
  requiresSignIn: boolean;
} {
  if (error instanceof LeaderboardRequestTimeout) {
    return {
      title: "The leaderboard took too long to load",
      detail: "Retry the read when your connection is ready.",
      requiresSignIn: false,
    };
  }
  if (error instanceof ApiError && error.status === 401) {
    return {
      title: "Sign in to view your academy leaderboard",
      detail:
        "Your session has expired. Sign in again to view this private ranking.",
      requiresSignIn: true,
    };
  }
  if (error instanceof ApiError && error.status === 403) {
    return {
      title: "This leaderboard is unavailable here",
      detail:
        "The current account is not authorized to view a learner leaderboard for its selected academy.",
      requiresSignIn: false,
    };
  }
  return {
    title: "The academy leaderboard could not load",
    detail:
      "The saved ranking is unchanged. Check your connection and try again.",
    requiresSignIn: false,
  };
}

async function boundedRequest<T>(
  parent: AbortSignal,
  request: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let cancel = () => {};
  const cancelled = new Promise<never>((_, reject) => {
    cancel = () => {
      controller.abort();
      reject(new DOMException("Request cancelled", "AbortError"));
    };
    parent.addEventListener("abort", cancel, { once: true });
    if (parent.aborted) cancel();
  });
  const timedOut = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new LeaderboardRequestTimeout());
    }, ACADEMY_LEADERBOARD_REQUEST_TIMEOUT_MS);
  });
  try {
    return await Promise.race([
      cancelled,
      timedOut,
      Promise.resolve().then(() => {
        controller.signal.throwIfAborted();
        return request(controller.signal);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
    parent.removeEventListener("abort", cancel);
  }
}

export function AcademyLeaderboard({
  api = defaultApi,
}: {
  api?: LeaderboardApi;
}) {
  const [state, setState] = useState<LoadState>("loading");
  const [data, setData] = useState<CommunityLeaderboardResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState(false);
  const mountedRef = useRef(false);
  const generationRef = useRef(0);
  const requestRef = useRef<AbortController | null>(null);

  const load = useCallback(() => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    const generation = ++generationRef.current;
    setState("loading");
    setData(null);
    setError(null);
    setLoadingMore(false);
    setMoreError(false);
    void boundedRequest(controller.signal, (signal) =>
      api.communityLeaderboard(ACADEMY_LEADERBOARD_PAGE_SIZE, undefined, {
        signal,
      }),
    ).then(
      (next) => {
        if (
          mountedRef.current &&
          generationRef.current === generation &&
          !controller.signal.aborted
        ) {
          setData(next);
          setState("ready");
        }
      },
      (reason: unknown) => {
        if (
          mountedRef.current &&
          generationRef.current === generation &&
          !controller.signal.aborted &&
          !isAbortError(reason)
        ) {
          setError(reason);
          setState("error");
        }
      },
    );
  }, [api]);

  useEffect(() => {
    let active = true;
    mountedRef.current = true;
    queueMicrotask(() => {
      if (active && mountedRef.current) load();
    });
    return () => {
      active = false;
      mountedRef.current = false;
      generationRef.current += 1;
      requestRef.current?.abort();
    };
  }, [load]);

  const loadMore = useCallback(() => {
    if (!data?.next_cursor || loadingMore || state !== "ready") return;
    const cursor = data.next_cursor;
    const controller = new AbortController();
    requestRef.current?.abort();
    requestRef.current = controller;
    const generation = generationRef.current;
    setLoadingMore(true);
    setMoreError(false);
    void boundedRequest(controller.signal, (signal) =>
      api.communityLeaderboard(ACADEMY_LEADERBOARD_PAGE_SIZE, cursor, {
        signal,
      }),
    ).then(
      (next) => {
        if (
          mountedRef.current &&
          generationRef.current === generation &&
          !controller.signal.aborted
        ) {
          setData((current) =>
            current
              ? {
                  ...current,
                  items: [...current.items, ...next.items],
                  next_cursor: next.next_cursor,
                }
              : next,
          );
          setLoadingMore(false);
        }
      },
      (reason: unknown) => {
        if (
          mountedRef.current &&
          generationRef.current === generation &&
          !controller.signal.aborted &&
          !isAbortError(reason)
        ) {
          setMoreError(true);
          setLoadingMore(false);
        }
      },
    );
  }, [api, data, loadingMore, state]);

  if (state === "loading") {
    return (
      <section className={styles.surface} aria-labelledby="leaderboard-title">
        <header className={styles.header}>
          <p className={styles.eyebrow}>Academy community</p>
          <h1 id="leaderboard-title">Academy leaderboard</h1>
        </header>
        <div className={styles.state} role="status" aria-live="polite">
          <RefreshCw className={styles.spin} size={22} aria-hidden="true" />
          <p>Loading the academy leaderboard…</p>
        </div>
      </section>
    );
  }

  if (state === "error") {
    const copy = errorCopy(error);
    return (
      <section className={styles.surface} aria-labelledby="leaderboard-title">
        <header className={styles.header}>
          <p className={styles.eyebrow}>Academy community</p>
          <h1 id="leaderboard-title">Academy leaderboard</h1>
        </header>
        <div className={styles.state} role="alert" aria-live="polite">
          <AlertCircle size={22} aria-hidden="true" />
          <div>
            <h2>{copy.title}</h2>
            <p>{copy.detail}</p>
            {copy.requiresSignIn ? (
              <Link
                className={styles.primaryAction}
                href={ROUTES.sessionExpired}
              >
                Sign in again
              </Link>
            ) : (
              <button
                className={styles.secondaryAction}
                type="button"
                onClick={load}
              >
                <RefreshCw size={16} aria-hidden="true" /> Retry
              </button>
            )}
          </div>
        </div>
        <AccountLinks />
      </section>
    );
  }

  if (!data) return null;
  const isEmpty = data.items.length === 0;
  return (
    <section className={styles.surface} aria-labelledby="leaderboard-title">
      <header className={styles.header}>
        <div className={styles.titleRow}>
          <span className={styles.icon} aria-hidden="true">
            <Trophy size={24} />
          </span>
          <div>
            <p className={styles.eyebrow}>Academy community</p>
            <h1 id="leaderboard-title">Academy leaderboard</h1>
          </div>
        </div>
        <p className={styles.lede}>
          A private academy view of confirmed practice recognition. Equal XP
          shares the same rank.
        </p>
        <p className={styles.policy}>{data.policy.label}</p>
      </header>

      {isEmpty ? (
        <div className={styles.empty} role="status" aria-live="polite">
          <Trophy size={28} aria-hidden="true" />
          <h2>No leaderboard entries yet</h2>
          <p>No opted-in learners with confirmed practice XP are listed yet.</p>
          <Link className={styles.primaryAction} href={ROUTES.arcade}>
            Start practice <ArrowRight size={17} aria-hidden="true" />
          </Link>
        </div>
      ) : (
        <>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <caption className="sr-only">
                Academy leaderboard ranked by confirmed all-time practice XP
              </caption>
              <colgroup>
                <col className={styles.rankColumn} />
                <col />
                <col className={styles.xpColumn} />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">Rank</th>
                  <th scope="col">Username</th>
                  <th scope="col">Practice XP</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr
                    key={item.username}
                    data-current-learner={item.is_current_learner || undefined}
                    className={
                      item.is_current_learner ? styles.current : undefined
                    }
                  >
                    <td>{item.rank}</td>
                    <th scope="row">
                      @{item.username}
                      {item.is_current_learner ? (
                        <span className={styles.you}>You</span>
                      ) : null}
                    </th>
                    <td>{item.xp_total.toLocaleString("en-US")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.next_cursor ? (
            <div className={styles.more}>
              {moreError ? (
                <p className={styles.moreError} role="alert">
                  More learners could not load. Try again.
                </p>
              ) : null}
              <button
                className={styles.secondaryAction}
                type="button"
                onClick={loadMore}
                disabled={loadingMore}
              >
                <RefreshCw
                  size={16}
                  aria-hidden="true"
                  className={loadingMore ? styles.spin : undefined}
                />
                {loadingMore
                  ? "Loading more…"
                  : moreError
                    ? "Retry"
                    : "Show more learners"}
              </button>
            </div>
          ) : null}
        </>
      )}
      <AccountLinks />
    </section>
  );
}

function AccountLinks() {
  return (
    <footer className={styles.footer}>
      <p>
        Manage your academy username and privacy in{" "}
        <Link href={ROUTES.profile}>Profile &amp; identity</Link>. Change visual
        preferences in <Link href={ROUTES.settings}>Settings</Link>.
      </p>
    </footer>
  );
}
