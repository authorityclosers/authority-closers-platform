"use client";

import { useEffect, useState } from "react";

import {
  type CommunityDiscoveryResponse,
  type CommunityPublicProfile,
  type LearnerApi,
} from "../lib/learner-api";
import { userFacingRequestError } from "../lib/user-facing-error";
import styles from "./community-discovery.module.css";

type DiscoveryApi = Pick<
  LearnerApi,
  | "communityDiscovery"
  | "setCommunityDiscovery"
  | "communitySearch"
  | "communityPublicProfile"
  | "communityConnections"
  | "requestCommunityConnection"
  | "respondCommunityConnection"
  | "removeCommunityConnection"
  | "blockCommunityLearner"
  | "reportCommunityLearner"
>;

export function CommunityDiscovery({ api }: { api: LearnerApi }) {
  const discoveryApi = api as LearnerApi & Partial<DiscoveryApi>;
  const [discovery, setDiscovery] = useState<CommunityDiscoveryResponse | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CommunityPublicProfile[]>([]);
  const [connections, setConnections] = useState<Array<{ username: string; state: "pending" | "accepted" | "declined" | "removed"; incoming: boolean }>>([]);
  const [viewedProfile, setViewedProfile] = useState<CommunityPublicProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!discoveryApi.communityDiscovery) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    void discoveryApi
      .communityDiscovery({ signal: controller.signal })
      .then(setDiscovery)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setMessage(userFacingRequestError(error, "Community settings couldn’t load."));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [discoveryApi.communityDiscovery]);

  useEffect(() => {
    if (!discoveryApi.communityConnections) return;
    const controller = new AbortController();
    void discoveryApi
      .communityConnections({ signal: controller.signal })
      .then((response) => setConnections(response.items))
      .catch(() => {
        // Search and the explicit discovery setting remain usable if this
        // optional list is unavailable.
      });
    return () => controller.abort();
  }, [discoveryApi.communityConnections]);

  if (!discoveryApi.communityDiscovery) return null;
  if (loading) return <section className={styles.card} aria-busy="true">Loading learner discovery…</section>;

  async function saveDiscovery() {
    if (!discovery || !discoveryApi.setCommunityDiscovery) return;
    setBusy(true);
    setMessage(null);
    try {
      setDiscovery(
        await discoveryApi.setCommunityDiscovery(
          !discovery.discoverable,
          discovery.public_display_name,
          discovery.avatar_asset_id,
          discovery.revision,
        ),
      );
      setMessage(discovery.discoverable ? "Your profile is private again." : "You can now be found by username in this academy.");
      setResults([]);
    } catch (error) {
      setMessage(userFacingRequestError(error, "Community settings couldn’t be saved."));
    } finally {
      setBusy(false);
    }
  }

  async function search() {
    if (!discoveryApi.communitySearch || query.trim().length < 3) return;
    setBusy(true);
    setMessage(null);
    try {
      setResults((await discoveryApi.communitySearch(query.trim(), 10)).items);
    } catch (error) {
      setMessage(userFacingRequestError(error, "Learner search couldn’t load."));
    } finally {
      setBusy(false);
    }
  }

  async function request(username: string) {
    if (!discoveryApi.requestCommunityConnection) return;
    setBusy(true);
    setMessage(null);
    try {
      const response = await discoveryApi.requestCommunityConnection(username);
      setResults((current) =>
        current.map((item) =>
          item.username === username ? { ...item, connection_state: response.state } : item,
        ),
      );
      setConnections((current) =>
        current.map((item) =>
          item.username === username ? { ...item, state: response.state } : item,
        ),
      );
      setMessage(`Connection request sent to @${username}.`);
    } catch (error) {
      setMessage(userFacingRequestError(error, "Connection request couldn’t be sent."));
    } finally {
      setBusy(false);
    }
  }

  async function viewProfile(username: string) {
    if (!discoveryApi.communityPublicProfile) return;
    setBusy(true);
    setMessage(null);
    try {
      setViewedProfile(await discoveryApi.communityPublicProfile(username));
    } catch (error) {
      setMessage(userFacingRequestError(error, "That learner profile couldn’t load."));
    } finally {
      setBusy(false);
    }
  }

  async function respond(username: string, action: "accept" | "decline") {
    if (!discoveryApi.respondCommunityConnection) return;
    setBusy(true);
    setMessage(null);
    try {
      const response = await discoveryApi.respondCommunityConnection(username, action);
      setResults((current) =>
        current.map((item) =>
          item.username === username ? { ...item, connection_state: response.state, connection_incoming: true } : item,
        ),
      );
      setViewedProfile((current) => current?.username === username ? { ...current, connection_state: response.state, connection_incoming: true } : current);
      setMessage(action === "accept" ? `You are now connected with @${username}.` : `Request from @${username} declined.`);
    } catch (error) {
      setMessage(userFacingRequestError(error, "That connection action couldn’t be completed."));
    } finally {
      setBusy(false);
    }
  }

  async function remove(username: string) {
    if (!discoveryApi.removeCommunityConnection) return;
    setBusy(true);
    setMessage(null);
    try {
      await discoveryApi.removeCommunityConnection(username);
      setResults((current) => current.map((item) => item.username === username ? { ...item, connection_state: "removed" } : item));
      setConnections((current) => current.filter((item) => item.username !== username));
      setViewedProfile((current) => current?.username === username ? { ...current, connection_state: "removed" } : current);
      setMessage(`Connection with @${username} removed.`);
    } catch (error) {
      setMessage(userFacingRequestError(error, "That connection couldn’t be removed."));
    } finally {
      setBusy(false);
    }
  }

  async function block(username: string) {
    if (!discoveryApi.blockCommunityLearner) return;
    setBusy(true);
    setMessage(null);
    try {
      await discoveryApi.blockCommunityLearner(username);
      setResults((current) => current.filter((item) => item.username !== username));
      setConnections((current) => current.filter((item) => item.username !== username));
      setViewedProfile(null);
      setMessage(`@${username} is blocked in this academy.`);
    } catch (error) {
      setMessage(userFacingRequestError(error, "That learner couldn’t be blocked."));
    } finally {
      setBusy(false);
    }
  }

  async function report(username: string) {
    if (!discoveryApi.reportCommunityLearner) return;
    setBusy(true);
    setMessage(null);
    try {
      await discoveryApi.reportCommunityLearner(username, "other");
      setMessage(`Thanks. Your report about @${username} was recorded.`);
    } catch (error) {
      setMessage(userFacingRequestError(error, "That report couldn’t be recorded."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={styles.card} aria-labelledby="community-discovery-title">
      <header>
        <p className={styles.eyebrow}>Academy community</p>
        <h2 id="community-discovery-title">Find fellow learners</h2>
        <p className={styles.copy}>
          Your learner profile is private until you choose to be discoverable. Search uses usernames only.
        </p>
      </header>
      {discovery ? (
        <>
          <div className={styles.preference}>
            <div>
              <strong>{discovery.discoverable ? "Discoverable by username" : "Private by default"}</strong>
              <p className={styles.muted}>
                Only your chosen display name, avatar selection, and already-public practice XP can appear.
              </p>
            </div>
            <button type="button" className={styles.button} disabled={busy || !discovery.username} onClick={() => void saveDiscovery()}>
              {discovery.discoverable ? "Make private" : "Enable discovery"}
            </button>
          </div>
          {discovery.username ? (
            <form
              className={styles.search}
              onSubmit={(event) => {
                event.preventDefault();
                void search();
              }}
            >
              <label htmlFor="community-search">Search by username</label>
              <div className={styles.searchRow}>
                <input
                  id="community-search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  minLength={3}
                  maxLength={30}
                  autoComplete="off"
                  placeholder="e.g. learner_7"
                />
                <button type="submit" className={styles.button} disabled={busy || query.trim().length < 3}>
                  Search
                </button>
              </div>
            </form>
          ) : (
            <p className={styles.muted}>Claim a username before enabling learner discovery.</p>
          )}
          {results.length ? (
            <ul className={styles.results}>
              {results.map((item) => (
                <li key={item.username}>
                  <div>
                    <strong>{item.display_name || `@${item.username}`}</strong>
                    <span className={styles.muted}>@{item.username}</span>
                    {item.practice_xp_total !== null ? <span className={styles.metric}>{item.practice_xp_total} public practice XP</span> : null}
                    {item.avatar_asset_id ? <span className={styles.metric}>Avatar selected</span> : null}
                  </div>
                  <div className={styles.actions}>
                    <button type="button" className={styles.secondaryButton} disabled={busy} onClick={() => void viewProfile(item.username)}>
                      View profile
                    </button>
                    {item.connection_state === "pending" && item.connection_incoming ? (
                      <>
                        <button type="button" className={styles.button} disabled={busy} onClick={() => void respond(item.username, "accept")}>Accept</button>
                        <button type="button" className={styles.secondaryButton} disabled={busy} onClick={() => void respond(item.username, "decline")}>Decline</button>
                      </>
                    ) : item.connection_state === "accepted" ? (
                      <>
                        <button type="button" className={styles.secondaryButton} disabled={busy} onClick={() => void remove(item.username)}>Remove</button>
                        <button type="button" className={styles.secondaryButton} disabled={busy} onClick={() => void block(item.username)}>Block</button>
                        <button type="button" className={styles.secondaryButton} disabled={busy} onClick={() => void report(item.username)}>Report</button>
                      </>
                    ) : item.connection_state === "pending" ? (
                      <button type="button" className={styles.secondaryButton} disabled={busy} onClick={() => void remove(item.username)}>Cancel</button>
                    ) : (
                      <button type="button" className={styles.button} disabled={busy} onClick={() => void request(item.username)}>Connect</button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
          {connections.length ? (
            <div className={styles.connections}>
              <strong>Your connections</strong>
              <ul className={styles.connectionList}>
                {connections.map((item) => (
                  <li key={item.username}>
                    <span>@{item.username} · {item.state === "accepted" ? "Connected" : item.incoming ? "Incoming request" : "Requested"}</span>
                    {item.incoming && item.state === "pending" ? <button type="button" className={styles.button} disabled={busy} onClick={() => void respond(item.username, "accept")}>Accept</button> : null}
                    {item.state === "accepted" ? <button type="button" className={styles.secondaryButton} disabled={busy} onClick={() => void remove(item.username)}>Remove</button> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {viewedProfile ? (
            <aside className={styles.viewer} aria-label={`Profile for @${viewedProfile.username}`}>
              <div>
                <strong>{viewedProfile.display_name || `@${viewedProfile.username}`}</strong>
                <span className={styles.muted}>@{viewedProfile.username}</span>
                {viewedProfile.avatar_asset_id ? <span className={styles.metric}>Avatar selected</span> : null}
                {viewedProfile.practice_xp_total !== null ? <span className={styles.metric}>{viewedProfile.practice_xp_total} public practice XP</span> : null}
              </div>
              <button type="button" className={styles.secondaryButton} onClick={() => setViewedProfile(null)}>Close profile</button>
            </aside>
          ) : null}
        </>
      ) : null}
      {message ? <p className={styles.notice} role="status">{message}</p> : null}
    </section>
  );
}
