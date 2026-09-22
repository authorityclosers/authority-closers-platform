"use client";

import { useEffect, useRef, useState } from "react";

type Turnstile = {
  render: (element: HTMLElement, options: Record<string, unknown>) => string;
  remove: (id: string) => void;
};
declare global {
  interface Window {
    turnstile?: Turnstile;
  }
}

/** Only the public site key reaches the browser. Tokens stay in component memory. */
export function UploadCheck({
  siteKey,
  action,
  onToken,
}: {
  siteKey: string;
  action: string;
  onToken: (token: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const callback = useRef(onToken);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    callback.current = onToken;
  }, [onToken]);
  useEffect(() => {
    let disposed = false;
    let id: string | undefined;
    let script: HTMLScriptElement | undefined;
    let tokenReceived = false;
    const render = () => {
      if (disposed || !container.current || !window.turnstile) return;
      id = window.turnstile.render(container.current, {
        sitekey: siteKey,
        action,
        theme: "light",
        size: "flexible",
        "response-field": false,
        callback: (token: string) => {
          if (disposed) return;
          tokenReceived = token.length > 0;
          setError(false);
          callback.current(token);
        },
        "expired-callback": () => {
          if (!disposed) {
            tokenReceived = false;
            callback.current("");
          }
        },
        "error-callback": () => {
          if (disposed) return;
          tokenReceived = false;
          callback.current("");
          setError(true);
        },
      });
    };
    const failed = () => {
      if (!disposed) {
        callback.current("");
        setError(true);
      }
    };
    if (window.turnstile) render();
    else {
      script = document.createElement("script");
      script.src =
        "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      script.async = true;
      script.addEventListener("load", render);
      script.addEventListener("error", failed);
      document.head.appendChild(script);
    }
    const timeout = setTimeout(() => {
      // A rendered iframe is not proof that Turnstile returned a token. If a
      // managed challenge stalls, give the user a visible retry instead of
      // leaving the Analyse button disabled indefinitely.
      if (!tokenReceived) failed();
    }, 20000);
    return () => {
      disposed = true;
      clearTimeout(timeout);
      if (id) window.turnstile?.remove(id);
      if (script) {
        script.removeEventListener("load", render);
        script.removeEventListener("error", failed);
        script.remove();
      }
      callback.current("");
    };
  }, [siteKey, action, attempt]);
  return (
    <div>
      <div ref={container} aria-label="Private upload verification" />
      {error && (
        <p role="alert">
          The upload check could not load. Check your connection.{" "}
          <button
            type="button"
            className="text-button"
            onClick={() => {
              setError(false);
              setAttempt((value) => value + 1);
            }}
          >
            Retry check
          </button>
        </p>
      )}
    </div>
  );
}
