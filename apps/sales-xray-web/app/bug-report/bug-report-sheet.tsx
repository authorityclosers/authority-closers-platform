"use client";

/**
 * Report a problem (owner, 23 Oct 2026: "bug catcher for everyone ... with the
 * greatest UX UI so any user can get that done").
 *
 * For every signed-in person, from any screen: You (the avatar on phones, the
 * gear on computers) → Report a problem; the command bar; Report on any error
 * corner card; and in the phone app, a shake. One sheet, one job, one primary
 * action at each step:
 * - Write: what went wrong (a draft survives closing), "This stops my work",
 *   a picture of the screen taken on the device as the sheet opens (shown
 *   before it goes; none on screens with call details or messages) or one they
 *   choose, which they can mark up or blur, and an optional voice note. With
 *   it, quietly: the screen, app and device, and recent errors (scrubbed,
 *   never call content). Primary: "Send report".
 * - Mark up: draw or blur on the picture, a step inside the sheet.
 * - Sent: "We'll tell you when it's fixed", or, with no connection, "Saved on
 *   this phone, it goes when you're back online".
 * - Your reports: what they sent and where each stands.
 * A failure that cannot wait is a corner card with Send again; the sheet
 * keeps everything.
 */

import {
  Bug,
  Camera,
  CheckCircle2,
  CloudOff,
  ImagePlus,
  PenLine,
  TriangleAlert,
  Vibrate,
  X,
} from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { postFeedbackRequest } from "../feedback/feedback-client";
import { useInApp } from "../in-app-client";
import { askScreenshot, inPhoneApp } from "../leads/native-phone";
import { notify } from "../notice-center";
import { useCommandSource } from "../ui/command-registry";
import { tick } from "../ui/haptics";
import { Button } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import {
  BugReportError,
  MAX_PICTURE_BYTES,
  PICTURE_TYPES,
  bugReportRequest,
  myReports,
  postBugReport,
  retryLater,
  type MyReport,
  type ReportPicture,
} from "./bug-report-client";
import styles from "./bug-report.module.css";
import { captureScreen } from "./capture";
import { commandId } from "./command-id";
import { reportContext } from "./device";
import { MarkupEditor } from "./markup";
import { STATUS_WORDS, lookForFixes, rememberSent } from "./my-reports";
import {
  REPORT_PROBLEM_EVENT,
  openBugReport,
  reporterMounted,
  takeWaitingReport,
  type ReportAbout,
} from "./open";
import { flush, keepNow, type OutboxItem } from "./outbox";
import { recentErrors } from "./recent-errors";
import { scrubRoute } from "./scrub";
import { setShakeToReport, useShakeSetting, useShakeToReport } from "./shake";
import { VoiceNoteRow, type VoiceNote } from "./voice-note";

/** Screens that can show call details or messages: no picture unless chosen. */
const PRIVATE_SCREENS = [
  /^\/analysis\/calls\/[^/]+/,
  /^\/chats(?:\/|$)/,
  /^\/review(?:\/|$)/,
];

export function privateScreen(path: string): boolean {
  return PRIVATE_SCREENS.some((pattern) => pattern.test(path));
}

type Picture =
  | { state: "none" }
  | { state: "taking" }
  | { state: "failed" }
  | { state: "ready"; picture: ReportPicture; url: string; marked: boolean };

type Step = "write" | "markup" | "sent" | "mine";
type Outcome = "sent" | "queued";

// What was typed stays for the next opening until it is sent.
const draft = { words: "", blocksWork: false };
function keepDraft(words: string, blocksWork: boolean) {
  draft.words = words;
  draft.blocksWork = blocksWork;
}

const TITLES: Record<Step, string> = {
  write: "Report a problem",
  markup: "Mark up the picture",
  sent: "Thanks for telling us",
  mine: "Your reports",
};

