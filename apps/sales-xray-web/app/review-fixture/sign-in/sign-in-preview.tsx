"use client";

/**
 * The whole sign-in and first-run setup flow with a fictional person, for the
 * sign-in tutorial, phone QA without a dev account, and screenshots on GitHub
 * (orchestrator, 23 Oct 2026). Dev only, no sign-in needed, nothing is sent:
 * every /v1 request on this page is answered here, and Google, Apple and
 * Facebook are never opened.
 *
 * It runs the real screens. Start at sign-in and go through it: any email gets
 * a "code", any six digits sign in, any password works, and a provider button
 * shows where that provider's own screen opens. Then the setup steps, to the
 * page it would open next.
 *
 * `?step=` jumps to one screen: signin (the default), code, password, provider,
 * setup, setup-name, setup-business, setup-team, setup-first, setup-join.
 * `&provider=google|apple|facebook` picks the provider; `&chrome=0` hides the
 * preview bar (for recordings).
 */

import { useState, useSyncExternalStore, type ReactNode } from "react";

import { AccountAuth } from "../../account-auth";
import { providerLabel, type SignInProvider } from "../../account-auth-client";
import { SetupFlow } from "../../welcome/setup-flow";
import { forgetFreshSignIn, type SetupStep } from "../../welcome/setup-state";
import styles from "./sign-in-preview.module.css";

const PERSON = "00000000-0000-4000-8000-000000000001";
const SESSION = "00000000-0000-4000-8000-000000000002";
const PERSONAL = "00000000-0000-4000-8000-000000000003";
const ORGANISATION = "00000000-0000-4000-8000-000000000004";
const INVITED = "00000000-0000-4000-8000-000000000005";
const INVITE = "00000000-0000-4000-8000-000000000006";
const EMAIL = "asha@fictional-homes.example";

const KINDS = [
  ["simple", "Any business", "Six stages that suit most teams.", "spark"],
  [
    "real_estate",
    "Real estate",
    "From enquiry to site visit to booking.",
    "building",
  ],
  [
    "education",
    "Coaching & education",
    "Counselling, demo class, enrolment.",
    "cap",
  ],
  ["insurance", "Insurance", "Needs, quote, documents, policy.", "shield"],
  [
    "clinic",
    "Clinics & healthcare",
    "Enquiry, appointment, visit, treatment.",
    "heart",
  ],
  [
    "b2b_services",
    "B2B services & agencies",
    "Discovery, meeting, proposal, deal.",
    "briefcase",
  ],
  ["automotive", "Cars & bikes", "Test drive, quote, booking.", "car"],
  ["loans", "Loans & finance", "Eligibility, documents, disbursal.", "bank"],
  ["home_services", "Home services & solar", "Survey, quote, order.", "home"],
  ["software", "Software & SaaS", "Demo, trial, proposal, signed.", "screen"],
  ["travel", "Travel & holidays", "Plan, itinerary, booking.", "plane"],
  ["retail", "Shops & showrooms", "Enquiry, store visit, purchase.", "bag"],
].map(([id, name, blurb, icon]) => ({ id, name, blurb, icon, stages: [] }));

const SCREENS = [
  ["signin", "Sign in"],
  ["code", "Email code"],
  ["password", "Password"],
  ["provider", "Google, Apple or Facebook"],
  ["setup", "Setup 1: how you'll use it"],
  ["setup-name", "Setup 2: business name"],
  ["setup-business", "Setup 3: business type"],
  ["setup-team", "Setup 4: invite your team"],
  ["setup-first", "Setup 5: first lead"],
  ["setup-join", "Setup: join an invite"],
] as const;
type Screen = (typeof SCREENS)[number][0] | "done";
const PROVIDERS: readonly SignInProvider[] = ["google", "apple", "facebook"];

