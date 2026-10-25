/**
 * First-run setup (owner, 23 Oct 2026: "the login and adding and selecting
 * business type has a ugly and confusing UI, not progressive").
 *
 * After a first sign-in, /welcome asks one question per step: how the person
 * will use Sales X-Ray, then for a business its name, what it sells and who
 * sells with them, and last a first lead or call. Every step can be skipped and
 * nothing is a dead end. Whether this device has shown it is remembered per
 * person; an account that already has an organisation or a call never sees it.
 */

export type SetupPath = "business" | "solo" | "join" | "pick";
export type SetupStep =
  | "workspace"
  | "start"
  | "name"
  | "business"
  | "team"
  | "first";
export type SetupMark = "done" | "skipped" | "not-needed";

export const WELCOME_PATH = "/welcome";

/**
 * Right after a sign-in, someone with more than one workspace (organisations,
 * their own calls) is asked where to work, in the middle of the screen (owner,
 * 25 Oct 2026: a tester got lost between her organisation and her account).
 */
export const PICK_PATH = `${WELCOME_PATH}?pick=1`;

/** Set on the page while Home decides whether a first run opens. */
export const FIRST_RUN_ATTRIBUTE = "data-sx-first-run";

export function holdFirstRun(on: boolean) {
  if (on) document.documentElement.setAttribute(FIRST_RUN_ATTRIBUTE, "");
  else document.documentElement.removeAttribute(FIRST_RUN_ATTRIBUTE);
}

export function setupKey(personId: string) {
  return `sx-setup:${personId}`;
}

/** What this device remembers for this person; null when never set or unreadable. */
export function readSetupMark(personId: string): SetupMark | null {
  try {
    const value = window.localStorage.getItem(setupKey(personId));
    return value === "done" || value === "skipped" || value === "not-needed"
      ? value
      : null;
  } catch {
    // Without storage the flow is never forced on anyone.
    return "not-needed";
  }
}

export function markSetup(personId: string, mark: SetupMark) {
  try {
    window.localStorage.setItem(setupKey(personId), mark);
  } catch {
    // Nothing kept: the next visit checks the account again.
  }
}

/** The steps a path shows, in order. Members who join skip the owner's setup. */
export function stepsFor(path: SetupPath): SetupStep[] {
  if (path === "pick") return ["workspace"];
  return path === "business"
    ? ["start", "name", "business", "team", "first"]
    : ["start", "first"];
}

/** Where to work is asked when sign-in leaves two or more to choose from. */
export function needsPick(enabledWorkspaces: number) {
  return enabledWorkspaces >= 2;
}

/** A brand-new account: no organisation of its own or to join, and no calls yet. */
export function needsSetup({
  organisations,
  calls,
}: {
  organisations: number;
  calls: number | null;
}) {
  return organisations === 0 && calls === 0;
}

// Addresses anyone can get: their domain says nothing about a business.
const OPEN_MAIL = new Set([
  "aol.com",
  "gmail.com",
  "gmx.com",
  "googlemail.com",
  "hotmail.com",
  "icloud.com",
  "live.com",
  "mail.com",
  "me.com",
  "msn.com",
  "outlook.com",
  "outlook.in",
  "proton.me",
  "protonmail.com",
  "rediffmail.com",
  "yahoo.co.in",
  "yahoo.com",
  "yahoo.in",
  "yandex.com",
  "zoho.com",
  "zohomail.in",
]);

/** A starting name for the business from a work address ("sales@bright-homes.in" → "Bright Homes"). */
export function suggestedBusinessName(email: string | null | undefined) {
  const domain = email?.split("@")[1]?.trim().toLowerCase();
  if (!domain || OPEN_MAIL.has(domain)) return "";
  const label = domain.split(".")[0] ?? "";
  return label
    .split(/[-_]+/)
    .filter(Boolean)
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(" ")
    .slice(0, 80);
}

/** Emails typed into the invite field: split on commas, spaces or new lines. */
export function inviteEmails(text: string) {
  const seen = new Set<string>();
  const valid: string[] = [];
  const invalid: string[] = [];
  for (const raw of text.split(/[\s,;]+/)) {
    const email = raw.trim().toLowerCase();
    if (!email || seen.has(email)) continue;
    seen.add(email);
    (/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email) ? valid : invalid).push(email);
  }
  return { valid, invalid };
}

/** "Asha" from "Asha Rao"; null when there is no name to greet. */
export function firstName(name: string | null | undefined) {
  const first = name?.trim().split(/\s+/)[0];
  return first ? first[0].toUpperCase() + first.slice(1) : null;
}

// Set when the sign-in screen finishes without a call file waiting, so Home
// checks for a first run once, right after that sign-in, and never mid-upload.
const FRESH_SIGN_IN_KEY = "sx-fresh-sign-in";

export function noteFreshSignIn() {
  try {
    window.sessionStorage.setItem(FRESH_SIGN_IN_KEY, "1");
  } catch {
    // Without storage no first run is offered; the app still opens.
  }
}

export function freshSignIn() {
  try {
    return window.sessionStorage.getItem(FRESH_SIGN_IN_KEY) === "1";
  } catch {
    return false;
  }
}

export function forgetFreshSignIn() {
  try {
    window.sessionStorage.removeItem(FRESH_SIGN_IN_KEY);
  } catch {
    // Nothing kept.
  }
}
