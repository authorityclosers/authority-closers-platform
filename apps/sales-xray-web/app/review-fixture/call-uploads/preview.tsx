"use client";

/**
 * Review fixture: Settings → This phone → Call uploads (SX-AUTOUPLOAD, 25 Nov 2026) as the phone app shows it, in a
 * browser. A stand-in phone bridge answers with one of these states (?view=): ok (default: uploading, one failed,
 * one waiting), terms (stopped by new upload terms), private (Google's Phone app), off (uploads off), recording
 * (the dialer isn't recording). Fictional names only.
 */
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { applyTheme } from "../../lightbox/theme";
import { CallUploads } from "../../settings/call-uploads/call-uploads";

type View = "ok" | "terms" | "private" | "off" | "recording";

function answers(view: View): Record<string, () => unknown> {
  const now = Date.now();
  const status = {
    supported: true,
    on: view !== "off" && view !== "terms",
    wifiOnly: false,
    health: view === "terms" ? "consent" : view === "off" ? "off" : "ok",
    pending: 1,
    lastUploadAt: now - 4 * 60_000,
    lastUploadLead: "Rohan Deshmukh",
    lastScanAt: now - 60_000,
    failed: 1,
    folders: ["MIUI/sound_recorder/call_rec"],
    callLogMatch: true,
  };
  const recorder = {
    kind: view === "private" ? "private" : "folder",
    maker: view === "private" ? "google" : "xiaomi",
    dialerLabel: view === "private" ? "Phone by Google" : "Phone",
    recording:
      view === "recording" ? "off" : view === "private" ? "private" : "on",
    folders: [
      { path: "MIUI/sound_recorder/call_rec", state: "found", recordings: 12 },
    ],
    switchTo: null,
  };
  const items =
    view === "ok"
      ? [
          {
            eventId: "e1",
            id: "j1",
            state: "analysing",
            leadName: "Rohan Deshmukh",
            uploadedAt: now - 4 * 60_000,
            stamp: now - 12 * 60_000,
            seconds: 312,
          },
          {
            eventId: "e2",
            id: "j2",
            state: "report_ready",
            leadName: "Aakash Mehta",
            uploadedAt: now - 70 * 60_000,
            stamp: now - 80 * 60_000,
            seconds: 188,
          },
          {
            eventId: "e3",
            id: "j3",
            state: "held",
            hold: "network",
            leadName: "Sanjay Patil",
            stamp: now - 3 * 3_600_000,
            seconds: 365,
          },
          {
            eventId: "e4",
            id: "j4",
            state: "waiting",
            leadName: "Neha Joshi",
            due: now + 42_000,
            stamp: now - 90_000,
            seconds: 140,
          },
        ]
      : [];
  return {
    autoCaptureStatus: () => status,
    setupStatus: () => ({
      checks: {},
      family: "xiaomi",
      model: "Redmi 13",
      autostartNeeded: false,
      version: "1.0.160",
      device: "fixture",
      recorderProfile: recorder,
      needsAllFiles: false,
      allFilesSupported: false,
      folderPickSupported: true,
      folderPicked: true,
      truecaller: false,
      callLogSupported: true,
      store: "play",
      blocked: {
        calls: false,
        notifications: false,
        recordings: false,
        microphone: false,
      },
    }),
    autoCaptureStates: () => ({ items }),
    autoCaptureRetry: () => status,
    autoCaptureRetryOne: () => status,
    autoCaptureSetup: () => ({ ...status, on: true, health: "ok" }),
    pickRecordingsFolder: () => null,
    askNotifications: () => null,
    recorderOpen: () => true,
  };
}

function installPhone(view: View): void {
  const target = globalThis as { SXPhone?: unknown };
  if (target.SXPhone) return;
  const listeners: ((event: { data: unknown }) => void)[] = [];
  const table = answers(view);
  target.SXPhone = {
    postMessage(data: string) {
      const { id, method } = JSON.parse(data) as { id: string; method: string };
      const answer = table[method];
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
}

export function CallUploadsPreview() {
  const params = useSearchParams();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const root = document.documentElement;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    applyTheme(root, "system", query.matches ? "dark" : "light");
    const asked = params.get("view");
    const view: View =
      asked === "terms" ||
      asked === "private" ||
      asked === "off" ||
      asked === "recording"
        ? asked
        : "ok";
    installPhone(view);
    // The screen mounts once the stand-in phone is in place (next task, not in the effect).
    const timer = window.setTimeout(() => setReady(true), 0);
    return () => window.clearTimeout(timer);
  }, [params]);
  if (!ready) return null;
  return (
    <main
      style={{
        maxWidth: 420,
        margin: "0 auto",
        padding: 16,
        background: "var(--sx-page, #f0f2f6)",
        minHeight: "100vh",
      }}
    >
      <h1
        style={{
          fontSize: 20,
          fontWeight: 500,
          margin: "4px 0 16px",
          color: "var(--sx-ink)",
        }}
      >
        Call uploads
      </h1>
      <CallUploads />
    </main>
  );
}
