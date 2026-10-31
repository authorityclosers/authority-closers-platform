/**
 * The advanced bug reporter's own server calls (owner, 31 Oct 2026).
 *
 * Who may use it: everyone in the Authority Closers organisation, the
 * platform's own staff, and the testers the owner lets in. GET
 * /v1/bug-reports/advanced answers "on", "requested" (asked, waiting for the
 * owner) or "off"; POST /v1/bug-reports/advanced/request asks for it. Read
 * once per page.
 *
 * The files that go with a report (the picture before its marks, each
 * comment's small picture, and the person's own files) follow it one by one:
 * POST /v1/bug-reports/{id}/files, the file itself as the body.
 */

import { onWorkspaceChange } from "../workspace-change";
import { BugReportError } from "./bug-report-client";

export type AdvancedAccess = "on" | "requested" | "off";

let asked: Promise<AdvancedAccess> | null = null;
let askedAt = 0;
let serverKnows = false;

/**
 * An answer from the server is kept for two minutes; a failed read is not
 * kept at all, and a workspace switch forgets it. It was kept for the page's
 * life, so a phone whose first read failed (before sign-in finished, or while
 * the server restarted) never showed the advanced reporter until the app
 * restarted, while another phone on the same account did (phone personas,
 * 1 Nov 2026).
 */
const KEPT_MS = 2 * 60 * 1000;
onWorkspaceChange(() => {
  asked = null;
  serverKnows = false;
});

/** The development site, while its server does not answer yet. */
const DEVELOPMENT = new Set([
  "salesxray-dev.authorityclosers.com",
  "localhost",
]);

export function advancedAccess(): Promise<AdvancedAccess> {
  if (asked && Date.now() - askedAt > KEPT_MS) asked = null;
  if (asked) return asked;
  askedAt = Date.now();
  let answered = false;
  // Started from a settled promise, so a fetch that throws or gives nothing back (a page's
  // test double) reads as off instead of breaking the page.
  const asking: Promise<AdvancedAccess> = Promise.resolve()
    .then(() =>
      fetch("/v1/bug-reports/advanced", {
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: { accept: "application/json" },
      }),
    )
    .then(async (response): Promise<AdvancedAccess> => {
      if (
        response.status === 404 &&
        DEVELOPMENT.has(window.location.hostname)
      ) {
        return "on";
      }
      if (!response.ok) return "off";
      serverKnows = true;
      answered = true;
      const body = (await response.json().catch(() => null)) as {
        access?: unknown;
      } | null;
      return body?.access === "on" || body?.access === "requested"
        ? body.access
        : "off";
    })
    .catch((): AdvancedAccess => "off")
    .then((access) => {
      // Only the server's answer is kept; the next ask tries again.
      if (!answered && asked === asking) asked = null;
      return access;
    });
  asked = asking;
  return asking;
}

/** True once the server has answered for the advanced reporter: it takes its parts. */
export function advancedServer(): boolean {
  return serverKnows;
}

export function forgetAdvancedAccessForTests() {
  asked = null;
  askedAt = 0;
  serverKnows = false;
}

/** Asks the owner to let this person use the advanced reporter. */
export async function requestAdvanced(): Promise<AdvancedAccess> {
  const response = await fetch("/v1/bug-reports/advanced/request", {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { accept: "application/json" },
  }).catch(() => null);
  if (!response?.ok) {
    throw new BugReportError(
      "Your request didn't go. Try again in a moment.",
      response?.status ?? 0,
    );
  }
  asked = Promise.resolve("requested");
  askedAt = Date.now();
  return "requested";
}

export type FileRole = "original" | "element" | "attachment";

/** One file that goes with a sent report. */
export async function uploadBugFile(
  bugId: string,
  file: Blob,
  role: FileRole,
  name: string,
  n?: number,
): Promise<void> {
  const response = await fetch(
    `/v1/bug-reports/${encodeURIComponent(bugId)}/files`,
    {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: {
        accept: "application/json",
        "content-type": file.type || "application/octet-stream",
        "x-file-role": role,
        "x-file-name": encodeURIComponent(name.slice(0, 120)),
        ...(n ? { "x-file-n": String(n) } : {}),
      },
      body: file,
    },
  ).catch(() => null);
  if (!response?.ok) {
    throw new BugReportError(
      "A file didn't go with your report.",
      response?.status ?? 0,
    );
  }
}
