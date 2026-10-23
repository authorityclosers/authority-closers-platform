/**
 * Sending a bug report: POST /v1/bug-reports and GET /v1/bug-reports/mine
 * (ac_platform/bug_reports/http.py). The request is built once, so a report
 * that waits in the outbox (no connection) is sent later exactly as it was.
 */

import type { ReportContext } from "./device";
import type { RecentError } from "./recent-errors";

export type ReportPicture = Readonly<{
  blob: Blob;
  source: "auto" | "upload";
}>;

export type ReportVoice = Readonly<{
  blob: Blob;
  seconds: number;
}>;

export type BugReportBody = Readonly<{
  commandId: string;
  words: string;
  blocksWork: boolean;
  route: string;
  context: ReportContext;
  errors: readonly RecentError[];
  picture: ReportPicture | null;
  voice?: ReportVoice | null;
}>;

export type BugReportSent = Readonly<{
  bugId: string;
  picture: "kept" | "skipped" | "none";
  voice: "kept" | "skipped" | "none";
}>;

export type MyReport = Readonly<{
  bugId: string;
  createdAt: string;
  words: string;
  status: string;
  statusAt: string;
}>;

export const PICTURE_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;
export const VOICE_TYPES = ["audio/webm", "audio/ogg", "audio/mp4"] as const;
export const MAX_PICTURE_BYTES = 4 * 1024 * 1024;
export const MAX_VOICE_BYTES = 1536 * 1024;

export class BugReportError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "BugReportError";
  }
}

/** True when the report can wait and go later (no connection, server busy). */
export function retryLater(error: unknown): boolean {
  return (
    error instanceof BugReportError &&
    (error.status === 0 || error.status === 408 || error.status >= 500)
  );
}

const FALLBACK: Record<number, string> = {
  401: "Sign in again, then send your report.",
  403: "Reload this page, then send your report.",
  413: "That picture is too large. Send it without the picture.",
  429: "That's a lot of reports in an hour. Send again a little later.",
};

export function base64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const url = String(reader.result ?? "");
      resolve(url.slice(url.indexOf(",") + 1));
    };
    reader.onerror = () => reject(new Error("unreadable file"));
    reader.readAsDataURL(blob);
  });
}

/** The JSON the server takes; built once and kept as is when it has to wait. */
export async function bugReportRequest(
  body: BugReportBody,
): Promise<Record<string, unknown>> {
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
  const voiceType = body.voice?.blob.type.split(";")[0] ?? "";
  const voice =
    body.voice &&
    (VOICE_TYPES as readonly string[]).includes(voiceType) &&
    body.voice.blob.size <= MAX_VOICE_BYTES
      ? {
          content_type: voiceType,
          data: await base64(body.voice.blob),
          seconds: Math.min(120, Math.max(1, Math.round(body.voice.seconds))),
        }
      : null;
  return {
    command_id: body.commandId,
    words: body.words,
    blocks_work: body.blocksWork,
    route: body.route,
    context: body.context,
    client_errors: body.errors,
    screenshot: picture,
    voice,
  };
}

async function call(
  path: string,
  init: RequestInit,
  signal?: AbortSignal,
): Promise<{ status: number; answer: Record<string, unknown> | null }> {
  let response: Response;
  try {
    response = await fetch(path, {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal,
      ...init,
      headers: { accept: "application/json", ...(init.headers ?? {}) },
    });
  } catch {
    throw new BugReportError(
      "Your report didn't go. Check the connection and send again.",
      0,
    );
  }
  const answer = (await response.json().catch(() => null)) as Record<
    string,
    unknown
  > | null;
  if (!response.ok) {
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
  return { status: response.status, answer };
}

const kept = (value: unknown) =>
  value === "kept" || value === "skipped" ? value : "none";

/** POST a request built by bugReportRequest. */
export async function postBugReport(
  request: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<BugReportSent> {
  const { answer } = await call(
    "/v1/bug-reports",
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(request),
    },
    signal,
  );
  if (typeof answer?.bug_id !== "string") {
    throw new BugReportError(
      "Your report didn't go. Send again in a moment.",
      0,
    );
  }
  return {
    bugId: answer.bug_id,
    picture: kept(answer.screenshot),
    voice: kept(answer.voice),
  };
}

export async function sendBugReport(
  body: BugReportBody,
  signal?: AbortSignal,
): Promise<BugReportSent> {
  return postBugReport(await bugReportRequest(body), signal);
}

/** The person's own newest reports and where each stands. */
export async function myReports(signal?: AbortSignal): Promise<MyReport[]> {
  const { answer } = await call(
    "/v1/bug-reports/mine",
    { method: "GET" },
    signal,
  );
  const items = Array.isArray(answer?.items) ? answer.items : [];
  return items.flatMap((item) => {
    const row = item as Record<string, unknown>;
    return typeof row.bug_id === "string" && typeof row.status === "string"
      ? [
          {
            bugId: row.bug_id,
            createdAt: String(row.created_at ?? ""),
            words: String(row.words ?? ""),
            status: row.status,
            statusAt: String(row.status_at ?? row.created_at ?? ""),
          },
        ]
      : [];
  });
}
