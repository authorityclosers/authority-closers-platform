"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import {
  ApiError,
  createLearnerApi,
  isAbortError,
  type CommunityLeaderboardResponse,
  type CommunityProfileResponse,
  type LearnerApi,
} from "../lib/learner-api";
import { ROUTES } from "../lib/routes";
import styles from "./community-identity-card.module.css";

const defaultApi = createLearnerApi();
export const COMMUNITY_REQUEST_TIMEOUT_MS = 10_000;

class CommunityRequestTimeout extends Error {}

async function boundedRequest<T>(
  parent: AbortSignal,
  request: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  let cancel = () => {};
  let timeout: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_, reject) => {
    cancel = () => {
      controller.abort();
      reject(new DOMException("Request cancelled", "AbortError"));
    };
    parent.addEventListener("abort", cancel, { once: true });
    timeout = setTimeout(() => {
      reject(new CommunityRequestTimeout());
      controller.abort();
    }, COMMUNITY_REQUEST_TIMEOUT_MS);
    if (parent.aborted) cancel();
  });
  try {
    return await Promise.race([
      deadline,
      Promise.resolve().then(() => {
        controller.signal.throwIfAborted();
        return request(controller.signal);
      }),
    ]);
  } finally {
    clearTimeout(timeout);
    parent.removeEventListener("abort", cancel);
  }
}

function message(error: unknown, fallback: string): string {
  if (error instanceof CommunityRequestTimeout)
    return "The connection took too long. Refresh to check the latest saved state.";
  if (!(error instanceof ApiError)) return fallback;
  if (error.code === "username_unavailable")
    return "That username is already taken. Try another name.";
  if (error.code === "username_reserved")
    return "That username is reserved. Choose a name that does not suggest an official account.";
  if (error.code === "username_already_claimed")
    return "You already have an academy username. Refresh to see it.";
  if (error.status === 409)
    return "That choice could not be saved. Refresh and try again.";
  if (error.status === 422) {
    return "Use 3–30 lowercase letters, numbers, or single underscores, starting with a letter.";
  }
  if (error.status === 401)
    return "Your session expired. Sign in again before saving.";
  return fallback;
}

