"use client";

/**
 * Settings → This phone → Call uploads (SX-AUTOUPLOAD, owner 25 Nov 2026: "auto upload is not working for any of
 * the people who are using it currently ... fix that feature"). Status first (judged design U1 v01-2): whether this
 * phone's lead calls go up by themselves, the last one sent, what waits and what failed with Retry, then the
 * folder, mobile data and older calls. iPhone and Google's Phone app get the plain truth and the way that works.
 * Words and states: call-uploads-rules.ts.
 */
import {
  CircleAlert,
  CircleCheck,
  CircleSlash,
  ChevronRight,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { isIPhoneApp } from "../../in-app";
import {
  askNotifications,
  autoCaptureRetry,
  autoCaptureRetryOne,
  autoCaptureSetup,
  autoCaptureStates,
  autoCaptureStatus,
  inPhoneApp,
  onPhoneSignal,
  pickRecordingsFolder,
  recorderOpen,
  setupOpen,
  setupStatus,
  type AutoCaptureItem,
  type AutoCaptureStatus,
  type SetupStatus,
} from "../../leads/native-phone";
import { notify } from "../../notice-center";
import { OnOff } from "../../organisation/setup/on-off";
import { Button } from "../../ui/kit";
import { AutoAnalysisSheet } from "../auto-analysis-sheet";
import {
  callLine,
  canRetry,
  counts,
  folderLine,
  headline,
  holdWords,
  type Where,
} from "./call-uploads-rules";
import styles from "./call-uploads.module.css";

function whereAmI(): Where {
  if (inPhoneApp()) return "android";
  if (
    typeof navigator !== "undefined" &&
    isIPhoneApp(navigator.userAgent, window)
  )
    return "iphone";
  return "web";
}

export function CallUploads() {
  const [where, setWhere] = useState<Where | null>(null);
  const [status, setStatus] = useState<AutoCaptureStatus | null>(null);
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [items, setItems] = useState<AutoCaptureItem[]>([]);
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const [agreeing, setAgreeing] = useState(false);
  const [shareHelp, setShareHelp] = useState(false);

  const refresh = useCallback(() => {
    void Promise.all([
      autoCaptureStatus(),
      setupStatus(),
      autoCaptureStates(),
    ]).then(([nextStatus, nextSetup, nextItems]) => {
      setStatus(nextStatus);
      setSetup(nextSetup);
      setItems(nextItems);
      setNow(Date.now());
    });
  }, []);

  useEffect(() => {
    // Where this runs is known only in the browser: set on the next task, never synchronously in the effect.
    const known = window.setTimeout(() => setWhere(whereAmI()), 0);
    refresh();
    const tick = window.setInterval(() => setNow(Date.now()), 30_000);
    const off = onPhoneSignal((signal) => {
      if (signal === "resume" || signal === "recordings") refresh();
    });
    return () => {
      window.clearTimeout(known);
      window.clearInterval(tick);
      off();
    };
  }, [refresh]);

  const turnOn = async (wifiOnly: boolean) => {
    setBusy(true);
    try {
      setStatus(await autoCaptureSetup(true, wifiOnly));
    } catch (error) {
      const code = error instanceof Error ? error.message : "";
      if (code === "standing_consent_required") setAgreeing(true);
      else if (code === "profile_required")
        notify({
          id: "call-uploads",
          tone: "error",
          title: "Complete your profile first",
          message:
            "Calls upload only once your profile has your name and phone number.",
        });
      else
        notify({
          id: "call-uploads",
          tone: "error",
          title: "Uploads didn't turn on",
          message:
            "Allow upload notices and check the recordings folder, then try again.",
        });
    } finally {
      setBusy(false);
      refresh();
    }
  };

  if (where === null) return null;
  const top = headline(where, status, setup, now);
  const { today, waiting, failed } = counts(items, now);
  const wifiOnly = status?.wifiOnly ?? false;
  const Icon =
    top.tone === "ok"
      ? CircleCheck
      : top.tone === "blocked"
        ? CircleSlash
        : CircleAlert;

  const act = () => {
    switch (top.action) {
      case "turn_on":
        return void turnOn(wifiOnly);
      case "agree":
        return setAgreeing(true);
      case "notices":
        return void (
          setup?.blocked.notifications
            ? setupOpen("notifications")
            : askNotifications()
        ).then(refresh);
      case "recorder":
        return void recorderOpen("settings");
      case "share_help":
        return setShareHelp((open) => !open);
      default:
        return undefined;
    }
  };
  const actionLabel: Record<string, string> = {
    turn_on: "Turn uploads on",
    agree: "Read and agree",
    notices: "Allow notices",
    recorder: "Open Phone settings",
    share_help: shareHelp ? "Hide the steps" : "Show me how",
  };

  return (
    <div className={styles.screen}>
      <section className={styles.card} data-tone={top.tone} aria-live="polite">
        <div className={styles.head}>
          <Icon className={styles.icon} size={40} aria-hidden="true" />
          <div>
            <h2 className={styles.title}>{top.title}</h2>
            <p className={styles.line}>{top.line}</p>
          </div>
        </div>
        {top.action && actionLabel[top.action] ? (
          <Button variant="primary" disabled={busy} onClick={act}>
            {actionLabel[top.action]}
          </Button>
        ) : null}
        {top.action === "upload" ? (
          <Link className={styles.primaryLink} href="/new-analysis">
            Upload a call
          </Link>
        ) : null}
        {top.action === "open_app" ? (
          <Link className={styles.primaryLink} href="/settings/devices">
            Get the Android app
          </Link>
        ) : null}
        {shareHelp ? (
          <ol className={styles.steps}>
            <li>Open your Phone app and tap Recents.</li>
            <li>Tap the call with your lead, then its recording.</li>
            <li>Tap Share and choose Sales X-Ray.</li>
            <li>
              Sales X-Ray puts it on that lead&apos;s call and analyses it.
            </li>
          </ol>
        ) : null}
        {where === "iphone" ? (
          <ol className={styles.steps}>
            <li>
              iPhone records a call into Notes (iOS 18.1 and later), or use
              Voice Memos for an in-person meeting.
            </li>
            <li>
              In Notes or Voice Memos, tap the recording, then Share → Save to
              Files.
            </li>
            <li>Here, tap Upload a call and pick it from Files.</li>
          </ol>
        ) : null}
        {where === "android" &&
        status?.supported &&
        (top.tone === "ok" || top.tone === "attention") ? (
          <dl className={styles.figures}>
            <div>
              <dt>Sent today</dt>
              <dd data-tone="ok">{today}</dd>
            </div>
            <div>
              <dt>Waiting</dt>
              <dd>{waiting.length}</dd>
            </div>
            <div>
              <dt>Failed</dt>
              <dd data-tone={failed.length ? "bad" : undefined}>
                {failed.length}
              </dd>
            </div>
          </dl>
        ) : null}
      </section>

      {failed.length ? (
        <section className={styles.card} aria-label="Needs you">
          <h3 className={styles.cardTitle}>Needs you</h3>
          <ul className={styles.rows}>
            {failed.map((item) => (
              <li key={item.id ?? item.eventId} className={styles.row}>
                <span
                  className={styles.dot}
                  data-tone="bad"
                  aria-hidden="true"
                />
                <span className={styles.rowText}>
                  <strong>
                    Call with {item.leadName ?? "a lead"} didn&apos;t upload
                  </strong>
                  <small>
                    {[holdWords(item.hold), callLine(item)]
                      .filter(Boolean)
                      .join(" · ")}
                  </small>
                </span>
                {canRetry(item) ? (
                  <Button
                    variant="ghost"
                    disabled={busy}
                    onClick={() =>
                      void autoCaptureRetryOne(item.id as string).then(
                        (next) => {
                          if (next) setStatus(next);
                          refresh();
                        },
                      )
                    }
                  >
                    Retry
                  </Button>
                ) : item.leadId ? (
                  <Link
                    className={styles.rowLink}
                    href={`/leads?lead=${encodeURIComponent(item.leadId)}`}
                  >
                    Open lead
                  </Link>
                ) : null}
              </li>
            ))}
          </ul>
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() =>
              void autoCaptureRetry().then((next) => {
                if (next) setStatus(next);
                refresh();
              })
            }
          >
            Try all again
          </Button>
        </section>
      ) : null}

      {waiting.length ? (
        <section className={styles.card} aria-label="Waiting">
          <h3 className={styles.cardTitle}>Waiting</h3>
          <ul className={styles.rows}>
            {waiting.map((item) => {
              const left = Math.max(
                0,
                Math.ceil(((item.due ?? 0) - now) / 1000),
              );
              return (
                <li key={item.id ?? item.eventId} className={styles.row}>
                  <span
                    className={styles.dot}
                    data-tone="warn"
                    aria-hidden="true"
                  />
                  <span className={styles.rowText}>
                    <strong>Call with {item.leadName ?? "a lead"}</strong>
                    <small>
                      {item.state === "uploading"
                        ? "Uploading now"
                        : left > 0
                          ? `Uploads in ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")} · Undo is in the notice`
                          : "Uploads when the phone has a connection"}
                    </small>
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {where === "android" && status?.supported && top.tone !== "blocked" ? (
        <section className={styles.card} aria-label="Upload settings">
          <h3 className={styles.cardTitle}>Settings</h3>
          <div className={styles.setting}>
            <span className={styles.rowText}>
              <strong>Recordings folder</strong>
              <small>{folderLine(status, setup)}</small>
            </span>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => void pickRecordingsFolder().then(refresh)}
            >
              Change
            </Button>
          </div>
          <div className={styles.setting}>
            <span className={styles.rowText}>
              <strong>Upload on mobile data</strong>
              <small>
                {wifiOnly ? "Off: waits for Wi-Fi" : "On: any network"}
              </small>
            </span>
            <OnOff
              label="Upload on mobile data"
              on={!wifiOnly}
              disabled={busy}
              onChange={(on) => {
                const wifi = !on;
                if (status.on) void turnOn(wifi);
                else setStatus({ ...status, wifiOnly: wifi });
              }}
            />
          </div>
          <Link className={styles.setting} href="/calls#old-calls">
            <span className={styles.rowText}>
              <strong>Find older calls</strong>
              <small>
                Lead calls of the last 30 days recorded on this phone
              </small>
            </span>
            <ChevronRight size={18} aria-hidden="true" />
          </Link>
          {status.on ? (
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setBusy(true);
                void autoCaptureSetup(false, wifiOnly)
                  .then(setStatus)
                  .finally(() => {
                    setBusy(false);
                    refresh();
                  });
              }}
            >
              Turn uploads off
            </Button>
          ) : null}
        </section>
      ) : null}

      <p className={styles.foot}>
        Only calls with your leads are uploaded. Every call shows a 60-second
        Undo first.
      </p>

      <AutoAnalysisSheet
        open={agreeing}
        onClose={() => setAgreeing(false)}
        onSaved={(view) => {
          setAgreeing(false);
          if (view.state !== "on") return;
          // Agreeing again turns this phone back on when the change of terms stopped it (older app builds);
          // newer builds kept uploads on and send the waiting calls by themselves.
          if (status?.supported && !status.on) void turnOn(wifiOnly);
          else void autoCaptureRetry().then(refresh);
        }}
      />
    </div>
  );
}
