import {
  record,
  parseAllowance,
  parseSubmissionLibraryPage,
  type Allowance,
  type LibrarySubmission,
} from "./acquisition-client";
import {
  parseProfile,
  type AccountProfileRecord,
} from "./account-profile-client";
import { parseWorkspaceChoices, type ViewState } from "./workspace-choices";
import { parseSalesXrayWorkspaces } from "./sales-xray-workspaces";
import {
  parseCallSummary,
  parseCallActivity,
  type CallSummary,
  type CallActivity,
} from "./dashboard/dashboard-data";

export type SessionSeed = {
  view: ViewState;
  profile: AccountProfileRecord | null;
};
export type ReadState<T> =
  | { status: "loading" }
  | { status: "ready"; value: T }
  | { status: "error"; forbidden: boolean };
export type DashboardSnapshot = {
  contextKey: string;
  summary: ReadState<CallSummary | null>;
  activity: ReadState<CallActivity | null>;
  allowance: ReadState<Allowance>;
  recent: ReadState<LibrarySubmission[]>;
};
export function sessionContextKey(seed: SessionSeed | null): string | null {
  const view = seed?.view;
  return view?.kind === "ready" && view.choices.selected_tenant_id
    ? JSON.stringify([
        view.choices.person_id,
        view.choices.session_id,
        view.choices.selected_tenant_id,
      ])
    : null;
}
export function parseSessionSeed(value: unknown): SessionSeed {
  const body = record(value);
  const identity = parseWorkspaceChoices(body.identity);
  const directory = parseSalesXrayWorkspaces(body.directory);
  if (!identity || !directory) throw new Error("invalid_bootstrap");
  const choices = {
    ...identity,
    ...directory,
    salesXrayWorkspaces: directory.workspaces,
  };
  let profile: AccountProfileRecord | null = null;
  try {
    if (body.profile !== null) profile = parseProfile(body.profile);
  } catch {
    /* Secondary profile failure never grants access. */
  }
  return {
    view: {
      kind:
        choices.selected_tenant_id !== null
          ? "ready"
          : choices.workspaces.length
            ? "chooser"
            : "empty",
      choices,
    },
    profile,
  };
}
function part<T>(value: unknown, parse: (value: unknown) => T): ReadState<T> {
  try {
    const item = record(value);
    if (item.status !== 200)
      return { status: "error", forbidden: item.status === 403 };
    return { status: "ready", value: parse(item.data) };
  } catch {
    return { status: "error", forbidden: false };
  }
}
export function parseDashboardSnapshot(
  value: unknown,
  contextKey: string,
): DashboardSnapshot {
  const body = record(value);
  return {
    contextKey,
    summary: part(body.summary, parseCallSummary),
    activity: part(body.activity, parseCallActivity),
    allowance: part(body.allowance, parseAllowance),
    recent: part(body.recent, (value) =>
      parseSubmissionLibraryPage(value).submissions.slice(0, 5),
    ),
  };
}
