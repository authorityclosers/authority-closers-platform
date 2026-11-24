/**
 * The workspace this tab last confirmed (v1.96 device polish, lane P: on a
 * backend 502 Leads swapped to the loading shell with "Workspace access could
 * not be checked", losing the header and everything on screen). When the
 * check fails for a moment the app keeps the frame it last confirmed in this
 * tab and checks again quietly; the pages' own reads say what didn't load.
 *
 * Kept in this tab only (sessionStorage), and forgotten on any page outside
 * the signed-in app (sign-in, sign-out) and on a "signed out" answer, so a
 * next person in the same tab never meets it.
 */
export const LAST_ACCESS_KEY = "sx.last-access";

type Choices = Readonly<{
  selected_tenant_id: string | null;
  workspaces: readonly unknown[];
}>;

export function rememberAccess<T extends Choices>(choices: T): void {
  try {
    if (choices.selected_tenant_id === null) return;
    window.sessionStorage.setItem(LAST_ACCESS_KEY, JSON.stringify(choices));
  } catch {
    // Without storage a failed check shows the waiting frame, as before.
  }
}

export function keptAccess<T extends Choices>(): T | null {
  try {
    const raw = window.sessionStorage.getItem(LAST_ACCESS_KEY);
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (
      value !== null &&
      typeof value === "object" &&
      typeof (value as Choices).selected_tenant_id === "string" &&
      Array.isArray((value as Choices).workspaces)
    )
      return value as T;
  } catch {
    // Unreadable: as if nothing were kept.
  }
  return null;
}

export function forgetAccess(): void {
  try {
    window.sessionStorage.removeItem(LAST_ACCESS_KEY);
  } catch {
    // Nothing kept.
  }
}
