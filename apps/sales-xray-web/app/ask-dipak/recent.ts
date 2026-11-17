/**
 * The lesson last opened on this device, for the home's Continue card (owner's
 * pick H-A, 17 Nov 2026). A convenience only: if storage is blocked or
 * cleared, the home shows the library instead. Saved lessons and missions
 * stay on the account (progress.ts).
 */

const KEY = "sales-xray:ask-dipak:last-lesson";
const ID = /^[A-Za-z0-9-]{1,16}$/;

export function rememberLesson(id: string) {
  if (!ID.test(id)) return;
  try {
    window.localStorage.setItem(KEY, id);
  } catch {
    // Private window or storage full: Continue just won't show it.
  }
}

export function lastLesson(): string | null {
  try {
    const id = window.localStorage.getItem(KEY);
    return id && ID.test(id) ? id : null;
  } catch {
    return null;
  }
}
