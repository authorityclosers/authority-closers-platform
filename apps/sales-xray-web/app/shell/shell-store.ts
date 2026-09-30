/**
 * Persistent in-memory cache for LightboxShell state across page navigations.
 * Prevents shell flickering, state resets, and duplicate fetches during client transitions.
 */

export interface ShellSummaryCounts {
  total: number;
  processing: number;
  completed: number;
  needsAttention: number;
}

export interface ShellWorkspace {
  tenant_id: string;
  name: string;
}

export interface ShellRecentCall {
  id: string;
  name: string;
  date: string;
  /** Label revision, so a rename from the sidebar is never a stale write. */
  revision?: number;
}

export interface ShellStoreState {
  collapsed: boolean;
  workspaces: ShellWorkspace[];
  selectedTenantId: string | null;
  selectedTenantAccountKey: string | null;
  counts: ShellSummaryCounts | null;
  recentCalls: ShellRecentCall[];
  recentCallsContextKey: string | null;
  recentFetchedAt: number | null;
  profileName: string | null;
  recentsOpen: boolean;
  /** Timestamp (ms) of the last successful workspace/profile fetch, or null. */
  fetchedAt: number | null;
}

let globalState: ShellStoreState = {
  collapsed: false,
  workspaces: [],
  selectedTenantId: null,
  selectedTenantAccountKey: null,
  counts: null,
  recentCalls: [],
  recentCallsContextKey: null,
  recentFetchedAt: null,
  profileName: null,
  recentsOpen: true,
  fetchedAt: null,
};

// Initialize collapsed from localStorage once on client
if (typeof window !== "undefined") {
  try {
    const saved = localStorage.getItem("sx.sidebar.collapsed");
    if (saved !== null) {
      globalState.collapsed = saved === "true";
    }
  } catch {}
}

export function getShellState(): ShellStoreState {
  return globalState;
}

export function updateShellState(
  patch: Partial<ShellStoreState>,
): ShellStoreState {
  globalState = { ...globalState, ...patch };
  return globalState;
}

export function recentCallsForContext(
  state: Pick<ShellStoreState, "recentCalls" | "recentCallsContextKey">,
  contextKey: string | null,
): ShellRecentCall[] {
  return contextKey !== null && state.recentCallsContextKey === contextKey
    ? state.recentCalls
    : [];
}

/** Sent when a call is created, renamed away or finishes: Recents refetch. */
export const RECENTS_CHANGED_EVENT = "sales-xray:recents-changed";
