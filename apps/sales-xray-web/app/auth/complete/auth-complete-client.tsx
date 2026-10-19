"use client";

import { useEffect, useState } from "react";
import {
  AUTH_COMPLETE_MESSAGE,
  forgetRedirectSignIn,
  keepSignInResult,
  readCanonicalSession,
  readGoogleCompletion,
  readRedirectSignIn,
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
  const [returning, setReturning] = useState(false);

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
      return;
    }
    // A full-page sign-in (the sign-in window was blocked): go back to the
    // page it started from. Only a receipt for this flow and this session
    // counts as signed in; the sign-in screen there reads the session again.
    // Read now, forget once used: development runs this effect twice.
    const started = readRedirectSignIn(flow);
    if (!started && result !== "success") return;
    const returnTo = started?.returnTo ?? "/";
    const provider = started?.provider ?? "google";
    if (result !== "success") {
      forgetRedirectSignIn();
      keepSignInResult(result, provider);
      window.location.replace(returnTo);
      return;
    }
    const request = new AbortController();
    void Promise.resolve().then(() => setReturning(true));
    readGoogleCompletion(flow, request.signal)
      .then(() => readCanonicalSession(request.signal))
      .then(
        () => {
          if (!request.signal.aborted) keepSignInResult("success", provider);
        },
        () => {
          if (!request.signal.aborted) keepSignInResult("failed", provider);
        },
      )
      .finally(() => {
        if (request.signal.aborted) return;
        forgetRedirectSignIn();
        window.location.replace(returnTo);
      });
    return () => request.abort();
  }, [flow, result]);

  const message = returning
    ? "Signing you in…"
    : !validAuthFlow(flow) || !result
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
        <p style={{ color: "var(--muted)" }} role="status">
          {message}
        </p>
        {returning ? null : (
          <button
            type="button"
            className="secondary-button"
            onClick={() => window.close()}
          >
            Close this window
          </button>
        )}
      </div>
    </main>
  );
}