function when(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const days = Math.floor((Date.now() - at.getTime()) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return at.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function MyReportsList() {
  const [items, setItems] = useState<MyReport[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    myReports(controller.signal)
      .then(setItems)
      .catch(() => setFailed(true));
    return () => controller.abort();
  }, []);
  if (failed) {
    return (
      <p className={styles.fine} role="status">
        Your reports can&apos;t load right now. Try again in a moment.
      </p>
    );
  }
  if (items === null) {
    return (
      <div className={styles.mine} aria-busy="true">
        {[0, 1, 2].map((key) => (
          <span key={key} className={styles.mineSkeleton} />
        ))}
      </div>
    );
  }
  if (!items.length) {
    return (
      <p className={styles.fine}>
        Nothing sent yet. When something goes wrong, report it here and
        we&apos;ll tell you when it&apos;s fixed.
      </p>
    );
  }
  return (
    <ul className={styles.mine}>
      {items.map((item) => (
        <li key={item.bugId} className={styles.mineRow}>
          <span className={styles.mineWords}>{item.words}</span>
          <span className={styles.mineMeta}>
            <span className={styles.status} data-status={item.status}>
              {STATUS_WORDS[item.status] ?? "Sent"}
            </span>
            <small>{when(item.statusAt)}</small>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function BugReportSheet({
  open,
  about,
  preset = null,
  onClose,
}: {
  open: boolean;
  about: ReportAbout | null;
  /** A picture the phone app took of the screen before the sheet opened. */
  preset?: Blob | null;
  onClose: () => void;
}) {
  const inApp = useInApp();
  const shakeOn = useShakeSetting();
  const [words, setWords] = useState(draft.words);
  const [blocksWork, setBlocksWork] = useState(draft.blocksWork);
  const [picture, setPicture] = useState<Picture>({ state: "none" });
  const [voice, setVoice] = useState<VoiceNote | null>(null);
  const [include, setInclude] = useState(true);
  const [sensitive, setSensitive] = useState(false);
  const [sending, setSending] = useState(false);
  const [pictureNote, setPictureNote] = useState<string | null>(null);
  const [route, setRoute] = useState("/");
  const [step, setStep] = useState<Step>("write");
  const [outcome, setOutcome] = useState<Outcome>("sent");
  const [shownOpen, setShownOpen] = useState(false);
  const command = useRef(commandId());
  const fileInput = useRef<HTMLInputElement>(null);
  const textArea = useRef<HTMLTextAreaElement>(null);
  const opening = useRef(0);
  const wordsId = useId();
  const formId = useId();

  // Each opening notes the screen it opened on (state follows the open prop).
  if (open !== shownOpen) {
    setShownOpen(open);
    if (open) {
      const path = window.location.pathname;
      const hidden = privateScreen(path);
      setRoute(scrubRoute(path + window.location.search));
      setSensitive(hidden);
      setInclude(!hidden);
      setPictureNote(null);
      setStep("write");
      setPicture(hidden ? { state: "none" } : { state: "taking" });
    }
  }

  // Then the picture is taken once the sheet is up, and the words get focus.
  useEffect(() => {
    if (!open) return;
    const round = (opening.current += 1);
    const focus = window.setTimeout(() => textArea.current?.focus(), 320);
    if (sensitive) return () => window.clearTimeout(focus);
    // The phone app's own picture when it took one; otherwise a copy of the page.
    const start = window.setTimeout(
      () => {
        void (preset ? Promise.resolve(preset) : captureScreen()).then(
          (blob) => {
            if (round !== opening.current) return;
            setPicture(
              blob
                ? {
                    state: "ready",
                    picture: { blob, source: "auto" },
                    url: URL.createObjectURL(blob),
                    marked: false,
                  }
                : { state: "failed" },
            );
          },
        );
      },
      preset ? 0 : 360,
    );
    return () => {
      window.clearTimeout(focus);
      window.clearTimeout(start);
    };
  }, [open, sensitive, preset]);

  // A picture's address is released when it is replaced or the sheet closes.
  useEffect(() => {
    const url = picture.state === "ready" ? picture.url : null;
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [picture]);

  const choose = (file: File | undefined) => {
    if (!file) return;
    if (!(PICTURE_TYPES as readonly string[]).includes(file.type)) {
      setPictureNote("Choose a PNG, JPG or WebP picture.");
      return;
    }
    if (file.size > MAX_PICTURE_BYTES) {
      setPictureNote("Choose a picture under 4 MB.");
      return;
    }
    setPictureNote(null);
    setInclude(true);
    setPicture({
      state: "ready",
      picture: { blob: file, source: "upload" },
      url: URL.createObjectURL(file),
      marked: false,
    });
  };

  const cleared = () => {
    keepDraft("", false);
    setWords("");
    setBlocksWork(false);
    setVoice(null);
    command.current = commandId();
  };

  const send = async () => {
    const text = words.trim();
    if (!text || sending) return;
    setSending(true);
    const id = command.current;
    let request: Record<string, unknown> | null = null;
    try {
      request = await bugReportRequest({
        commandId: id,
        words: about
          ? `${text}\n\n(About: ${about.title}${about.reference ? `, ref ${about.reference}` : ""})`
          : text,
        blocksWork,
        route,
        context: await reportContext(),
        errors: recentErrors(),
        picture: include && picture.state === "ready" ? picture.picture : null,
        voice: voice ? { blob: voice.blob, seconds: voice.seconds } : null,
      });
      const sent = await postBugReport(request);
      rememberSent(sent.bugId);
      tick();
      cleared();
      setOutcome("sent");
      setStep("sent");
      if (sent.picture === "skipped" || sent.voice === "skipped") {
        notify({
          id: "bug-report-partial",
          tone: "info",
          title: "Your report went without one part",
          message:
            sent.picture === "skipped"
              ? "The picture didn't go with it."
              : "The voice note didn't go with it.",
        });
      }
    } catch (error) {
      // No connection: it waits on this phone and goes by itself later.
      if (request && retryLater(error) && (await keepNow("bug", id, request))) {
        tick();
        cleared();
        setOutcome("queued");
        setStep("sent");
      } else {
        notify({
          id: "bug-report-failed",
          tone: "error",
          title: "Your report didn't go",
          message:
            error instanceof BugReportError
              ? error.message
              : "Send again in a moment.",
          action: { label: "Send again", run: () => void send() },
          noReport: true,
        });
      }
    } finally {
      setSending(false);
    }
  };

  const ready = picture.state === "ready";
  const footer =
    step === "write" ? (
      <>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="primary"
          type="submit"
          form={formId}
          disabled={!words.trim() || sending}
          aria-busy={sending || undefined}
        >
          {sending ? "Sending…" : "Send report"}
        </Button>
      </>
    ) : step === "sent" ? (
      <>
        <Button onClick={() => setStep("mine")}>Your reports</Button>
        <Button variant="primary" onClick={onClose}>
          Done
        </Button>
      </>
    ) : step === "mine" ? (
      <>
        <Button onClick={() => setStep("write")}>Report a problem</Button>
        <Button variant="primary" onClick={onClose}>
          Done
        </Button>
      </>
    ) : undefined;

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={TITLES[step]}
      description={
        step === "write"
          ? "Tell us what went wrong. The team gets it straight away."
          : undefined
      }
      wide="center"
      footer={footer}
    >
      {step === "markup" && ready ? (
        <MarkupEditor
          source={picture.picture.blob}
          onCancel={() => setStep("write")}
          onDone={(marked) => {
            setPicture({
              state: "ready",
              picture: { blob: marked, source: picture.picture.source },
              url: URL.createObjectURL(marked),
              marked: true,
            });
            setInclude(true);
            setStep("write");
          }}
        />
      ) : step === "sent" ? (
        <div className={styles.sent} role="status">
          <span
            className={styles.sentIcon}
            data-outcome={outcome}
            aria-hidden="true"
          >
            {outcome === "sent" ? (
              <CheckCircle2 size={28} />
            ) : (
              <CloudOff size={26} />
            )}
          </span>
          <strong>
            {outcome === "sent"
              ? "Sent. We'll tell you when it's fixed."
              : "Saved on this phone."}
          </strong>
          <p>
            {outcome === "sent"
              ? "The team sees it now. When it's fixed, a note appears here in the app."
              : "It goes by itself as soon as you're back online. You can keep working."}
          </p>
        </div>
      ) : step === "mine" ? (
        <MyReportsList />
      ) : (
        <form
          id={formId}
          className={styles.form}
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          {about ? (
            <p className={styles.about}>
              <TriangleAlert size={15} aria-hidden="true" />
              <span>About: {about.title}</span>
            </p>
          ) : null}
          <label className={styles.field} htmlFor={wordsId}>
            <span className={styles.label}>What went wrong?</span>
            <textarea
              id={wordsId}
              ref={textArea}
              className={styles.words}
              value={words}
              rows={4}
              maxLength={4000}
              autoCapitalize="sentences"
              placeholder="What did you do, and what happened instead?"
              onChange={(event) => {
                setWords(event.target.value);
                keepDraft(event.target.value, blocksWork);
              }}
            />
          </label>
          <div className={styles.chips}>
            <button
              type="button"
              className={styles.chip}
              aria-pressed={blocksWork}
              onClick={() => {
                tick();
                setBlocksWork(!blocksWork);
                keepDraft(words, !blocksWork);
              }}
            >
              <TriangleAlert size={15} aria-hidden="true" />
              This stops my work
            </button>
            <VoiceNoteRow note={voice} onChange={setVoice} />
          </div>
          <div className={styles.picture} data-state={picture.state}>
            {ready && include ? (
              <>
                <button
                  type="button"
                  className={styles.thumbButton}
                  aria-label="Mark up or blur the picture"
                  onClick={() => setStep("markup")}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element -- a local blob preview */}
                  <img
                    className={styles.thumb}
                    src={picture.url}
                    alt="Picture of the screen that goes with your report"
                  />
                </button>
                <div className={styles.pictureWords}>
                  <strong>
                    {picture.picture.source === "auto"
                      ? "Picture of this screen"
                      : "Your picture"}
                  </strong>
                  <button
                    type="button"
                    className={styles.inlineAction}
                    onClick={() => setStep("markup")}
                  >
                    <PenLine size={13} aria-hidden="true" />
                    {picture.marked ? "Marked up · change" : "Mark up or blur"}
                  </button>
                </div>
                <button
                  type="button"
                  className={styles.remove}
                  aria-label="Leave the picture out"
                  onClick={() => setInclude(false)}
                >
                  <X size={16} aria-hidden="true" />
                </button>
              </>
            ) : picture.state === "taking" ? (
              <>
                <span className={styles.thumbLoading} aria-hidden="true" />
                <div className={styles.pictureWords}>
                  <strong>Taking a picture of this screen…</strong>
                  <small>You can start typing.</small>
                </div>
              </>
            ) : (
              <>
                <span className={styles.thumbEmpty} aria-hidden="true">
                  <Camera size={18} />
                </span>
                <div className={styles.pictureWords}>
                  <strong>No picture</strong>
                  <small>
                    {picture.state === "failed"
                      ? "Couldn't take one here. Choose a picture instead."
                      : sensitive && !ready
                        ? "This screen can show call details or messages, so no picture is taken."
                        : "Choose a picture if it helps."}
                  </small>
                </div>
                {ready ? (
                  <Button variant="ghost" onClick={() => setInclude(true)}>
                    Add it back
                  </Button>
                ) : null}
              </>
            )}
          </div>
          <div className={styles.chips}>
            <button
              type="button"
              className={styles.chip}
              onClick={() => fileInput.current?.click()}
            >
              <ImagePlus size={15} aria-hidden="true" />
              {ready && picture.picture.source === "upload"
                ? "Choose another picture"
                : "Choose a picture"}
            </button>
            <input
              ref={fileInput}
              className={styles.file}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              tabIndex={-1}
              aria-hidden="true"
              onChange={(event) => {
                choose(event.target.files?.[0]);
                event.target.value = "";
              }}
            />
            {inApp ? (
              <button
                type="button"
                className={styles.chip}
                aria-pressed={shakeOn}
                onClick={() => setShakeToReport(!shakeOn)}
              >
                <Vibrate size={15} aria-hidden="true" />
                Shake to report {shakeOn ? "on" : "off"}
              </button>
            ) : null}
          </div>
          {pictureNote ? (
            <small className={styles.note} role="alert">
              {pictureNote}
            </small>
          ) : null}
          <p className={styles.fine}>
            We also send which screen you were on, your app and device, and
            recent error messages. Never your calls.{" "}
            <button
              type="button"
              className={styles.inlineAction}
              onClick={() => setStep("mine")}
            >
              Your reports
            </button>
          </p>
        </form>
      )}
    </Sheet>
  );
}

const COMMANDS = {
  commands: [
    {
      id: "bug-report:open",
      group: "Help",
      label: "Report a problem",
      hint: "Tell the team about a bug",
      keywords: "bug issue broken feedback support",
      icon: <Bug size={16} aria-hidden="true" />,
      run: () => openBugReport(),
    },
  ],
};

/** Send what waited offline: reports and feedback, oldest first. */
async function sendWaiting(
  item: OutboxItem,
): Promise<"sent" | "retry" | "drop"> {
  try {
    if (item.kind === "bug") {
      const sent = await postBugReport(item.body as Record<string, unknown>);
      rememberSent(sent.bugId);
    } else {
      await postFeedbackRequest(item.body as Record<string, unknown>);
    }
    return "sent";
  } catch (error) {
    return retryLater(error) ? "retry" : "drop";
  }
}

/**
 * Mounted once in the app frame: opens the sheet on REPORT_PROBLEM_EVENT (and
 * on a shake in the phone app), offers "Report a problem" in the command bar,
 * sends what waited offline, and says when a report has been fixed.
 */
export function BugReportHost() {
  const inApp = useInApp();
  const [open, setOpen] = useState(false);
  const [about, setAbout] = useState<ReportAbout | null>(null);
  const [preset, setPreset] = useState<Blob | null>(null);
  useEffect(() => reporterMounted(), []);
  useEffect(() => {
    let latest = 0;
    const show = (event: Event) => {
      const detail = (event as CustomEvent<ReportAbout | null>).detail ?? null;
      const round = (latest += 1);
      const reveal = (shot: Blob | null) => {
        if (round !== latest) return;
        setAbout(detail);
        setPreset(shot);
        setOpen(true);
      };
      // In the phone app the phone takes the picture, before the sheet covers
      // the screen (a closing You menu gets a moment to leave first).
      if (!inPhoneApp() || privateScreen(window.location.pathname)) {
        reveal(null);
        return;
      }
      window.setTimeout(() => {
        void askScreenshot().then(reveal, () => reveal(null));
      }, 280);
    };
    window.addEventListener(REPORT_PROBLEM_EVENT, show);
    // Asked for before this loaded (the frame loads it once the page is quiet).
    const waiting = takeWaitingReport();
    if (waiting)
      show(
        new CustomEvent<ReportAbout | null>(REPORT_PROBLEM_EVENT, {
          detail: waiting.about,
        }),
      );
    return () => window.removeEventListener(REPORT_PROBLEM_EVENT, show);
  }, []);
  useCommandSource("bug-report", COMMANDS);
  const onShake = useCallback(() => {
    tick();
    openBugReport();
  }, []);
  useShakeToReport(inApp, onShake);

  useEffect(() => {
    const send = () => {
      void flush(sendWaiting).then((sent) => {
        if (sent) {
          notify({
            id: "bug-report-outbox",
            tone: "success",
            title:
              sent === 1
                ? "Your saved report has gone to the team."
                : `${sent} saved reports have gone to the team.`,
          });
        }
      });
    };
    send();
    window.addEventListener("online", send);
    // A little after the frame is up: say if a report has been fixed.
    const look = window.setTimeout(() => {
      void lookForFixes()
        .then((fixed) => {
          for (const report of fixed.slice(0, 2)) {
            notify({
              id: `bug-fixed-${report.bugId}`,
              tone: "success",
              title: `Fixed: “${report.words.slice(0, 60)}${report.words.length > 60 ? "…" : ""}”`,
              message: "Thanks for reporting it. If it still happens, tell us.",
              timeout: 12_000,
              action: { label: "Report again", run: () => openBugReport() },
            });
          }
        })
        .catch(() => {});
    }, 8000);
    return () => {
      window.removeEventListener("online", send);
      window.clearTimeout(look);
    };
  }, []);

  return (
    <BugReportSheet
      open={open}
      about={about}
      preset={preset}
      onClose={() => setOpen(false)}
    />
  );
}
