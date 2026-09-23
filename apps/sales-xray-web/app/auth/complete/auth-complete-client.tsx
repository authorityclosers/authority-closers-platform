"use client";

import { useEffect } from "react";
import { AUTH_COMPLETE_MESSAGE, validAuthFlow } from "../../account-auth-client";

export function AuthCompleteClient({ flow }: { flow: string | null }) {
  useEffect(() => {
    if (!validAuthFlow(flow) || !window.opener || window.opener === window)
      return;
    // No token or identity leaves this page. The opener validates source,
    // origin and flow, then performs a fresh canonical session read.
    try {
      window.opener.postMessage(
        { type: AUTH_COMPLETE_MESSAGE, flow },
        window.location.origin,
      );
    } catch {
      // A closed or isolated opener can still use the manual session check.
    }
  }, [flow]);

  return (
    <main className="xray-app simple-app" style={{
      minHeight: "100dvh", display: "grid", placeItems: "center",
      padding: 24, textAlign: "center", background: "var(--canvas)",
    }}>
      <div>
        <h1 style={{ marginBottom: 8, fontSize: 24 }}>Sales Xray sign-in</h1>
        <p style={{ color: "var(--muted)" }}>
          Return to the Sales Xray window to check your sign-in.
        </p>
        <button type="button" className="secondary-button" onClick={() => window.close()}>
          Close this window
        </button>
      </div>
    </main>
  );
}
