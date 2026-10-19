/**
 * Connect from the Sales Xray app.
 *
 * Facebook and Google refuse their sign-in inside an app's web view, so inside
 * the app a Connect opens in the phone's own browser instead. This page keeps a
 * random verifier and asks for the sign-in address with its challenge; the app
 * opens that address in the browser; the provider comes back to Sales Xray
 * there, which redirects to the app with a sealed hand-off; the app reopens
 * this page with the hand-off in the address fragment and the page finishes the
 * Connect on its own session with the verifier (lead_desk/connectors/app_return.py).
 *
 * In a browser none of this runs: Connect stays an ordinary link.
 */

import { useCallback, useEffect, useRef } from "react";

import { inPhoneApp, openConnect, phoneStatus } from "./native-phone";

export type ConnectProvider = "meta" | "google" | "whatsapp" | "messaging";

/** What happened: the server's word ("connected", "nopages", "cancelled", …)
 * and, when it said more, its own words. */
export type ConnectOutcome = { result: string; message?: string };

const STARTS: Record<ConnectProvider, string> = {
  meta: "/v1/lead-desk/meta/connect",
  google: "/v1/lead-desk/google/connect",
  whatsapp: "/v1/lead-desk/whatsapp/start",
  messaging: "/v1/lead-desk/messaging/connect",
};
const FINISHES: Record<ConnectProvider, string> = {
  meta: "/v1/lead-desk/meta/app-complete",
  google: "/v1/lead-desk/google/app-complete",
  whatsapp: "/v1/lead-desk/whatsapp/app-complete",
  messaging: "/v1/lead-desk/messaging/app-complete",
};
const KEPT = "sx.appConnect";
/** As long as the server keeps the hand-off. */
const MAX_AGE_MS = 10 * 60 * 1000;
const HANDOFF = /^[A-Za-z0-9_-]{20,8192}$/;
const WORD = /^[a-z_]{1,32}$/;

export const UPDATE_APP =
  "Update the Sales Xray app to connect from your phone, or connect from a computer.";
const TOO_LONG = "That took too long. Connect again.";

function b64url(bytes: Uint8Array): string {
  let text = "";
  bytes.forEach((byte) => {
    text += String.fromCharCode(byte);
  });
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function newVerifier(): string {
  const bytes = new Uint8Array(48);
  crypto.getRandomValues(bytes);
  return b64url(bytes);
}

/** The challenge a verifier answers: unpadded base64url of its SHA-256. */
export async function challengeOf(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(verifier),
  );
  return b64url(new Uint8Array(digest));
}

function keep(provider: ConnectProvider, verifier: string): boolean {
  try {
    window.localStorage.setItem(
      KEPT,
      JSON.stringify({ provider, verifier, at: Date.now() }),
    );
    return true;
  } catch {
    return false;
  }
}

/** The verifier kept for this provider, once: it is gone after reading. */
function take(provider: ConnectProvider): string | null {
  try {
    const raw = window.localStorage.getItem(KEPT);
    window.localStorage.removeItem(KEPT);
    const kept = JSON.parse(raw ?? "null") as {
      provider?: unknown;
      verifier?: unknown;
      at?: unknown;
    } | null;
    if (
      !kept ||
      kept.provider !== provider ||
      typeof kept.verifier !== "string" ||
      typeof kept.at !== "number" ||
      Date.now() - kept.at > MAX_AGE_MS
    )
      return null;
    return kept.verifier;
  } catch {
    return null;
  }
}

/** The app's return in the address fragment, when it is for this provider. */
export function readReturn(
  hash: string,
  provider: ConnectProvider,
): { handoff: string } | { result: string } | null {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  if (params.get("connect") !== provider) return null;
  const handoff = params.get("handoff") ?? "";
  if (HANDOFF.test(handoff)) return { handoff };
  const result = params.get("result") ?? "";
  return { result: WORD.test(result) ? result : "failed" };
}

async function detail(response: Response): Promise<string | undefined> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : undefined;
  } catch {
    return undefined;
  }
}

/** Starts a Connect in the phone's browser. Null once the browser is open. */
export async function startConnect(
  provider: ConnectProvider,
): Promise<ConnectOutcome | null> {
  const app = await phoneStatus();
  if (!app?.connect) return { result: "update_app", message: UPDATE_APP };
  try {
    const verifier = newVerifier();
    const challenge = await challengeOf(verifier);
    const response = await fetch(
      `${STARTS[provider]}?app_challenge=${challenge}&format=json`,
      {
        credentials: "same-origin",
        cache: "no-store",
        headers: { accept: "application/json" },
      },
    );
    if (!response.ok)
      return { result: "failed", message: await detail(response) };
    const { url } = (await response.json()) as { url?: unknown };
    if (typeof url !== "string" || !keep(provider, verifier))
      return { result: "failed" };
    if (!(await openConnect(url)))
      return {
        result: "failed",
        message: "Sales Xray couldn't open your browser. Try again.",
      };
    return null;
  } catch {
    return { result: "failed" };
  }
}

/** Finishes a Connect the app brought back to this page, if there is one. */
export async function finishConnect(
  provider: ConnectProvider,
): Promise<ConnectOutcome | null> {
  if (typeof window === "undefined") return null;
  const back = readReturn(window.location.hash, provider);
  if (!back) return null;
  // One use only: the hand-off leaves the address bar and history at once.
  window.history.replaceState(
    window.history.state,
    "",
    window.location.pathname + window.location.search,
  );
  const verifier = take(provider);
  if ("result" in back) return { result: back.result };
  if (!verifier) return { result: "failed", message: TOO_LONG };
  try {
    const response = await fetch(FINISHES[provider], {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
      },
      body: JSON.stringify({ handoff: back.handoff, verifier }),
    });
    if (!response.ok)
      return { result: "failed", message: await detail(response) };
    const body = (await response.json()) as { result?: unknown };
    return {
      result:
        typeof body.result === "string" && WORD.test(body.result)
          ? body.result
          : "failed",
    };
  } catch {
    return { result: "failed" };
  }
}

/**
 * For a Connect link: finishes a Connect the app brought back here, and inside
 * the app turns the link's click into the phone's-browser Connect. ``done``
 * hears each outcome.
 */
export function useAppConnect(
  provider: ConnectProvider,
  done: (outcome: ConnectOutcome) => void,
): (event: { preventDefault: () => void }) => void {
  const latest = useRef(done);
  useEffect(() => {
    latest.current = done;
  });
  useEffect(() => {
    void finishConnect(provider).then(
      (outcome) => outcome && latest.current(outcome),
    );
  }, [provider]);
  return useCallback(
    (event) => {
      if (!inPhoneApp()) return;
      event.preventDefault();
      void startConnect(provider).then(
        (outcome) => outcome && latest.current(outcome),
      );
    },
    [provider],
  );
}
