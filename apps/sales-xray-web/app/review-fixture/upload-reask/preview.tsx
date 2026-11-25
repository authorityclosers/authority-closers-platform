"use client";

/**
 * Review fixture: "Your call wasn't checked" (upload-reask.tsx) as the phone
 * app shows it, in a browser. A stand-in phone bridge says uploads are off and
 * answers each step; a stand-in server read names one lead call that ended
 * 25 minutes ago with no recording. Fictional names only. ?step=1 opens the
 * first step, ?done=1 shows the end card as if uploads turned on.
 */

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { CAPTURE_SETUP_PATH } from "../../capture-setup/capture-setup-client";
import { applyTheme } from "../../lightbox/theme";
import { UploadReask } from "../../shell/upload-reask";

const ACCOUNT = "review-fixture";
let uploadsOn = false;

function installPhone(): void {
  const target = globalThis as {
    SXPhone?: unknown;
    __sxReaskFetch?: typeof fetch;
  };
  if (target.SXPhone) return;
  const listeners: ((event: { data: unknown }) => void)[] = [];
  const answers: Record<string, () => unknown> = {
    autoCaptureStatus: () => ({
      supported: true,
      on: uploadsOn,
      wifiOnly: false,
    }),
    setupStatus: () => null,
    askNotifications: () => null,
    pickRecordingsFolder: () => null,
    autoCaptureSetup: () => {
      uploadsOn = true;
      return { supported: true, on: true, wifiOnly: false };
    },
  };
  target.SXPhone = {
    postMessage(data: string) {
      const { id, method } = JSON.parse(data) as { id: string; method: string };
      const answer = answers[method];
      window.setTimeout(() => {
        const reply = answer
          ? { id, ok: true, result: answer() }
          : { id, ok: false, error: "unknown_method" };
        listeners.forEach((listener) =>
          listener({ data: JSON.stringify(reply) }),
        );
      }, 30);
    },
    addEventListener(
      _type: "message",
      listener: (event: { data: unknown }) => void,
    ) {
      listeners.push(listener);
    },
  };
  const realFetch = window.fetch.bind(window);
  target.__sxReaskFetch = realFetch;
  window.fetch = async (input, init) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    if (url.startsWith(`${CAPTURE_SETUP_PATH}/missing`)) {
      const at = new Date(Date.now() - 27 * 60 * 1000).toISOString();
      return new Response(
        JSON.stringify({
          schema: "sales-xray-missing-recordings/1",
          calls: 1,
          tried: 0,
          latest_at: at,
          items: [
            {
              event_id: "fixture-call-1",
              lead_id: "fixture-lead-1",
              lead_name: "Asha Example",
              at,
              seconds: 134,
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    return realFetch(input, init);
  };
}

export function UploadReaskPreview() {
  const params = useSearchParams();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const root = document.documentElement;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    applyTheme(root, "system", query.matches ? "dark" : "light");
    try {
      window.localStorage.removeItem(
        `sales-xray:upload-reask-shown:${ACCOUNT}`,
      );
    } catch {
      // A fresh look each load; without storage it shows anyway.
    }
    uploadsOn = false;
    installPhone();
    setReady(true);
  }, []);
  // Walk to the asked stage by pressing the card's own buttons.
  useEffect(() => {
    if (!ready) return;
    const want = params.get("done")
      ? "done"
      : params.get("step")
        ? "step"
        : null;
    if (!want) return;
    const timer = window.setInterval(() => {
      const press = (label: string) =>
        Array.from(
          document.querySelectorAll<HTMLButtonElement>(
            "dialog[data-upload-reask] button",
          ),
        )
          .find(
            (button) =>
              button.textContent?.trim() === label && !button.disabled,
          )
          ?.click();
      const dialog = document.querySelector("dialog[data-upload-reask]");
      if (!dialog) return;
      const text = dialog.textContent ?? "";
      if (text.includes("Call not checked"))
        return void press("Turn uploads on");
      if (want === "step") return window.clearInterval(timer);
      if (text.includes("Uploads are on")) return window.clearInterval(timer);
      const step = dialog.querySelector("h2")?.textContent ?? "";
      press(
        step === "Upload notices"
          ? "Allow notices"
          : step === "Recordings folder"
            ? "Choose the folder"
            : "Turn uploads on",
      );
    }, 400);
    return () => window.clearInterval(timer);
  }, [ready, params]);
  return (
    <main style={{ padding: "24px 16px" }}>
      <h1
        style={{
          margin: 0,
          font: "700 20px/28px var(--lx-font-ui)",
          color: "var(--lx-ink)",
        }}
      >
        Leads
      </h1>
      <p style={{ color: "var(--lx-ink-3)" }}>
        The phone app, behind the card.
      </p>
      {ready ? (
        <UploadReask accountKey={ACCOUNT} openLead={() => undefined} />
      ) : null}
    </main>
  );
}