function answer(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function sent(init: RequestInit | undefined): Record<string, unknown> {
  try {
    return JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
  } catch {
    return {};
  }
}

/** Answers every /v1 request on this page; the rest (Next itself) goes out. */
function install() {
  if (typeof window === "undefined") return true;
  const marked = window as typeof window & { __sxSignInPreview?: true };
  if (marked.__sxSignInPreview) return true;
  marked.__sxSignInPreview = true;
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = new URL(
      String(input instanceof Request ? input.url : input),
      window.location.origin,
    );
    if (!url.pathname.startsWith("/v1/")) return real(input, init);
    const path = url.pathname;
    const method = (init?.method ?? "GET").toUpperCase();
    if (path === "/v1/auth/email-code/config")
      return answer({
        enabled: true,
        consent_version: "review-only",
        google_enabled: true,
        apple_enabled: true,
        facebook_enabled: true,
        expires_in_seconds: 600,
        resend_after_seconds: 30,
      });
    if (path === "/v1/auth/email-code/request")
      return answer(
        { accepted: true, expires_in_seconds: 600, resend_after_seconds: 30 },
        202,
      );
    if (path === "/v1/auth/email-code/verify")
      return answer({
        authenticated: true,
        person_id: PERSON,
        account_created: true,
        profile_complete: false,
      });
    if (path === "/v1/auth/password/login") return answer({ ok: true });
    if (path === "/v1/me/workspaces")
      return answer({
        person_id: PERSON,
        session_id: SESSION,
        selected_tenant_id: PERSONAL,
        workspaces: [],
      });
    if (path === "/v1/organisation" && method === "POST")
      return answer({
        tenant_id: ORGANISATION,
        name: String(sent(init).name ?? "Fictional Homes"),
      });
    if (path === "/v1/context")
      return answer({ tenant_id: String(sent(init).tenant_id ?? PERSONAL) });
    if (path === "/v1/lead-desk/journey/templates") return answer(KINDS);
    if (path === "/v1/lead-desk/journey")
      return answer({ version: 0, industry: null, stages: [] });
    if (path === "/v1/lead-desk/journey/template")
      return answer({
        version: 1,
        industry: String(sent(init).template ?? "simple"),
        stages: [],
      });
    if (path === "/v1/organisation/members") return answer({});
    if (path === `/v1/organisation/invites/${INVITE}/accept`)
      return answer({ status: "accepted", tenant_id: INVITED, role: "member" });
    // Nothing else on this page may reach the API.
    return answer({ detail: "Not in this preview." }, 404);
  };
  return true;
}

const noSubscription = () => () => {};
const readSearch = () => window.location.search;

function screenFrom(search: string): Screen {
  const asked = new URLSearchParams(search).get("step");
  return SCREENS.find(([key]) => key === asked)?.[0] ?? "signin";
}

export function SignInPreview() {
  useState(install);
  // Null on the server, the address on the client: no hydration mismatch.
  const search = useSyncExternalStore(noSubscription, readSearch, () => null);
  if (search === null) return null;
  return <Walkthrough search={search} />;
}

