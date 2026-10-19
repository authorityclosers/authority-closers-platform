"use client";

/**
 * "Connect to Sales X-Ray": the consent screen of Connect (OAuth 2.0 + PKCE).
 * An app sends an organisation's owner or admin here; Allow returns them to the
 * app with a one-time code, Cancel with access_denied. A wrong app or return
 * address is shown here and never redirected, so this page cannot bounce
 * people elsewhere.
 */
import { Building2, Check, Link2, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import styles from "./connect.module.css";

const FIELDS = [
  "client_id",
  "redirect_uri",
  "scope",
  "code_challenge",
  "code_challenge_method",
  "response_type",
  "state",
] as const;

type Ask = Partial<Record<(typeof FIELDS)[number], string>>;

type Consent = {
  app: { name: string; client_id: string };
  returns_to: string | null;
  organisation: { id: string; name: string };
  scopes: { key: string; label: string }[];
};

type View =
  | { kind: "loading" }
  | { kind: "ready"; consent: Consent }
  | { kind: "problem"; title: string; text: string; organisation?: boolean }
  | { kind: "leaving" };

export function readAsk(search: string): Ask {
  const params = new URLSearchParams(search);
  const ask: Ask = {};
  for (const field of FIELDS) {
    const value = params.get(field);
    if (value !== null) ask[field] = value;
  }
  return ask;
}

async function post(path: string, body: unknown) {
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data: unknown = await response.json().catch(() => null);
  return { status: response.status, data };
}

const detail = (data: unknown) =>
  data &&
  typeof data === "object" &&
  "detail" in data &&
  typeof data.detail === "string"
    ? data.detail
    : null;

export function ConnectView() {
  const [view, setView] = useState<View>({ kind: "loading" });
  const [ask] = useState<Ask>(() =>
    typeof window === "undefined" ? {} : readAsk(window.location.search),
  );
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    post("/v1/oauth/authorize/check", ask).then(
      ({ status, data }) => {
        if (!live) return;
        if (status === 401) {
          const back = `${window.location.pathname}${window.location.search}`;
          window.location.assign(`/login?next=${encodeURIComponent(back)}`);
          setView({ kind: "leaving" });
        } else if (status === 403)
          setView({
            kind: "problem",
            title: "Choose your organisation",
            text:
              detail(data) ??
              "Open the organisation you want to connect, as its owner or admin.",
            organisation: true,
          });
        else if (status === 200 && data && typeof data === "object")
          setView({ kind: "ready", consent: data as Consent });
        else
          setView({
            kind: "problem",
            title: "This link can't be used",
            text: detail(data) ?? "Ask the app to start the connection again.",
          });
      },
      () =>
        live &&
        setView({
          kind: "problem",
          title: "Sales X-Ray isn't answering",
          text: "Check your connection and reload this page.",
        }),
    );
    return () => {
      live = false;
    };
  }, [ask]);

  const decide = (approve: boolean) => {
    setBusy(true);
    post("/v1/oauth/authorize/decision", { ...ask, approve }).then(
      ({ status, data }) => {
        const redirect =
          data &&
          typeof data === "object" &&
          "redirect" in data &&
          typeof data.redirect === "string"
            ? data.redirect
            : null;
        if (status === 200 && redirect) {
          setView({ kind: "leaving" });
          window.location.assign(redirect);
          return;
        }
        setBusy(false);
        setView({
          kind: "problem",
          title: "That did not work",
          text: detail(data) ?? "Reload the page and try again.",
        });
      },
      () => {
        setBusy(false);
        setView({
          kind: "problem",
          title: "Sales X-Ray isn't answering",
          text: "Check your connection and try again.",
        });
      },
    );
  };

  return (
    <main className={styles.page}>
      <section className={styles.card} aria-live="polite">
        {view.kind === "loading" || view.kind === "leaving" ? (
          <div className={styles.waiting} aria-busy="true">
            <span className={styles.spinner} aria-hidden="true" />
            <p>
              {view.kind === "leaving"
                ? "Taking you back…"
                : "Checking the app…"}
            </p>
          </div>
        ) : view.kind === "problem" ? (
          <>
            <span className={styles.icon} aria-hidden="true">
              <Link2 size={20} />
            </span>
            <h1>{view.title}</h1>
            <p className={styles.text}>{view.text}</p>
            {view.organisation ? (
              <a className={styles.primary} href="/organisation">
                Open my organisation
              </a>
            ) : null}
          </>
        ) : (
          <>
            <span className={styles.icon} aria-hidden="true">
              <ShieldCheck size={20} />
            </span>
            <h1>
              Connect <b>{view.consent.app.name}</b> to Sales X-Ray?
            </h1>
            <p className={styles.org}>
              <Building2 size={14} aria-hidden="true" />
              {view.consent.organisation.name}
            </p>
            <p className={styles.text}>It will be able to:</p>
            <ul className={styles.scopes}>
              {view.consent.scopes.map((scope) => (
                <li key={scope.key}>
                  <Check size={14} aria-hidden="true" />
                  {scope.label}
                </li>
              ))}
            </ul>
            <p className={styles.small}>
              You can remove it any time in Organisation → Integrations.
              {view.consent.returns_to ? (
                <>
                  {" "}
                  You will go back to <b>{view.consent.returns_to}</b>.
                </>
              ) : null}
            </p>
            <div className={styles.actions}>
              <button
                type="button"
                className={styles.secondary}
                disabled={busy}
                onClick={() => decide(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className={styles.primary}
                disabled={busy}
                onClick={() => decide(true)}
              >
                Allow
              </button>
            </div>
          </>
        )}
      </section>
    </main>
  );
}
