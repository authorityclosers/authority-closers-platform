"use client";

import { useState } from "react";
import { ProspectsListView } from "../../../prospects/prospects-list-view";
import { ProspectDetailView } from "../../../prospects/prospect-detail-view";
import { WorkspaceAccessContext } from "../../../workspace-access";
import styles from "../../../prospects/prospects.module.css";

const context = {
  personId: "00000000-0000-0000-0000-000000000001",
  tenantId: "00000000-0000-0000-0000-000000000002",
  sessionId: "00000000-0000-0000-0000-000000000003",
};

/** Only the bounded browser proof supplies invented rows at the API port. */
export function ProspectLibraryFixture() {
  const [mode, setMode] = useState<
    "ready" | "unauthenticated" | "loading" | "unavailable"
  >("ready");
  const [profile, setProfile] = useState(false);
  const [signInRequested, setSignInRequested] = useState(false);
  return (
    <>
      <div role="group" aria-label="Fictional prospect access states">
        <button
          type="button"
          className={styles.filterBtn}
          onClick={() => {
            setProfile(false);
            setMode("ready");
          }}
        >
          Preview list
        </button>
        <button
          type="button"
          className={styles.filterBtn}
          onClick={() => {
            setProfile(true);
            setMode("ready");
          }}
        >
          Preview profile
        </button>
        <button
          type="button"
          className={styles.filterBtn}
          onClick={() => {
            setSignInRequested(false);
            setMode("unauthenticated");
          }}
        >
          Signed out
        </button>
        <button
          type="button"
          className={styles.filterBtn}
          onClick={() => setMode("loading")}
        >
          Checking access
        </button>
        <button
          type="button"
          className={styles.filterBtn}
          onClick={() => setMode("unavailable")}
        >
          Workspace unavailable
        </button>
      </div>
      {signInRequested && <span role="status">Sign-in requested</span>}
      <WorkspaceAccessContext.Provider
        value={{
          status: mode,
          authenticated: mode === "loading" ? null : mode !== "unauthenticated",
          context: mode === "ready" ? context : null,
          retry: () => setMode("ready"),
          requestAccountSignIn: () => setSignInRequested(true),
        }}
      >
        {profile ? (
          <ProspectDetailView prospectId="00000000-0000-0000-0000-000000000004" />
        ) : (
          <ProspectsListView />
        )}
      </WorkspaceAccessContext.Provider>
    </>
  );
}
