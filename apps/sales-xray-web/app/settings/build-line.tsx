"use client";

/**
 * The build this screen runs, as one quiet line at the foot of Help & support
 * (the orchestrator, 3 Nov 2026: phone proof must show the build on screen):
 * the web build's commit and, in the phone app, the app's own version,
 * "Build 3b08990 · App 1.0.84". A long press copies it, for a bug report.
 */

import { useEffect, useRef, useState } from "react";

import { phoneStatus } from "../leads/native-phone";
import { notify } from "../notice-center";
import { releaseLabel } from "../telemetry";
import styles from "./build-line.module.css";

/** A long press, as the phone's own: half a second held. */
const HOLD_MS = 500;

/** "Version 1.53.0 · 3b08990 · App 1.0.84", or "Build 3b08990" while the
 *  release's number isn't known: a commit to its first 7, the app's version
 *  when there is one; "dev" for a build with no release id. */
export function buildLine(
  release: string | null,
  app: string | null,
  version: string | null = null,
): string {
  const build = release
    ? /^[0-9a-f]{12}$/.test(release)
      ? release.slice(0, 7)
      : release
    : "dev";
  const head = version ? `Version ${version} · ${build}` : `Build ${build}`;
  return app ? `${head} · App ${app}` : head;
}

/**
 * The release's number, from the signed manifest of the phone apps' live web
 * updates, when it is this very build (its commit); null otherwise, and on an
 * environment that publishes none (the orchestrator, 10 Nov 2026: support must
 * tell builds apart; Redmi QA on production: no screen showed the version).
 */
export async function readVersion(
  release: string | null,
): Promise<string | null> {
  if (!release || !/^[0-9a-f]{7,}$/.test(release)) return null;
  try {
    const response = await fetch("/v1/app-web/manifest.json", {
      credentials: "same-origin",
      cache: "no-store",
      headers: { accept: "application/json" },
    });
    if (!response.ok) return null;
    const manifest = (await response.json()) as { payload?: unknown };
    if (typeof manifest.payload !== "string") return null;
    const payload = JSON.parse(manifest.payload) as {
      version?: unknown;
      sha?: unknown;
    };
    return typeof payload.version === "string" &&
      typeof payload.sha === "string" &&
      payload.sha.startsWith(release)
      ? payload.version
      : null;
  } catch {
    return null;
  }
}

const failed = () =>
  notify({
    id: "copy",
    tone: "error",
    title: "Couldn’t copy",
    message: "Select the text and copy it yourself.",
  });

export function BuildLine() {
  const [app, setApp] = useState<string | null>(null);
  const [version, setVersion] = useState<string | null>(null);
  const release = releaseLabel(process.env.NEXT_PUBLIC_AC_RELEASE_ID);
  useEffect(() => {
    let alive = true;
    void readVersion(release).then((found) => {
      if (alive) setVersion(found);
    });
    return () => {
      alive = false;
    };
  }, [release]);
  const [copied, setCopied] = useState(false);
  const hold = useRef<number | undefined>(undefined);
  const touch = useRef(false);
  useEffect(() => {
    let alive = true;
    void phoneStatus().then((status) => {
      if (alive && status?.version) setApp(status.version);
    });
    return () => {
      alive = false;
    };
  }, []);
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);
  useEffect(() => () => window.clearTimeout(hold.current), []);
  const line = buildLine(release, app, version);
  const copy = () => {
    const done = navigator.clipboard?.writeText(line);
    if (!done) return failed();
    void done.then(() => setCopied(true), failed);
  };
  const letGo = () => window.clearTimeout(hold.current);
  return (
    <p
      className={styles.line}
      aria-live="polite"
      onPointerDown={(event) => {
        touch.current = event.pointerType === "touch";
        letGo();
        hold.current = window.setTimeout(copy, HOLD_MS);
      }}
      onPointerUp={letGo}
      onPointerLeave={letGo}
      onPointerCancel={letGo}
      // A held finger copies; the phone's own selection menu stays away.
      onContextMenu={(event) => {
        if (touch.current) event.preventDefault();
      }}
    >
      {copied ? "Copied" : line}
    </p>
  );
}
