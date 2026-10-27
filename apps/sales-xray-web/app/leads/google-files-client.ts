/**
 * Google Sheets and Drive (Lead OS, slice 1, 27 Oct 2026;
 * docs/product/lead-desk/google-sheets-drive.md): whether Google is connected
 * and by whom, the copy of new leads kept in a Sheet of the organisation's own,
 * and the Picker's setup for importing a Sheet someone picks. With the
 * drive.file permission Sales X-Ray sees only the files picked there and the
 * ones it creates. Owners and admins only: anyone else is answered 403.
 */

import type { ImportPreview } from "./leads-client";

const BASE = "/v1/lead-desk";

/** The full-page trip to Google (the phone app opens it in the browser). */
export const GOOGLE_FILES_CONNECT = `${BASE}/google/files/connect`;

export type SheetCopy = Readonly<{
  on: boolean;
  /** The Sheet, to open it. */
  url: string | null;
  /** Leads written to it so far. */
  sent: number;
  last_sent_at: string | null;
  /** Why the last send didn't work, in plain words. */
  problem: string | null;
}>;

export type GoogleFiles = Readonly<{
  /** Set up on this server; false: "Coming soon". */
  configured: boolean;
  /** The Picker is set up, so a Sheet can be imported. */
  picker: boolean;
  connected: boolean;
  email: string | null;
  /** Who connected it. */
  connected_by: string | null;
  /** The organisation's "Sales X-Ray · <name>" folder in Drive. */
  folder_url: string | null;
  copy: SheetCopy | null;
}>;

export type PickerSetup = Readonly<{
  client_id: string;
  api_key: string;
  app_id: string;
  /** Lasts about an hour. */
  access_token: string;
}>;

export class GoogleFilesError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "GoogleFilesError";
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    ...init,
    headers: {
      accept: "application/json",
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // No body: the status says enough.
    }
    throw new GoogleFilesError(
      detail ?? "That didn't work. Try again.",
      response.status,
    );
  }
  return (await response.json()) as T;
}

export const readGoogleFiles = (signal?: AbortSignal) =>
  call<GoogleFiles>("/google/files", { signal });

/** Google is asked to forget the grant; a kept Sheet stays the client's. */
export const disconnectGoogleFiles = () =>
  call<GoogleFiles>("/google/files/disconnect", { method: "POST" });

/** Every new lead from now on is added to a Sheet in the organisation's Drive. */
export const keepSheetCopy = () =>
  call<GoogleFiles>("/google/sheet-copy", { method: "POST" });

/** No more rows; the Sheet itself stays. */
export const stopSheetCopy = () =>
  call<GoogleFiles>("/google/sheet-copy", { method: "DELETE" });

/** 409 when Google isn't connected or the Picker isn't set up. */
export const readPickerSetup = () => call<PickerSetup>("/google/picker");

/** A picked Sheet read into the same preview a file gets. */
export const previewGoogleSheet = (spreadsheetId: string, tab?: string) =>
  call<ImportPreview>("/imports/google-sheet", {
    method: "POST",
    body: JSON.stringify(
      tab
        ? { spreadsheet_id: spreadsheetId, tab }
        : { spreadsheet_id: spreadsheetId },
    ),
  });
