"use client";

import { useEffect } from "react";
import {
  AUTH_COMPLETE_MESSAGE,
  validAuthFlow,
  type AuthCompletionResult,
} from "../../account-auth-client";

export function AuthCompleteClient({
  flow,
  result,
}: {
  flow: string | null;
  result: AuthCompletionResult | null;
}) {
  useEffect(() => {
    if (!validAuthFlow(flow) || !result) return;
    if (window.opener && window.opener !== window) {
      try {
        window.opener.postMessage(
          { type: AUTH_COMPLETE_MESSAGE, flow, auth_result: result },
          window.location.origin,
        );
      } catch {
        // The opener can still inspect this exact callback URL manually.
      }
    }
  }, [flow, result]);

  const message =
    !validAuthFlow(flow) || !result
      ? "Sign-in could not be confirmed. Return to the Sales Xray window and try again."
      : result === "success"
        ? "Return to the Sales Xray window to finish sign-in."
        : "Sign-in needs another step. Return to the Sales Xray window for details.";

  return (
    <main
      className="xray-app simple-app"
      style={{
        minHeight: "100dvh",
        display: "grid",
        placeItems: "center",
        padding: 24,
        textAlign: "center",
        background: "var(--canvas)",
      }}
    >
      <div>
        <h1 style={{ marginBottom: 8, fontSize: 24 }}>Sales Xray sign-in</h1>
        <p style={{ color: "var(--muted)" }}>{message}</p>
        <button
          type="button"
          className="secondary-button"
          onClick={() => window.close()}
        >
          Close this window
        </button>
      </div>
    </main>
  );
}
