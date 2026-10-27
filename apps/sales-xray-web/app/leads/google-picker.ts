/**
 * Google's Picker for one spreadsheet (Lead OS, slice 1, 27 Oct 2026). It shows
 * only spreadsheets; what is picked is the one file Sales X-Ray may read
 * (drive.file). It needs a real browser page: the phone app opens it there.
 */

import { readPickerSetup } from "./google-files-client";

type PickerData = { action: string; docs?: { id?: string }[] };
type PickerBuilder = {
  addView(view: unknown): PickerBuilder;
  setOAuthToken(token: string): PickerBuilder;
  setDeveloperKey(key: string): PickerBuilder;
  setAppId(id: string): PickerBuilder;
  setCallback(callback: (data: PickerData) => void): PickerBuilder;
  build(): { setVisible(visible: boolean): void };
};
type PickerApi = {
  PickerBuilder: new () => PickerBuilder;
  ViewId: { SPREADSHEETS: unknown };
  Action: { PICKED: string; CANCEL: string };
};
type GoogleWindow = Window & {
  gapi?: {
    load(
      name: string,
      options: { callback: () => void; onerror?: () => void },
    ): void;
  };
  google?: { picker?: PickerApi };
};

export const PICKER_SCRIPT = "https://apis.google.com/js/api.js";
export const PICKER_FAILED = "Google's file picker didn't open. Try again.";

let loading: Promise<void> | null = null;

function loadScript(): Promise<void> {
  loading ??= new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = PICKER_SCRIPT;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      loading = null;
      script.remove();
      reject(new Error(PICKER_FAILED));
    };
    document.head.append(script);
  });
  return loading;
}

/** The picked spreadsheet's id, or null when the Picker was closed. */
export async function pickGoogleSheet(): Promise<string | null> {
  const setup = await readPickerSetup();
  await loadScript();
  const win = window as GoogleWindow;
  const gapi = win.gapi;
  if (!gapi) throw new Error(PICKER_FAILED);
  await new Promise<void>((resolve, reject) =>
    gapi.load("picker", {
      callback: resolve,
      onerror: () => reject(new Error(PICKER_FAILED)),
    }),
  );
  const api = win.google?.picker;
  if (!api) throw new Error(PICKER_FAILED);
  return new Promise<string | null>((resolve) => {
    new api.PickerBuilder()
      .addView(api.ViewId.SPREADSHEETS)
      .setOAuthToken(setup.access_token)
      .setDeveloperKey(setup.api_key)
      .setAppId(setup.app_id)
      .setCallback((data) => {
        if (data.action === api.Action.PICKED)
          resolve(data.docs?.[0]?.id ?? null);
        else if (data.action === api.Action.CANCEL) resolve(null);
      })
      .build()
      .setVisible(true);
  });
}