function Walkthrough({ search }: { search: string }) {
  const query = new URLSearchParams(search);
  const chrome = query.get("chrome") !== "0";
  const [screen, setScreen] = useState<Screen>(() => screenFrom(search));
  const [provider, setProvider] = useState<SignInProvider>(
    () => PROVIDERS.find((item) => item === query.get("provider")) ?? "google",
  );
  const [next, setNext] = useState<string | null>(null);
  const [run, setRun] = useState(0);

  const show = (target: Screen) => {
    setScreen(target);
    setRun((value) => value + 1);
    if (target === "done") return;
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("step", target);
      window.history.replaceState(window.history.state, "", url);
    } catch {
      // The screen still changes.
    }
  };
  const signedIn = () => {
    // A real sign-in would send Home to setup; here the preview goes on itself.
    forgetFreshSignIn();
    show("setup");
  };
  const setupAt = (step: SetupStep, join = false) => (
    <SetupFlow
      key={`${screen}:${run}`}
      preview={{
        step,
        path: join ? "join" : "business",
        person: {
          personId: PERSON,
          email: EMAIL,
          name: "Asha Example",
          personalId: PERSONAL,
          invite: join
            ? {
                inviteId: INVITE,
                tenantId: INVITED,
                organisationName: "Fictional Homes",
                role: "member",
                invitedAt: null,
                expiresAt: null,
              }
            : null,
        },
        templates: step === "start" || step === "name" ? undefined : KINDS,
        orgName:
          step === "start" || step === "name" ? undefined : "Fictional Homes",
        ...(step === "first"
          ? {
              applied: "real_estate",
              invited: ["ravi@fictional-homes.example"],
            }
          : {}),
        onLeave: (href) => {
          setNext(href);
          show("done");
        },
      }}
    />
  );

  let body: ReactNode;
  if (screen === "signin")
    body = (
      <AccountAuth
        key={run}
        onAuthenticated={signedIn}
        reviewProvider={(chosen) => {
          setProvider(chosen);
          show("provider");
        }}
      />
    );
  else if (screen === "code")
    body = (
      <AccountAuth
        key={run}
        previewState="auth.code"
        onAuthenticated={signedIn}
      />
    );
  else if (screen === "password")
    body = (
      <AccountAuth
        key={run}
        previewState="auth.password"
        onAuthenticated={signedIn}
      />
    );
  else if (screen === "provider")
    body = (
      <main className={styles.stand}>
        <section className={styles.card} aria-labelledby="provider-title">
          <p className={styles.eyebrow}>
            Sign in with {providerLabel(provider)}
          </p>
          <h1 id="provider-title">
            {providerLabel(provider)}’s own screen opens here
          </h1>
          <p>
            {provider === "apple"
              ? "On the web, Apple’s sign-in page opens. The person picks their Apple account, then comes straight back to Sales X-Ray."
              : `In the phone app, ${providerLabel(provider)} slides up a sheet over the app with the phone’s accounts. On the web, its sign-in window opens. The person picks an account, then comes straight back to Sales X-Ray.`}
          </p>
          <p className={styles.muted}>
            This preview never opens {providerLabel(provider)}.
          </p>
          <div className={styles.actions}>
            <button type="button" className={styles.primary} onClick={signedIn}>
              Continue as Asha Example
            </button>
            <button
              type="button"
              className={styles.secondary}
              onClick={() => show("signin")}
            >
              Back to sign-in
            </button>
          </div>
        </section>
      </main>
    );
  else if (screen === "setup") body = setupAt("start");
  else if (screen === "setup-name") body = setupAt("name");
  else if (screen === "setup-business") body = setupAt("business");
  else if (screen === "setup-team") body = setupAt("team");
  else if (screen === "setup-first") body = setupAt("first");
  else if (screen === "setup-join") body = setupAt("start", true);
  else
    body = (
      <main className={styles.stand}>
        <section className={styles.card} aria-labelledby="done-title">
          <p className={styles.eyebrow}>End of the preview</p>
          <h1 id="done-title">Sales X-Ray opens next</h1>
          <p>
            {next === "/leads#add=lead"
              ? "Leads, with Add lead open."
              : next === "/"
                ? "Home."
                : "A new call, ready to analyse."}
          </p>
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primary}
              onClick={() => show("signin")}
            >
              Start again
            </button>
          </div>
        </section>
      </main>
    );

  return (
    <div className={styles.frame} data-review-preview="sign-in">
      {chrome ? (
        <div className={styles.bar} role="region" aria-label="Preview controls">
          <span className={styles.badge}>Preview · nothing is sent</span>
          <label className={styles.picker}>
            <span className={styles.srOnly}>Screen</span>
            <select
              value={screen === "done" ? "" : screen}
              onChange={(event) => show(event.target.value as Screen)}
            >
              {screen === "done" ? (
                <option value="">End of the preview</option>
              ) : null}
              {SCREENS.map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <span className={styles.hint}>
            Any email, any 6 digits, any password.
          </span>
        </div>
      ) : null}
      {body}
    </div>
  );
}
