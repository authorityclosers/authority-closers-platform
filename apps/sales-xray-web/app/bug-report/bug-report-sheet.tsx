"use client";

/**
 * Report a problem (owner, 23 Oct 2026: "bug catcher for everyone ... so they
 * report bugs and issues immediately and easily").
 *
 * For every signed-in person, from any screen, in two taps: You (the avatar
 * on phones, the gear on computers) → Report a problem; also the command bar,
 * and Report on any error corner card. One sheet, one job, one primary action
 * ("Send report"):
 * - what went wrong, in their words (a draft survives closing the sheet);
 * - "This stops my work", one chip;
 * - a picture of the screen, taken on the device when the sheet opens and
 *   shown before it goes; off by default on screens with call details or
 *   messages; or a picture they choose;
 * - with it, quietly: the screen, app and device, and recent errors
 *   (scrubbed, never call content).
 * Sending closes the sheet with a thank-you corner card; a failure is a
 * corner card with Send again, and the sheet keeps everything.
 */

import { Bug, Camera, ImagePlus, TriangleAlert, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { notify } from "../notice-center";
import { useCommandSource } from "../ui/command-registry";
import { tick } from "../ui/haptics";
import { Button } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import {
  BugReportError,
  MAX_PICTURE_BYTES,
  PICTURE_TYPES,
  sendBugReport,
  type ReportPicture,
} from "./bug-report-client";
import styles from "./bug-report.module.css";
import { captureScreen } from "./capture";
import { reportContext } from "./device";
import {
  REPORT_PROBLEM_EVENT,
  openBugReport,
  reporterMounted,
  type ReportAbout,
} from "./open";
import { recentErrors } from "./recent-errors";
import { scrubRoute } from "./scrub";

/** Screens that can show call details or messages: no picture unless chosen. */
const PRIVATE_SCREENS = [
  /^\/analysis\/calls\/[^/]+/,
  /^\/chats(?:\/|$)/,
  /^\/review(?:\/|$)/,
];

export function privateScreen(path: string): boolean {
  return PRIVATE_SCREENS.some((pattern) => pattern.test(path));
}

function commandId(): string {
  const random = globalThis.crypto?.randomUUID?.();
  if (random) return random;
  const bytes = Array.from({ length: 16 }, () =>
    Math.floor(Math.random() * 256),
  );
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.map((byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

type Picture =
  | { state: "none" }
  | { state: "taking" }
  | { state: "failed" }
  | { state: "ready"; picture: ReportPicture; url: string };

// What was typed stays for the next opening until it is sent.
const draft = { words: "", blocksWork: false };
function keepDraft(words: string, blocksWork: boolean) {
  draft.words = words;
  draft.blocksWork = blocksWork;
}

export function BugReportSheet({
  open,
  about,
  onClose,
}: {
  open: boolean;
  about: ReportAbout | null;
  onClose: () => void;
}) {
  const [words, setWords] = useState(draft.words);
  const [blocksWork, setBlocksWork] = useState(draft.blocksWork);
  const [picture, setPicture] = useState<Picture>({ state: "none" });
  const [include, setInclude] = useState(true);
  const [sensitive, setSensitive] = useState(false);
  const [sending, setSending] = useState(false);
  const [pictureNote, setPictureNote] = useState<string | null>(null);
  const [route, setRoute] = useState("/");
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
      setPicture(hidden ? { state: "none" } : { state: "taking" });
    }
  }

  // Then the picture is taken once the sheet is up, and the words get focus.
  useEffect(() => {
    if (!open) return;
    const round = (opening.current += 1);
    const focus = window.setTimeout(() => textArea.current?.focus(), 320);
    if (sensitive) return () => window.clearTimeout(focus);
    const start = window.setTimeout(() => {
      void captureScreen().then((blob) => {
        if (round !== opening.current) return;
        setPicture(
          blob
            ? {
                state: "ready",
                picture: { blob, source: "auto" },
                url: URL.createObjectURL(blob),
              }
            : { state: "failed" },
        );
      });
    }, 360);
    return () => {
      window.clearTimeout(focus);
      window.clearTimeout(start);
    };
  }, [open, sensitive]);

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
    });
  };

  const send = async () => {
    const text = words.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      const sent = await sendBugReport({
        commandId: command.current,
        words: about
          ? `${text}\n\n(About: ${about.title}${about.reference ? `, ref ${about.reference}` : ""})`
          : text,
        blocksWork,
        route,
        context: await reportContext(),
        errors: recentErrors(),
        picture: include && picture.state === "ready" ? picture.picture : null,
      });
      tick();
      keepDraft("", false);
      setWords("");
      setBlocksWork(false);
      command.current = commandId();
      onClose();
      notify({
        id: "bug-report-sent",
        tone: "success",
        title: "Thanks. The team has your report.",
        message:
          sent.picture === "skipped"
            ? "The picture didn't go with it."
            : undefined,
      });
    } catch (error) {
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
    } finally {
      setSending(false);
    }
  };

  const ready = picture.state === "ready";
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Report a problem"
      description="Tell us what went wrong. The team gets it straight away."
      wide="center"
      footer={
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
      }
    >
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
        </div>
        <div className={styles.picture} data-state={picture.state}>
          {ready && include ? (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element -- a local blob preview */}
              <img
                className={styles.thumb}
                src={picture.url}
                alt="Picture of the screen that goes with your report"
              />
              <div className={styles.pictureWords}>
                <strong>
                  {picture.picture.source === "auto"
                    ? "Picture of this screen"
                    : "Your picture"}
                </strong>
                <small>It goes with your report.</small>
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
        {pictureNote ? (
          <small className={styles.note} role="alert">
            {pictureNote}
          </small>
        ) : null}
        <p className={styles.fine}>
          We also send which screen you were on, your app and device, and recent
          error messages. Never your calls.
        </p>
      </form>
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

/**
 * Mounted once in the app frame: opens the sheet on REPORT_PROBLEM_EVENT and
 * offers "Report a problem" in the command bar.
 */
export function BugReportHost() {
  const [open, setOpen] = useState(false);
  const [about, setAbout] = useState<ReportAbout | null>(null);
  useEffect(() => reporterMounted(), []);
  useEffect(() => {
    const show = (event: Event) => {
      setAbout((event as CustomEvent<ReportAbout | null>).detail ?? null);
      setOpen(true);
    };
    window.addEventListener(REPORT_PROBLEM_EVENT, show);
    return () => window.removeEventListener(REPORT_PROBLEM_EVENT, show);
  }, []);
  useCommandSource("bug-report", COMMANDS);
  return (
    <BugReportSheet open={open} about={about} onClose={() => setOpen(false)} />
  );
}