export function CommunityIdentityCard({
  api = defaultApi,
}: {
  api?: LearnerApi;
}) {
  const [contextApi, setContextApi] = useState(() => api);
  const [profile, setProfile] = useState<CommunityProfileResponse | null>(null);
  const [leaderboard, setLeaderboard] =
    useState<CommunityLeaderboardResponse | null>(null);
  const [username, setUsername] = useState("");
  const [optedIn, setOptedIn] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [leaderboardError, setLeaderboardError] = useState<string | null>(null);
  const [requiresSignIn, setRequiresSignIn] = useState(false);
  const [requiresRefresh, setRequiresRefresh] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const errorRef = useRef<HTMLParagraphElement>(null);
  const mountedRef = useRef(false);
  const generationRef = useRef(0);
  const loadAbortRef = useRef<AbortController | null>(null);
  const operationAbortRef = useRef<AbortController | null>(null);
  const leaderboardAbortRef = useRef<AbortController | null>(null);
  const busyRef = useRef(false);
  const leaderboardGenerationRef = useRef(0);

  function isCurrent(generation: number, signal: AbortSignal): boolean {
    return (
      mountedRef.current &&
      generationRef.current === generation &&
      !signal.aborted
    );
  }

  function load(generation: number, signal: AbortSignal) {
    setLoading(true);
    setError(null);
    setLeaderboardError(null);
    setRequiresSignIn(false);
    // Optional rankings must not delay identity, nor overwrite a later
    // participation refresh when an older request finally returns.
    const leaderboardGeneration = ++leaderboardGenerationRef.current;
    void Promise.resolve()
      .then(() =>
        boundedRequest(signal, (requestSignal) =>
          api.communityProfile({ signal: requestSignal }),
        ),
      )
      .then(
        (next) => {
          if (!isCurrent(generation, signal)) return;
          setProfile(next);
          setOptedIn(next.leaderboard_opted_in);
          setLoading(false);
          setRequiresRefresh(false);
        },
        (reason: unknown) => {
          if (!isCurrent(generation, signal) || isAbortError(reason)) return;
          setRequiresSignIn(
            reason instanceof ApiError && reason.status === 401,
          );
          setError(
            message(reason, "Community identity could not load. Try again."),
          );
          setLoading(false);
        },
      );
    void Promise.resolve()
      .then(() =>
        boundedRequest(signal, (requestSignal) =>
          api.communityLeaderboard(25, undefined, { signal: requestSignal }),
        ),
      )
      .then(
        (next) => {
          if (
            isCurrent(generation, signal) &&
            leaderboardGeneration === leaderboardGenerationRef.current
          ) {
            setLeaderboard(next);
          }
        },
        (reason: unknown) => {
          if (
            !isCurrent(generation, signal) ||
            leaderboardGeneration !== leaderboardGenerationRef.current ||
            isAbortError(reason)
          )
            return;
          setLeaderboard(null);
          setLeaderboardError(
            "The leaderboard could not load. You can still manage your academy identity.",
          );
        },
      );
  }

  function startLoad() {
    if (busyRef.current) return;
    operationAbortRef.current?.abort();
    leaderboardAbortRef.current?.abort();
    busyRef.current = false;
    setSaving(false);
    loadAbortRef.current?.abort();
    const controller = new AbortController();
    loadAbortRef.current = controller;
    const generation = ++generationRef.current;
    void load(generation, controller.signal);
  }

  function startOperation(): {
    controller: AbortController;
    generation: number;
  } | null {
    if (
      busyRef.current ||
      loading ||
      requiresSignIn ||
      requiresRefresh ||
      contextApi !== api
    )
      return null;
    busyRef.current = true;
    operationAbortRef.current?.abort();
    const controller = new AbortController();
    operationAbortRef.current = controller;
    return { controller, generation: generationRef.current };
  }

  function finishOperation(controller: AbortController, generation: number) {
    if (operationAbortRef.current === controller) {
      operationAbortRef.current = null;
      busyRef.current = false;
    }
    if (isCurrent(generation, controller.signal)) setSaving(false);
  }

  useEffect(() => {
    let active = true;
    mountedRef.current = true;
    queueMicrotask(() => {
      if (active) {
        setContextApi(() => api);
        setProfile(null);
        setLeaderboard(null);
        setUsername("");
        setSuccess(null);
        startLoad();
      }
    });
    return () => {
      active = false;
      mountedRef.current = false;
      generationRef.current += 1;
      loadAbortRef.current?.abort();
      operationAbortRef.current?.abort();
      leaderboardAbortRef.current?.abort();
      busyRef.current = false;
    };
    // The API is a stable dependency supplied by the route or a test fixture.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  async function claim() {
    if (!username.trim()) return;
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      setError("Reconnect before claiming a username.");
      return;
    }
    const operation = startOperation();
    if (!operation) return;
    const { controller, generation } = operation;
    setSaving(true);
    setError(null);
    setRequiresSignIn(false);
    setSuccess(null);
    try {
      const next = await boundedRequest(controller.signal, (signal) =>
        api.claimUsername(username, signal),
      );
      if (!isCurrent(generation, controller.signal)) return;
      setProfile(next);
      setOptedIn(next.leaderboard_opted_in);
      setUsername("");
      setSuccess(`Username @${next.username} claimed.`);
    } catch (claimError) {
      if (isAbortError(claimError) || !isCurrent(generation, controller.signal))
        return;
      setRequiresSignIn(
        claimError instanceof ApiError && claimError.status === 401,
      );
      setRequiresRefresh(claimError instanceof CommunityRequestTimeout);
      setError(
        message(claimError, "Username could not be claimed. Try again."),
      );
    } finally {
      finishOperation(controller, generation);
    }
  }

  async function saveParticipation() {
    if (!profile?.username || optedIn === profile.leaderboard_opted_in) return;
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      setError("Reconnect before changing leaderboard participation.");
      return;
    }
    const operation = startOperation();
    if (!operation) return;
    const { controller, generation } = operation;
    const previousProfile = profile;
    const leaderboardGeneration = ++leaderboardGenerationRef.current;
    leaderboardAbortRef.current?.abort();
    setSaving(true);
    setError(null);
    setRequiresSignIn(false);
    setSuccess(null);
    try {
      const next = await boundedRequest(controller.signal, (signal) =>
        api.setLeaderboardOptIn(optedIn, profile.revision, signal),
      );
      if (!isCurrent(generation, controller.signal)) return;
      setProfile(next);
      setOptedIn(next.leaderboard_opted_in);
      setSuccess(
        next.leaderboard_opted_in
          ? "You joined the academy leaderboard."
          : "You left the academy leaderboard. Your learning progress is unchanged.",
      );
    } catch (saveError) {
      if (isAbortError(saveError) || !isCurrent(generation, controller.signal))
        return;
      setOptedIn(previousProfile.leaderboard_opted_in);
      setRequiresSignIn(
        saveError instanceof ApiError && saveError.status === 401,
      );
      setRequiresRefresh(saveError instanceof CommunityRequestTimeout);
      setError(
        message(
          saveError,
          "Leaderboard participation could not be saved. Try again.",
        ),
      );
      finishOperation(controller, generation);
      return;
    }
    // The canonical save is finished. Optional ranking refresh must not lock
    // the learner out of withdrawing again while the network is slow.
    finishOperation(controller, generation);
    leaderboardAbortRef.current = controller;
    try {
      const refreshed = await boundedRequest(controller.signal, (signal) =>
        api.communityLeaderboard(25, undefined, { signal }),
      );
      if (
        !isCurrent(generation, controller.signal) ||
        leaderboardGeneration !== leaderboardGenerationRef.current
      )
        return;
      setLeaderboard(refreshed);
      setLeaderboardError(null);
    } catch (refreshError) {
      if (
        isAbortError(refreshError) ||
        !isCurrent(generation, controller.signal) ||
        leaderboardGeneration !== leaderboardGenerationRef.current
      )
        return;
      setLeaderboard(null);
      setRequiresSignIn(
        refreshError instanceof ApiError && refreshError.status === 401,
      );
      setError(
        message(
          refreshError,
          "Participation was saved, but the leaderboard could not refresh. Try again.",
        ),
      );
    } finally {
      if (leaderboardAbortRef.current === controller)
        leaderboardAbortRef.current = null;
    }
  }

  if (contextApi !== api)
    return <p role="status">Loading community identity…</p>;

  return (
    <section className={styles.card} aria-labelledby="community-identity-title">
      <header className={styles.heading}>
        <h2 id="community-identity-title">Academy username</h2>
        <p>
          Choose a public academy name. It is not your sign-in ID and never
          exposes your email.
        </p>
      </header>

      {loading ? <p role="status">Loading community identity…</p> : null}
      {error ? (
        <div>
          <p className={styles.error} role="alert" tabIndex={-1} ref={errorRef}>
            {error}
          </p>
          {requiresSignIn ? (
            <Link className={styles.button} href={ROUTES.sessionExpired}>
              Sign in again
            </Link>
          ) : profile ? (
            <button className={styles.button} type="button" onClick={startLoad}>
              Refresh community identity
            </button>
          ) : null}
        </div>
      ) : null}
      {success ? (
        <p className={styles.status} role="status" aria-live="polite">
          {success}
        </p>
      ) : null}

      {!loading && !profile ? (
        <button className={styles.button} type="button" onClick={startLoad}>
          Retry
        </button>
      ) : null}

      {leaderboardError ? (
        <div>
          <p className={styles.error} role="status">
            {leaderboardError}
          </p>
          <button
            className={styles.button}
            type="button"
            onClick={startLoad}
            disabled={saving}
          >
            Retry leaderboard
          </button>
        </div>
      ) : null}

      {profile && !profile.username ? (
        <form
          className={styles.form}
          onSubmit={(event) => {
            event.preventDefault();
            void claim();
          }}
        >
          <label className={styles.label} htmlFor="academy-username">
            Username
          </label>
          <div className={styles.claimRow}>
            <input
              className={styles.input}
              id="academy-username"
              name="academy_username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              minLength={3}
              maxLength={30}
              pattern="[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*"
              autoCapitalize="none"
              autoCorrect="off"
              autoComplete="off"
              spellCheck={false}
              required
              disabled={saving || loading || requiresSignIn || requiresRefresh}
            />
            <button
              className={styles.button}
              type="submit"
              disabled={
                saving ||
                loading ||
                requiresSignIn ||
                requiresRefresh ||
                !username.trim()
              }
            >
              {saving ? "Claiming…" : "Claim username"}
            </button>
          </div>
          <p className={styles.help}>
            3–30 letters, numbers, or single underscores, starting with a
            letter. Choose carefully: usernames are fixed in this release.
          </p>
        </form>
      ) : null}

      {profile?.username ? (
        <>
          <div className={styles.claimed}>
            <strong>@{profile.username}</strong>
            <span>Claimed for this academy · fixed in this release</span>
          </div>
          <div className={styles.preference}>
            <label className={styles.choice}>
              <input
                className={styles.checkbox}
                type="checkbox"
                checked={optedIn}
                onChange={(event) => setOptedIn(event.target.checked)}
                disabled={
                  saving || loading || requiresSignIn || requiresRefresh
                }
              />
              <span>
                <strong>Join the academy leaderboard</strong>
                <span>
                  Show only your username and confirmed all-time practice XP.
                  Equal XP shares the same rank. This never changes course
                  access, progress, or scoring.
                </span>
              </span>
            </label>
            <button
              className={styles.button}
              type="button"
              onClick={() => void saveParticipation()}
              disabled={
                saving ||
                loading ||
                requiresSignIn ||
                requiresRefresh ||
                optedIn === profile.leaderboard_opted_in
              }
            >
              {saving ? "Saving…" : "Save participation"}
            </button>
            <p className={styles.privacy}>
              {profile.leaderboard_opted_in
                ? "You're on the academy leaderboard."
                : "You're not on the academy leaderboard."}{" "}
              Save to update your choice. Leaving never removes your earned XP.
            </p>
          </div>
        </>
      ) : null}

      {leaderboard ? (
        <div className={styles.leaderboard}>
          <h3>{leaderboard.policy.label}</h3>
          {leaderboard.items.length === 0 ? (
            <p className={styles.empty}>
              No opted-in learners with confirmed practice XP are listed yet.
            </p>
          ) : (
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
                {leaderboard.items.map((item) => (
                  <tr
                    className={
                      item.is_current_learner ? styles.current : undefined
                    }
                    key={item.username}
                  >
                    <td>{item.rank}</td>
                    <th scope="row">
                      @{item.username}
                      {item.is_current_learner ? (
                        <span className="sr-only"> (you)</span>
                      ) : null}
                    </th>
                    <td>{item.xp_total.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {leaderboard.next_cursor ? (
            <p className={styles.privacy}>
              Showing the first 25 learners. More opted-in learners are
              available.
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
