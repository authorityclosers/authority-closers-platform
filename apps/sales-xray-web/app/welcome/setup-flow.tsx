"use client";

import {
  ArrowLeft,
  AudioLines,
  Briefcase,
  Building2,
  Car,
  Check,
  GraduationCap,
  HeartPulse,
  House,
  Landmark,
  LoaderCircle,
  MonitorSmartphone,
  Plane,
  ShieldCheck,
  ShoppingBag,
  Sparkles,
  UserPlus,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { readAccountProfile } from "../account-profile-client";
import {
  applyTemplate,
  readJourney,
  readTemplates,
  type TemplateView,
} from "../leads/journey/journey-client";
import { newCallHref } from "../new-call-navigation";
import { notify } from "../notice-center";
import {
  acceptInvite,
  addMember,
  createOrganisation,
  OrgApiError,
  readPendingInvites,
  type PendingInvite,
} from "../organisation/organisation-api";
import { readSalesXrayWorkspaces } from "../sales-xray-workspaces";
import { BrandMark } from "../shell/brand-lockup";
import {
  firstName,
  inviteEmails,
  markSetup,
  stepsFor,
  suggestedBusinessName,
  type SetupPath,
  type SetupStep,
} from "./setup-state";
import styles from "./setup-flow.module.css";

/**
 * /welcome: first-run setup, one question per step (setup-state.ts says when it
 * shows). It only uses what the app already does: create an organisation, set
 * its lead stages from a kind of business, invite people, accept an invite.
 */

// The same icons Leads → Lead stages gives each kind of business (journey-view.tsx).
const ICONS: Record<string, LucideIcon> = {
  spark: Sparkles,
  building: Building2,
  cap: GraduationCap,
  shield: ShieldCheck,
  heart: HeartPulse,
  briefcase: Briefcase,
  car: Car,
  bank: Landmark,
  home: House,
  screen: MonitorSmartphone,
  plane: Plane,
  bag: ShoppingBag,
};
const ADD_LEAD_HREF = "/leads#add=lead";

type Person = {
  personId: string;
  email: string | null;
  name: string | null;
  invite: PendingInvite | null;
  personalId: string | null;
};

export type SetupPreview = Readonly<{
  step: SetupStep;
  path: SetupPath;
  person: Person;
  templates?: TemplateView[];
  orgName?: string;
  applied?: string;
  invited?: string[];
  /** Review fixtures: where the flow would go next, instead of going there. */
  onLeave?: (href: string) => void;
}>;

/** A request key for retries; randomUUID is missing on the plain-http dev edge. */
function requestKey() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

async function selectWorkspace(tenantId: string) {
  const response = await fetch("/v1/context", {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({ tenant_id: tenantId }),
  });
  if (!response.ok) throw new Error("workspace_selection_rejected");
}

async function readPerson(
  signal: AbortSignal,
): Promise<Person | "signed-out" | "set-up"> {
  const response = await fetch("/v1/me/workspaces", {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    signal,
    headers: { accept: "application/json" },
  });
  if (response.status === 401) return "signed-out";
  if (!response.ok) throw new Error("identity_unavailable");
  const body = (await response.json()) as { person_id?: unknown };
  if (typeof body.person_id !== "string") throw new Error("identity_shape");
  const [directory, profile, invites] = await Promise.all([
    readSalesXrayWorkspaces(signal),
    readAccountProfile(signal).catch(() => null),
    readPendingInvites(signal).catch(() => null),
  ]);
  const invite = invites?.[0] ?? null;
  const organisations = directory.workspaces.filter(
    (item) => item.kind === "organisation",
  );
  // Already in a business, with nothing to join: nothing to set up here.
  if (organisations.length > 0 && !invite) {
    markSetup(body.person_id, "not-needed");
    return "set-up";
  }
  return {
    personId: body.person_id,
    email: profile?.email ?? null,
    name: profile?.name ?? null,
    invite,
    personalId:
      directory.workspaces.find((item) => item.kind === "personal")
        ?.tenant_id ?? null,
  };
}

function leave(
  personId: string | undefined,
  mark: "done" | "skipped",
  href: string,
) {
  if (personId) markSetup(personId, mark);
  // A full load: the app frame must read the workspace chosen here.
  window.location.assign(href);
}

export function SetupFlow({ preview }: { preview?: SetupPreview }) {
  const [person, setPerson] = useState<Person | null>(preview?.person ?? null);
  const [failed, setFailed] = useState(false);
  const [path, setPath] = useState<SetupPath>(
    preview?.path ?? (preview?.person.invite ? "join" : "business"),
  );
  const [index, setIndex] = useState(() =>
    preview ? Math.max(0, stepsFor(preview.path).indexOf(preview.step)) : 0,
  );
  const [orgName, setOrgName] = useState(
    preview?.orgName ?? suggestedBusinessName(preview?.person.email),
  );
  const [created, setCreated] = useState<string | null>(
    preview?.orgName ? preview.orgName : null,
  );
  const [templates, setTemplates] = useState<TemplateView[] | null>(
    preview?.templates ?? null,
  );
  const [version, setVersion] = useState(0);
  const [picked, setPicked] = useState<string | null>(null);
  const [applied, setApplied] = useState<string | null>(
    preview?.applied ?? null,
  );
  const [inviteText, setInviteText] = useState("");
  const [invited, setInvited] = useState<string[]>(preview?.invited ?? []);
  const [busy, setBusy] = useState(false);
  const [fieldError, setFieldError] = useState("");
  const createRequest = useRef<{ name: string; key: string } | null>(null);
  const acceptRequest = useRef<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const titleId = useId();
  const nameId = useId();
  const nameHint = useId();
  const teamId = useId();
  const teamHint = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (preview) return;
    const controller = new AbortController();
    void readPerson(controller.signal)
      .then((found) => {
        if (controller.signal.aborted) return;
        if (found === "signed-out") return window.location.replace("/");
        if (found === "set-up") return window.location.replace("/");
        setPerson(found);
        setOrgName(suggestedBusinessName(found.email));
        if (found.invite) setPath("join");
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [preview, attempt]);

  // Back (button, gesture or key) returns to the previous step, one per press.
  useEffect(() => {
    const onPop = (event: PopStateEvent) => {
      const at = (event.state as { sxSetup?: unknown } | null)?.sxSetup;
      setFieldError("");
      setIndex(typeof at === "number" ? at : 0);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // A new step moves focus to its question, for screen readers and keyboards.
  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true });
  }, [index]);

  const steps = stepsFor(path);
  const step = steps[Math.min(index, steps.length - 1)];

  function exit(mark: "done" | "skipped", href: string) {
    if (preview?.onLeave) preview.onLeave(href);
    else leave(person?.personId, mark, href);
  }

  function go(next: SetupStep, nextPath: SetupPath = path) {
    const at = stepsFor(nextPath).indexOf(next);
    setFieldError("");
    setIndex(at);
    try {
      window.history.pushState({ ...window.history.state, sxSetup: at }, "");
    } catch {
      // The step still changes; Back then leaves the page.
    }
  }

  function failure(title: string, error: unknown) {
    notify({
      id: "welcome-setup",
      tone: "error",
      title,
      message:
        error instanceof OrgApiError && error.message
          ? error.message
          : "Check your connection and try again.",
    });
  }

  async function loadStages() {
    try {
      const [list, journey] = await Promise.all([
        readTemplates(),
        readJourney(),
      ]);
      setTemplates(list);
      setVersion(journey.version);
      if (journey.industry) setApplied(journey.industry);
    } catch {
      setTemplates([]);
    }
  }

  async function start() {
    if (!person || busy) return;
    if (path === "business") return go("name");
    setBusy(true);
    try {
      if (path === "join" && person.invite) {
        acceptRequest.current ??= requestKey();
        const joined = await acceptInvite(
          person.invite.inviteId,
          acceptRequest.current,
        );
        await selectWorkspace(joined.tenantId);
      } else if (person.personalId) {
        await selectWorkspace(person.personalId);
      }
      go("first");
    } catch (error) {
      failure(
        path === "join"
          ? `You didn’t join ${person.invite?.organisationName ?? "the team"}`
          : "That didn’t open",
        error,
      );
    }
    setBusy(false);
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (created) return go("business");
    const clean = orgName.trim().replace(/\s+/g, " ");
    if (clean.length < 2 || clean.length > 80) {
      setFieldError("Use 2 to 80 characters.");
      return;
    }
    if (createRequest.current?.name !== clean)
      createRequest.current = { name: clean, key: requestKey() };
    setBusy(true);
    try {
      const organisation = await createOrganisation(
        clean,
        createRequest.current.key,
      );
      await selectWorkspace(organisation.tenantId);
      setCreated(organisation.name);
      void loadStages();
      go("business");
    } catch (error) {
      if (error instanceof OrgApiError && error.status < 500 && error.message)
        setFieldError(error.message);
      else failure("Your business wasn’t created", error);
    }
    setBusy(false);
  }

  async function applyStages() {
    if (!picked || busy) return;
    if (picked === applied) return go("team");
    setBusy(true);
    try {
      const journey = await applyTemplate(version, picked);
      setVersion(journey.version);
      setApplied(picked);
      go("team");
    } catch (error) {
      failure("Those stages weren’t saved", error);
    }
    setBusy(false);
  }

  async function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const { valid, invalid } = inviteEmails(inviteText);
    if (invalid.length) {
      setFieldError(
        `Check ${invalid.length === 1 ? "this address" : "these addresses"}: ${invalid.join(", ")}`,
      );
      return;
    }
    if (!valid.length) return go("first");
    setBusy(true);
    const sent: string[] = [];
    const refused: string[] = [];
    for (const email of valid) {
      try {
        await addMember(email, "member");
        sent.push(email);
      } catch {
        refused.push(email);
      }
    }
    setInvited((list) => [...list, ...sent]);
    setBusy(false);
    if (refused.length) {
      setInviteText(refused.join(", "));
      setFieldError(
        `We couldn’t invite ${refused.join(", ")}. Check the address, or invite them later from Team.`,
      );
      return;
    }
    setInviteText("");
    go("first");
  }

  if (!person)
    return (
      <main className={styles.page} aria-busy={!failed}>
        <div className={styles.centre}>
          {failed ? (
            <>
              <p className={styles.lead}>
                We couldn’t open your setup just now.
              </p>
              <div className={styles.inlineActions}>
                <button
                  type="button"
                  className={styles.primary}
                  onClick={() => {
                    setFailed(false);
                    setAttempt((value) => value + 1);
                  }}
                >
                  Try again
                </button>
                <Link className={styles.secondary} href="/">
                  Go to Home
                </Link>
              </div>
            </>
          ) : (
            <p className={styles.lead} role="status">
              <LoaderCircle
                className={styles.spin}
                size={18}
                aria-hidden="true"
              />
              Getting your account ready…
            </p>
          )}
        </div>
      </main>
    );

  const greeting = firstName(person.name);
  const inviteName = person.invite?.organisationName ?? "";
  const business = created ?? orgName.trim();
  const appliedName = templates?.find((item) => item.id === applied)?.name;
  const firstAction =
    path === "solo"
      ? { label: "Analyse your first call", href: newCallHref("/") }
      : { label: "Add your first lead", href: ADD_LEAD_HREF };

  return (
    <main className={styles.page} aria-labelledby={titleId}>
      <header className={styles.top}>
        <div className={styles.topRow}>
          {index > 0 ? (
            <button
              type="button"
              className={styles.iconButton}
              aria-label="Back"
              disabled={busy}
              onClick={() => window.history.back()}
            >
              <ArrowLeft size={20} aria-hidden="true" />
            </button>
          ) : (
            <span className={styles.brand} aria-label="Sales X-Ray">
              <BrandMark />
            </span>
          )}
          <button
            type="button"
            className={styles.skip}
            disabled={busy}
            onClick={() => exit(step === "first" ? "done" : "skipped", "/")}
          >
            {step === "first" ? "Go to Home" : "Skip setup"}
          </button>
        </div>
        <div className={styles.progress}>
          <span className={styles.progressText}>
            Step {index + 1} of {steps.length}
          </span>
          <span
            className={styles.track}
            role="progressbar"
            aria-label="Setup progress"
            aria-valuemin={1}
            aria-valuemax={steps.length}
            aria-valuenow={index + 1}
          >
            <span
              className={styles.fill}
              style={{ width: `${((index + 1) / steps.length) * 100}%` }}
            />
          </span>
        </div>
      </header>

      {step === "start" ? (
        <section className={styles.body} key="start">
          <p className={styles.eyebrow}>
            {greeting ? `Welcome, ${greeting}` : "Welcome to Sales X-Ray"}
          </p>
          <h1 id={titleId} ref={headingRef} tabIndex={-1}>
            How will you use Sales X-Ray?
          </h1>
          <p className={styles.lead}>Pick one. You can change this later.</p>
          <div
            className={styles.choices}
            role="radiogroup"
            aria-labelledby={titleId}
          >
            {person.invite ? (
              <Choice
                icon={UserPlus}
                title={`Join ${inviteName}`}
                text={`${inviteName} invited you as ${person.invite.role === "admin" ? "an admin" : "a member"}.`}
                on={path === "join"}
                onPick={() => setPath("join")}
              />
            ) : null}
            <Choice
              icon={Building2}
              title="For my business"
              text="Leads, calls and your sales team in one place."
              on={path === "business"}
              onPick={() => setPath("business")}
            />
            <Choice
              icon={AudioLines}
              title="Just my own calls"
              text="Analyse your sales calls and get coaching. Add a business any time."
              on={path === "solo"}
              onPick={() => setPath("solo")}
            />
          </div>
          <footer className={styles.actions}>
            <button
              type="button"
              className={styles.primary}
              disabled={busy}
              onClick={() => void start()}
            >
              {busy ? (
                <LoaderCircle
                  className={styles.spin}
                  size={18}
                  aria-hidden="true"
                />
              ) : null}
              {path === "join"
                ? `Join ${inviteName}`
                : path === "business"
                  ? "Set up my business"
                  : "Start with my calls"}
            </button>
          </footer>
        </section>
      ) : step === "name" ? (
        <form
          className={styles.body}
          key="name"
          onSubmit={(event) => void create(event)}
          noValidate
        >
          <p className={styles.eyebrow}>Your business</p>
          <h1 id={titleId} ref={headingRef} tabIndex={-1}>
            What’s your business called?
          </h1>
          <p className={styles.lead}>
            You’ll be its owner. Your team sees this name when they join.
          </p>
          <label className={styles.label} htmlFor={nameId}>
            Business name
          </label>
          <input
            id={nameId}
            className={styles.input}
            value={created ?? orgName}
            onChange={(event) => {
              setOrgName(event.target.value);
              setFieldError("");
            }}
            maxLength={80}
            autoComplete="organization"
            placeholder="Your business name"
            readOnly={created !== null}
            aria-invalid={fieldError ? true : undefined}
            aria-describedby={nameHint}
          />
          <p
            id={nameHint}
            className={fieldError ? styles.fieldError : styles.hint}
          >
            {fieldError ||
              (created
                ? "Created. Your business is ready."
                : "Use the name your customers know.")}
          </p>
          <footer className={styles.actions}>
            <button type="submit" className={styles.primary} disabled={busy}>
              {busy ? (
                <LoaderCircle
                  className={styles.spin}
                  size={18}
                  aria-hidden="true"
                />
              ) : null}
              {created ? "Choose what you sell" : "Create my business"}
            </button>
          </footer>
        </form>
      ) : step === "business" ? (
        <section className={styles.body} key="business">
          <p className={styles.eyebrow}>{business || "Your business"}</p>
          <h1 id={titleId} ref={headingRef} tabIndex={-1}>
            What does your business sell?
          </h1>
          <p className={styles.lead}>
            Pick the closest one. You get lead stages that fit, and can change
            them later in Leads.
          </p>
          <ul className={styles.kinds} aria-label="Kinds of business">
            {templates === null
              ? Array.from({ length: 6 }, (_, item) => (
                  <li key={item} aria-hidden="true">
                    <span className={styles.kind} data-skeleton="true" />
                  </li>
                ))
              : templates.map((item) => {
                  const Icon = ICONS[item.icon] ?? Sparkles;
                  const on = item.id === picked;
                  return (
                    <li key={item.id}>
                      <button
                        type="button"
                        className={styles.kind}
                        aria-pressed={on}
                        onClick={() => setPicked(item.id)}
                      >
                        <span className={styles.kindIcon} aria-hidden="true">
                          <Icon size={18} strokeWidth={1.9} />
                        </span>
                        <span className={styles.kindText}>
                          <strong>{item.name}</strong>
                          <small>{item.blurb}</small>
                        </span>
                        <span className={styles.kindCheck} aria-hidden="true">
                          {on ? <Check size={14} strokeWidth={2.6} /> : null}
                        </span>
                      </button>
                    </li>
                  );
                })}
          </ul>
          {templates !== null && templates.length === 0 ? (
            <p className={styles.hint}>
              Kinds of business didn’t load. Skip for now and choose in Leads
              later.
            </p>
          ) : null}
          <footer className={styles.actions}>
            <button
              type="button"
              className={styles.primary}
              disabled={busy || !picked}
              onClick={() => void applyStages()}
            >
              {busy ? (
                <LoaderCircle
                  className={styles.spin}
                  size={18}
                  aria-hidden="true"
                />
              ) : null}
              {picked ? "Use these stages" : "Pick one to continue"}
            </button>
            <button
              type="button"
              className={styles.secondary}
              disabled={busy}
              onClick={() => go("team")}
            >
              Skip for now
            </button>
          </footer>
        </section>
      ) : step === "team" ? (
        <form
          className={styles.body}
          key="team"
          onSubmit={(event) => void invite(event)}
          noValidate
        >
          <p className={styles.eyebrow}>{business || "Your team"}</p>
          <h1 id={titleId} ref={headingRef} tabIndex={-1}>
            Who sells with you?
          </h1>
          <p className={styles.lead}>
            Invite your team by email. Each person joins once they accept.
          </p>
          <label className={styles.label} htmlFor={teamId}>
            Email addresses
          </label>
          <textarea
            id={teamId}
            className={styles.input}
            rows={3}
            value={inviteText}
            onChange={(event) => {
              setInviteText(event.target.value);
              setFieldError("");
            }}
            placeholder="name@company.com, another@company.com"
            autoComplete="off"
            spellCheck={false}
            aria-invalid={fieldError ? true : undefined}
            aria-describedby={teamHint}
          />
          <p
            id={teamHint}
            className={fieldError ? styles.fieldError : styles.hint}
          >
            {fieldError ||
              "Separate addresses with commas or new lines. They join as members."}
          </p>
          {invited.length ? (
            <ul className={styles.sent} aria-label="Invited">
              {invited.map((email) => (
                <li key={email}>
                  <Check size={14} aria-hidden="true" />
                  {email}
                </li>
              ))}
            </ul>
          ) : null}
          <footer className={styles.actions}>
            <button
              type="submit"
              className={styles.primary}
              disabled={busy || !inviteEmails(inviteText).valid.length}
            >
              {busy ? (
                <LoaderCircle
                  className={styles.spin}
                  size={18}
                  aria-hidden="true"
                />
              ) : null}
              {(() => {
                const count = inviteEmails(inviteText).valid.length;
                return count > 1 ? `Send ${count} invites` : "Send invite";
              })()}
            </button>
            <button
              type="button"
              className={styles.secondary}
              disabled={busy}
              onClick={() => go("first")}
            >
              {invited.length ? "Continue" : "Skip for now"}
            </button>
          </footer>
        </form>
      ) : (
        <section className={styles.body} key="first">
          <p className={styles.eyebrow}>You’re ready</p>
          <h1 id={titleId} ref={headingRef} tabIndex={-1}>
            {path === "join"
              ? `You’re in ${inviteName}`
              : path === "solo"
                ? "Analyse your first call"
                : "Add your first lead"}
          </h1>
          <p className={styles.lead}>
            {path === "solo"
              ? "Upload a recording to get your report and coaching."
              : "Add a lead now, or analyse a call you’ve already recorded."}
          </p>
          {path === "business" ? (
            <ul className={styles.summary} aria-label="Set up">
              <li>
                <Check size={16} aria-hidden="true" />
                <span>
                  <strong>{business}</strong> is ready, with you as owner
                </span>
              </li>
              <li data-done={applied ? "true" : undefined}>
                <Check size={16} aria-hidden="true" />
                <span>
                  {appliedName
                    ? `Lead stages for ${appliedName.toLowerCase()}`
                    : "Standard lead stages; choose a kind of business in Leads any time"}
                </span>
              </li>
              <li data-done={invited.length ? "true" : undefined}>
                <Check size={16} aria-hidden="true" />
                <span>
                  {invited.length
                    ? `${invited.length} ${invited.length === 1 ? "invite" : "invites"} sent`
                    : "Invite your team any time from Team"}
                </span>
              </li>
            </ul>
          ) : null}
          <footer className={styles.actions}>
            <button
              type="button"
              className={styles.primary}
              onClick={() => exit("done", firstAction.href)}
            >
              {firstAction.label}
            </button>
            {path === "solo" ? null : (
              <button
                type="button"
                className={styles.secondary}
                onClick={() => exit("done", newCallHref("/"))}
              >
                <AudioLines size={16} aria-hidden="true" />
                Analyse a call instead
              </button>
            )}
          </footer>
        </section>
      )}
    </main>
  );
}

function Choice({
  icon: Icon,
  title,
  text,
  on,
  onPick,
}: {
  icon: LucideIcon;
  title: string;
  text: string;
  on: boolean;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={on}
      className={styles.choice}
      onClick={onPick}
    >
      <span className={styles.choiceIcon} aria-hidden="true">
        <Icon size={20} strokeWidth={1.9} />
      </span>
      <span className={styles.choiceText}>
        <strong>{title}</strong>
        <small>{text}</small>
      </span>
      <span className={styles.radio} aria-hidden="true" />
    </button>
  );
}
