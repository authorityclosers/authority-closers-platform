/**
 * Switching workspace in place (owner bug #17, 29 Oct 2026): the page no
 * longer reloads, so anything kept in memory between screens for one
 * workspace is forgotten here when the workspace changes. Every read a store
 * starts notes the generation; an answer that comes back after a change is
 * dropped, so nothing read for one workspace ever shows under another.
 *
 * Stores keyed by person, session and workspace (calls, report settings,
 * pipelines, coaching, branding) need nothing from here. Stores that keep a
 * single answer (the Chats list, the Leads and Review badges) register.
 */

type Reset = (reread: boolean) => void;

let generation = 0;
let arrivedAt = -Infinity;
const resets = new Set<Reset>();

/**
 * Forget a store's answers whenever the workspace changes. `reread` is true
 * once the server has the workspace the page will show (read again now), and
 * false while a switch is still on its way (read nothing yet).
 */
export function onWorkspaceChange(reset: Reset): () => void {
  resets.add(reset);
  return () => {
    resets.delete(reset);
  };
}

/** Moves on every change: a read compares it before and after. */
export function workspaceGeneration(): number {
  return generation;
}

/** A switch has started, landed or been undone: drop the old answers. */
export function announceWorkspaceChange(
  stage: "leaving" | "arrived" | "stayed",
): void {
  generation += 1;
  if (stage === "arrived") arrivedAt = Date.now();
  for (const reset of [...resets]) reset(stage !== "leaving");
}

/** True for the frame that mounts as a switch lands (its arrival motion). */
export function justArrived(now = Date.now()): boolean {
  return now - arrivedAt < 1_000;
}

/** For tests: no switch has happened (stores stay registered). */
export function resetWorkspaceChangeForTests(): void {
  arrivedAt = -Infinity;
}
