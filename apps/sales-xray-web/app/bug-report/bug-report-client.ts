/** Sending a bug report: POST /v1/bug-reports (ac_platform/bug_reports/http.py). */

import type { ReportContext } from "./device";
import type { RecentError } from "./recent-errors";

export type ReportPicture = Readonly<{
  blob: Blob;
  source: "auto" | "upload";
}>;

export type BugReportBody = Readonly<{
  commandId: string;
  words: string;
  blocksWork: boolean;
  route: string;
  context: ReportContext;
  errors: readonly RecentError[];
  picture: ReportPicture | null;
}>;

export type BugReportSent = Readonly<{
  bugId: string;
  picture: "kept" | "skipped" | "none";
}>;

export const PICTURE_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;
export const MAX_PICTURE_BYTES = 4 * 1024 * 1024;

export class BugReportError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "BugReportError";
  }
}

const FALLBACK: Record<number, string> = {
  401: "Sign in again, then send your report.",
  403: "Reload this page, then send your report.",
  413: "That picture is too large. Send it without the picture.",
  429: "That's a lot of reports in an hour. Send again a little later.",
};

function base64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const url = String(reader.result ?? "");
      resolve(url.slice(url.indexOf(",") + 1));
    };
    reader.onerror = () => reject(new Error("unreadable picture"));
    reader.readAsDataURL(blob);
  });
}

export async function sendBugReport(
  body: BugReportBody,
  signal?: AbortSignal,
): Promise<BugReportSent> {
  const picture =
    body.picture &&
    (PICTURE_TYPES as readonly string[]).includes(body.picture.blob.type) &&
    body.picture.blob.size <= MAX_PICTURE_BYTES
      ? {
          content_type: body.picture.blob.type,
          data: await base64(body.picture.blob),
          source: body.picture.source,
        }
      : null;
  let response: Response;
  try {
    response = await fetch("/v1/bug-reports", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal,
      headers: {
        accept: "application/json",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        command_id: body.commandId,
        words: body.words,
        blocks_work: body.blocksWork,
        route: body.route,
        context: body.context,
        client_errors: body.errors,
        screenshot: picture,
      }),
    });
  } catch {
    throw new BugReportError(
      "Your report didn't go. Check the connection and send again.",
      0,
    );
  }
  const answer = (await response.json().catch(() => null)) as {
    bug_id?: unknown;
    screenshot?: unknown;
    detail?: unknown;
  } | null;
  if (!response.ok || typeof answer?.bug_id !== "string") {
    const detail =
      typeof answer?.detail === "string" && answer.detail.length < 200
        ? answer.detail
        : null;
    throw new BugReportError(
      detail ??
        FALLBACK[response.status] ??
        "Your report didn't go. Send again in a moment.",
      response.status,
    );
  }
  return {
    bugId: answer.bug_id,
    picture:
      answer.screenshot === "kept" || answer.screenshot === "skipped"
        ? answer.screenshot
        : "none",
  };
}
