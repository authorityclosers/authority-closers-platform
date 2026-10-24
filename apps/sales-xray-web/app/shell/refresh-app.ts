/**
 * Starts Sales X-Ray afresh without signing out (orchestrator, 24 Oct 2026:
 * a seller reinstalled the app when it "hung a little"). A reload drops
 * everything kept in memory for speed (lists, details, read-ahead); this also
 * forgets the early-read flag and anything in the browser's caches.
 *
 * Kept: the sign-in, preferences, uploads and recordings in progress, and
 * changes not sent yet (sync/write-queue.ts).
 */
import { EARLY_CONVERSATION_KEY } from "../early-reads";

export async function refreshAppData(): Promise<void> {
  try {
    window.sessionStorage.removeItem(EARLY_CONVERSATION_KEY);
  } catch {
    // Storage blocked: nothing kept there.
  }
  try {
    if ("caches" in window) {
      const keys = await window.caches.keys();
      await Promise.all(keys.map((key) => window.caches.delete(key)));
    }
  } catch {
    // No caches to clear.
  }
  window.location.reload();
}
