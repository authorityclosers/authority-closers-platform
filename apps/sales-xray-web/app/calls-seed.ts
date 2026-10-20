import {
  parseSubmissionLibraryPage,
  type SubmissionLibraryPage,
} from "./acquisition-client";
import type { ServerRead } from "./server-reads";

/** The Calls page's first read, exactly as the browser makes it. */
export const CALLS_LIST_PATH =
  "/v1/conversation/acquisition/submissions?include_owners=true&order=reports_first&include_summary=true";

/**
 * The server's answer to the Calls list read as the page's first page of
 * rows: only a success with the browser read's own shape. Anything else
 * (no answer, a sign-in problem, an error, a bad shape) leaves the list to
 * the browser, which reads and reports as before.
 */
export function seededLibraryPage(
  read: ServerRead | undefined,
): SubmissionLibraryPage | null {
  if (read?.status !== 200) return null;
  try {
    return parseSubmissionLibraryPage(read.body);
  } catch {
    return null;
  }
}
