"use client";

/**
 * The advanced bug reporter (owner, 31 Oct 2026), for the team and the
 * testers the owner lets in. One large editor: on a computer the picture of
 * the screen fills the left with the drawing tools over it and the report sits
 * in a panel on the right; on a phone it is one full screen, the picture on
 * top and the report under it. Marks are kept as shapes, so every one can be
 * undone; the picture that goes is cropped and has them burnt in. Esc, Back
 * and Cancel close it, asking first when something would be lost.
 */

import {
  ArrowUpRight,
  Bug,
  CheckCircle2,
  Circle,
  CloudOff,
  Crop,
  EyeOff,
  Highlighter,
  ImagePlus,
  MousePointerClick,
  PenLine,
  Redo2,
  Square,
  Trash2,
  TriangleAlert,
  Type,
  Undo2,
  X,
} from "lucide-react";
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { notify } from "../notice-center";
import { recentSteps } from "../telemetry";
import { useBackClose } from "../ui/back-close";
import { tick } from "../ui/haptics";
import { Button } from "../ui/kit";
import { AnnotateCanvas, type CanvasColors } from "./annotate-canvas";
import {
  EMPTY,
  commit,
  edited,
  flatten,
  redo,
  startHistory,
  undo,
  type Box,
  type History,
  type Markup,
  type Pin,
  type Tool,
} from "./annotate-model";
import styles from "./advanced-reporter.module.css";
import {
  BugReportError,
  MAX_PICTURE_BYTES,
  PICTURE_TYPES,
  bugReportRequest,
  postBugReport,
  retryLater,
} from "./bug-report-client";
import { captureScreen } from "./capture";
import { commandId } from "./command-id";
import { reportContext } from "./device";
import {
  cropOf,
  markScroll,
  pickElement,
  shortName,
  type Picked,
  type ScrollMark,
} from "./element-picker";
import { rememberSent } from "./my-reports";
import type { ReportAbout } from "./open";
import { keepNow } from "./outbox";
import { recentErrors } from "./recent-errors";
import { scrubRoute } from "./scrub";
import { enterSends, keySendAsks, stopAskingOnKeySend } from "./key-send";
import {
  advancedServer,
  uploadBugFile,
  type FileRole,
} from "./advanced-access";
import {
  CapturedSection,
  FilesSection,
  StepsSection,
  fileProblem,
  kindOf,
  type Attachment,
} from "./advanced-parts";
import {
  captureTelemetry,
  stepsFrom,
  type Captured,
} from "./advanced-telemetry";

/** What the basic reporter hands over when the person opens this one. */
export type AdvancedSeed = Readonly<{
  words: string;
  blocksWork: boolean;
  about: ReportAbout | null;
  /** The picture already taken (the screen, or one they chose), or none. */
  picture: Blob | null;
  source: "auto" | "upload";
  /** No picture is taken on screens that can show calls or messages. */
  sensitive: boolean;
}>;

type Loaded = Readonly<{
  blob: Blob;
  source: "auto" | "upload";
  image: HTMLImageElement;
  size: Readonly<{ width: number; height: number }>;
}>;

/** A comment on one part of the screen, numbered on the picture. */
type Comment = Readonly<{
  id: number;
  picked: Picked;
  note: string;
  crop: string | null;
  cropBlob: Blob | null;
  /** Where it sits on the picture, or null when the page had scrolled since. */
  pin: Box | null;
}>;

/** "LeadRow › LeadList · testid lead-row · div.row > button" for the team. */
function whereOf(picked: Picked): string {
  return [
    picked.components.join(" › "),
    picked.testid ? `testid ${picked.testid}` : "",
    picked.label ? `"${picked.label}"` : "",
    picked.selector,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** The comments, written under the description so the team reads them today. */
export function wordsWithComments(
  text: string,
  comments: readonly Pick<Comment, "picked" | "note">[],
): string {
  if (!comments.length) return text;
  const lines = comments.map(
    (item, index) =>
      `${index + 1}. ${item.note.trim() || "(no words)"}\n   ${whereOf(item.picked)}`,
  );
  return `${text}\n\nOn the screen:\n${lines.join("\n")}`.slice(0, 4000);
}

type Picture =
  | { state: "taking" }
  | { state: "none"; note: string }
  | ({ state: "ready" } & Loaded);

const TOOLS: ReadonlyArray<{
  tool: Tool;
  label: string;
  key: string;
  icon: ReactNode;
}> = [
  { tool: "arrow", label: "Arrow", key: "a", icon: <ArrowUpRight size={18} /> },
  { tool: "rect", label: "Box", key: "r", icon: <Square size={17} /> },
  { tool: "ellipse", label: "Circle", key: "o", icon: <Circle size={17} /> },
  { tool: "pen", label: "Pen", key: "p", icon: <PenLine size={17} /> },
  {
    tool: "highlight",
    label: "Highlighter",
    key: "h",
    icon: <Highlighter size={17} />,
  },
  { tool: "text", label: "Text", key: "t", icon: <Type size={17} /> },
  { tool: "blur", label: "Blur", key: "b", icon: <EyeOff size={17} /> },
  { tool: "crop", label: "Crop", key: "c", icon: <Crop size={17} /> },
];

const HINTS: Record<Tool, string> = {
  arrow: "Drag from where you start to what is wrong.",
  rect: "Drag a box round what is wrong.",
  ellipse: "Drag a circle round what is wrong.",
  pen: "Draw freely.",
  highlight: "Run over text to highlight it.",
  text: "Tap where the words go, type, then press Enter.",
  blur: "Drag over anything private to hide it.",
  crop: "Drag the part to keep. Tap once to keep it all.",
};

// Each a token of the app, read as a colour the canvas can use.
const SWATCHES: ReadonlyArray<{ name: string; css: string }> = [
  { name: "Red", css: "var(--sx-bad, crimson)" },
  { name: "Amber", css: "var(--sx-warn, orange)" },
  { name: "Green", css: "var(--sx-good, seagreen)" },
  { name: "Blue", css: "var(--lx-closing, royalblue)" },
  { name: "Pink", css: "var(--lx-objection, deeppink)" },
  { name: "White", css: "white" },
  { name: "Black", css: "black" },
];

/** A CSS colour (a token too) as the browser resolves it, e.g. "rgb(198, 40, 40)". */
function resolved(css: string): string {
  if (typeof document === "undefined") return "crimson";
  const probe = document.createElement("span");
  probe.style.color = css;
  probe.style.display = "none";
  document.body.appendChild(probe);
  const value = getComputedStyle(probe).color;
  probe.remove();
  return value || "crimson";
}

function load(blob: Blob, source: "auto" | "upload"): Promise<Loaded | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.decoding = "async";
    image.onload = () => {
      resolve({
        blob,
        source,
        image,
        size: { width: image.naturalWidth, height: image.naturalHeight },
      });
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      resolve(null);
    };
    image.src = url;
  });
}

export function AdvancedReporter({
  open,
  seed,
  onClose,
  onSent,
}: {
  open: boolean;
  seed: AdvancedSeed | null;
  onClose: () => void;
  /** Sent or saved to go later: the basic reporter forgets its draft. */
  onSent: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const wordsId = useId();
  const [words, setWords] = useState("");
  const [blocksWork, setBlocksWork] = useState(false);
  const [picture, setPicture] = useState<Picture>({ state: "taking" });
  const [history, setHistory] = useState<History>(startHistory());
  const [tool, setTool] = useState<Tool>("arrow");
  const [swatch, setSwatch] = useState(0);
  // The app's colours as the canvas needs them, read while it is open (light or dark).
  const colors = useMemo(
    () => (open ? SWATCHES.map((item) => resolved(item.css)) : []),
    [open],
  );
  const pinColors = useMemo<CanvasColors>(
    () =>
      open
        ? {
            pinFill: resolved("var(--sx-accent, royalblue)"),
            pinInk: resolved("var(--sx-accent-ink, white)"),
          }
        : { pinFill: "crimson", pinInk: "white" },
    [open],
  );
  const [discarding, setDiscarding] = useState(false);
  // Sending from the keyboard asks first, until "Don't ask again" (key-send.ts).
  const [asking, setAsking] = useState(false);
  const [dontAsk, setDontAsk] = useState(false);
  const askSendId = useId();
  const wordsArea = useRef<HTMLTextAreaElement>(null);
  const [sending, setSending] = useState(false);
  const [outcome, setOutcome] = useState<"sent" | "queued" | null>(null);
  const [route, setRoute] = useState("/");
  const [shownSeed, setShownSeed] = useState<AdvancedSeed | null>(null);
  const [comments, setComments] = useState<readonly Comment[]>([]);
  const [picking, setPicking] = useState(false);
  const [fresh, setFresh] = useState<number | null>(null);
  const [captured, setCaptured] = useState<Captured | null>(null);
  const [steps, setSteps] = useState<string[]>([]);
  const [files, setFiles] = useState<readonly Attachment[]>([]);
  const fileSerial = useRef(0);
  const scroll = useRef<ScrollMark | null>(null);
  const serial = useRef(0);
  const [command, setCommand] = useState(commandId);

  // Each opening starts from what the basic reporter had.
  if (open && seed !== shownSeed) {
    setShownSeed(seed);
    setWords(seed?.words ?? "");
    setBlocksWork(seed?.blocksWork ?? false);
    setHistory(startHistory());
    setComments([]);
    setCaptured(null);
    setSteps([]);
    setFiles([]);
    setDiscarding(false);
    setAsking(false);
    setOutcome(null);
    setRoute(scrubRoute(window.location.pathname + window.location.search));
    setPicture(
      seed?.sensitive && !seed.picture
        ? {
            state: "none",
            note: "This screen can show call details or messages, so no picture is taken. Choose one if it helps.",
          }
        : { state: "taking" },
    );
    setCommand(commandId());
  }

  // Shown while open; it steps aside while a part of the screen is picked.
  const shown = open && !picking;
  useEffect(() => {
    const target = dialog.current;
    if (!target) return;
    if (shown && !target.open) {
      if (typeof target.showModal === "function") target.showModal();
      else target.setAttribute("open", "");
    } else if (!shown && target.open) {
      if (typeof target.close === "function") target.close();
      else target.removeAttribute("open");
    }
  }, [shown]);

  // Where everything was scrolled as the picture was taken, so a pin lands
  // where the part was (the reporter covered the page since).
  useEffect(() => {
    if (open && seed) scroll.current = markScroll();
  }, [open, seed]);

  // What goes with it, gathered as it opens; the steps start from the app's trail.
  useEffect(() => {
    if (!open || !seed) return;
    let alive = true;
    void captureTelemetry(
      scrubRoute(window.location.pathname + window.location.search),
    ).then((found) => {
      if (!alive) return;
      setCaptured(found);
      setSteps((now) => (now.length ? now : stepsFrom(found.trail)));
    });
    return () => {
      alive = false;
    };
  }, [open, seed]);

  // A comment's small picture, or a file, is released when it goes.
  const crops = useRef(new Set<string>());
  useEffect(() => {
    const kept = crops.current;
    return () => {
      kept.forEach((url) => URL.revokeObjectURL(url));
      kept.clear();
    };
  }, []);

  // The picture: the one handed over, or a fresh one of the screen.
  useEffect(() => {
    if (!open || !seed || picture.state !== "taking") return;
    let alive = true;
    void (seed.picture ? Promise.resolve(seed.picture) : captureScreen()).then(
      async (blob) => {
        const loaded = blob
          ? await load(blob, seed.picture ? seed.source : "auto")
          : null;
        if (!alive) return;
        setPicture(
          loaded
            ? { state: "ready", ...loaded }
            : {
                state: "none",
                note: "Couldn't take a picture here. Choose one instead.",
              },
        );
      },
    );
    return () => {
      alive = false;
    };
  }, [open, seed, picture.state]);

  // Its address is released when the picture is replaced or the editor closes.
  useEffect(() => {
    const url = picture.state === "ready" ? picture.image.src : null;
    return () => {
      if (url?.startsWith("blob:")) URL.revokeObjectURL(url);
    };
  }, [picture]);

  const markup: Markup = history.now;
  const change = (next: Markup) => {
    setHistory((now) => commit(now, next));
    setDiscarding(false);
  };
  const unsaved =
    words.trim() !== (seed?.words ?? "").trim() ||
    edited(history) ||
    comments.length > 0 ||
    files.length > 0 ||
    (picture.state === "ready" &&
      picture.source === "upload" &&
      !seed?.picture);

  const requestClose = () => {
    if (picking) return;
    if (outcome) return onClose();
    if (unsaved && !discarding) {
      setDiscarding(true);
      return;
    }
    onClose();
  };
  useBackClose(open, requestClose);

  const choose = async (file: File | undefined) => {
    if (!file) return;
    if (!(PICTURE_TYPES as readonly string[]).includes(file.type)) {
      notify({
        id: "bug-report-picture",
        tone: "info",
        title: "Choose a PNG, JPG or WebP picture.",
      });
      return;
    }
    if (file.size > MAX_PICTURE_BYTES) {
      notify({
        id: "bug-report-picture",
        tone: "info",
        title: "Choose a picture under 4 MB.",
      });
      return;
    }
    const loaded = await load(file, "upload");
    if (!loaded) return;
    setHistory(startHistory());
    setPicture({ state: "ready", ...loaded });
  };

  const pick = async () => {
    if (picking) return;
    setPicking(true);
    // Let the editor leave the screen first.
    await new Promise((resolve) => window.setTimeout(resolve, 60));
    const picked = await pickElement(scroll.current);
    setPicking(false);
    if (!picked) return;
    serial.current += 1;
    const id = serial.current;
    const scale =
      picture.state === "ready" && scroll.current
        ? picture.size.width / Math.max(1, scroll.current.width)
        : 0;
    const pin =
      !picked.moved && scale
        ? {
            x: picked.box.x * scale,
            y: picked.box.y * scale,
            w: picked.box.w * scale,
            h: picked.box.h * scale,
          }
        : null;
    setComments((now) => [
      ...now,
      { id, picked, note: "", crop: null, cropBlob: null, pin },
    ]);
    setFresh(id);
    setDiscarding(false);
    tick();
    // Its own small picture, from a fresh picture of the screen as it is now.
    const shot = await captureScreen();
    const crop = shot ? await cropOf(shot, picked.box) : null;
    if (!crop) return;
    const url = URL.createObjectURL(crop);
    crops.current.add(url);
    setComments((now) =>
      now.map((item) =>
        item.id === id ? { ...item, crop: url, cropBlob: crop } : item,
      ),
    );
  };

  const removeComment = (id: number) => {
    setComments((now) => {
      const gone = now.find((item) => item.id === id);
      if (gone?.crop) {
        URL.revokeObjectURL(gone.crop);
        crops.current.delete(gone.crop);
      }
      return now.filter((item) => item.id !== id);
    });
  };

  const addFiles = async (list: readonly File[]) => {
    let count = files.length;
    const added: Attachment[] = [];
    for (const file of list) {
      const problem = await fileProblem(file, count);
      if (problem) {
        notify({ id: "bug-report-file", tone: "info", title: problem });
        continue;
      }
      fileSerial.current += 1;
      const url = URL.createObjectURL(file);
      crops.current.add(url);
      added.push({ id: fileSerial.current, file, kind: kindOf(file)!, url });
      count += 1;
    }
    if (added.length) {
      setFiles((now) => [...now, ...added]);
      setDiscarding(false);
    }
  };

  const removeFile = (id: number) => {
    setFiles((now) => {
      const gone = now.find((item) => item.id === id);
      if (gone) {
        URL.revokeObjectURL(gone.url);
        crops.current.delete(gone.url);
      }
      return now.filter((item) => item.id !== id);
    });
  };

  const pins: Pin[] = useMemo(
    () =>
      comments.flatMap((item, index) =>
        item.pin ? [{ n: index + 1, box: item.pin }] : [],
      ),
    [comments],
  );

  const send = async () => {
    const text = words.trim();
    if (!text || sending || !seed) return;
    setSending(true);
    const id = command;
    let request: Record<string, unknown> | null = null;
    try {
      const marked =
        picture.state === "ready"
          ? edited(history)
            ? await flatten(picture.image, picture.size, markup, {
                pinColors: { fill: pinColors.pinFill, ink: pinColors.pinInk },
                scale: picture.size.width / Math.max(1, window.innerWidth),
              })
            : picture.blob
          : null;
      const about = seed.about;
      const server = advancedServer();
      const said = wordsWithComments(
        about
          ? `${text}\n\n(About: ${about.title}${about.reference ? `, ref ${about.reference}` : ""})`
          : text,
        comments,
      );
      const filled = steps
        .map((step) => step.trim())
        .filter(Boolean)
        .slice(0, 20);
      const base = await bugReportRequest({
        commandId: id,
        // Until the server keeps the steps on their own, they go in the words.
        words:
          server || !filled.length
            ? said
            : `${said}\n\nSteps to reproduce:\n${filled.map((step, index) => `${index + 1}. ${step}`).join("\n")}`.slice(
                0,
                4000,
              ),
        blocksWork,
        route,
        context: {
          ...(captured?.context ?? (await reportContext())),
          trail: recentSteps(),
        },
        errors: captured?.errors ?? recentErrors(),
        picture:
          marked && picture.state === "ready"
            ? { blob: marked, source: picture.source }
            : null,
      });
      const marks = picture.state === "ready" && edited(history);
      // The files that follow the report: the picture before its marks, each
      // comment's small picture, then the person's own files.
      const follow: Array<{
        blob: Blob;
        role: FileRole;
        name: string;
        n?: number;
      }> = [];
      if (server) {
        if (marks && picture.state === "ready") {
          follow.push({ blob: picture.blob, role: "original", name: "screen" });
        }
        comments.forEach((item, index) => {
          if (item.cropBlob) {
            follow.push({
              blob: item.cropBlob,
              role: "element",
              name: `part ${index + 1}`,
              n: index + 1,
            });
          }
        });
        for (const item of files) {
          follow.push({
            blob: item.file,
            role: "attachment",
            name: item.file.name || "pasted picture",
          });
        }
      }
      request = server
        ? {
            ...base,
            advanced: {
              steps: filled,
              comments: comments.map((item, index) => ({
                n: index + 1,
                note: item.note.trim().slice(0, 500),
                selector: item.picked.selector,
                ...(item.picked.testid ? { testid: item.picked.testid } : {}),
                components: item.picked.components,
                tag: item.picked.tag,
                ...(item.picked.role ? { role: item.picked.role } : {}),
                ...(item.picked.label ? { label: item.picked.label } : {}),
                box: item.picked.box,
                on_picture: item.pin !== null,
              })),
              trail: (captured?.trail ?? recentSteps()).slice(-50),
              calls: captured?.calls ?? [],
              ...(captured?.speed ? { speed: captured.speed } : {}),
              marked: marks,
              files: follow.length,
            },
          }
        : base;
      const sent = await postBugReport(request);
      rememberSent(sent.bugId);
      let missed = 0;
      for (const item of follow) {
        try {
          await uploadBugFile(
            sent.bugId,
            item.blob,
            item.role,
            item.name,
            item.n,
          );
        } catch {
          missed += 1;
        }
      }
      if (missed) {
        notify({
          id: "bug-report-files",
          tone: "info",
          title:
            missed === 1
              ? "Your report went without one of its files"
              : `Your report went without ${missed} of its files`,
        });
      }
      tick();
      onSent();
      setOutcome("sent");
    } catch (error) {
      if (request && retryLater(error) && (await keepNow("bug", id, request))) {
        tick();
        onSent();
        setOutcome("queued");
      } else {
        notify({
          id: "bug-report-failed",
          tone: "error",
          title: "Your report didn't go",
          message:
            error instanceof BugReportError
              ? error.message
              : "Send again in a moment.",
          noReport: true,
        });
      }
    } finally {
      setSending(false);
    }
  };

  // The question takes the focus, so Enter again (or Space) sends.
  useEffect(() => {
    if (asking) document.getElementById(askSendId)?.focus();
  }, [asking, askSendId]);

  // Enter or Ctrl+Enter: the same send as the button, asking first unless the
  // person said not to. Nothing written, nothing sent.
  const sendFromKeys = () => {
    if (!words.trim() || sending || outcome) return;
    setDiscarding(false);
    if (!keySendAsks()) {
      setAsking(false);
      void send();
      return;
    }
    if (asking) {
      document.getElementById(askSendId)?.focus();
      return;
    }
    setDontAsk(false);
    setAsking(true);
  };

  const sendAsked = () => {
    if (dontAsk) stopAskingOnKeySend();
    setAsking(false);
    void send();
  };

  const keys = (event: KeyboardEvent) => {
    const typingHere =
      event.target instanceof HTMLTextAreaElement ||
      event.target instanceof HTMLInputElement;
    const mod = event.ctrlKey || event.metaKey;
    if (mod && event.key === "Enter") {
      event.preventDefault();
      sendFromKeys();
      return;
    }
    if (typingHere || outcome) return;
    if (mod && event.key.toLowerCase() === "z") {
      event.preventDefault();
      setHistory((now) => (event.shiftKey ? redo(now) : undo(now)));
    } else if (mod && event.key.toLowerCase() === "y") {
      event.preventDefault();
      setHistory(redo);
    } else if (!mod && !event.altKey && event.key.toLowerCase() === "e") {
      void pick();
    } else if (!mod && !event.altKey) {
      const found = TOOLS.find((item) => item.key === event.key.toLowerCase());
      if (found) setTool(found.tool);
    }
  };

  const color = colors[swatch] ?? "crimson";
  const ready = picture.state === "ready";
  const footer = outcome ? (
    <Button variant="primary" onClick={onClose}>
      Done
    </Button>
  ) : asking ? (
    <div className={styles.discard} role="alert">
      <span>Send this report?</span>
      <label className={styles.askAgain}>
        <input
          type="checkbox"
          checked={dontAsk}
          onChange={(event) => setDontAsk(event.target.checked)}
        />
        Don&apos;t ask again
      </label>
      <Button
        onClick={() => {
          setAsking(false);
          wordsArea.current?.focus();
        }}
      >
        Keep editing
      </Button>
      <Button
        id={askSendId}
        variant="primary"
        disabled={!words.trim() || sending}
        onClick={sendAsked}
      >
        Send
      </Button>
    </div>
  ) : discarding ? (
    <div className={styles.discard} role="alert">
      <span>Discard this report?</span>
      <Button onClick={() => setDiscarding(false)}>Keep editing</Button>
      <Button variant="primary" onClick={onClose}>
        Discard
      </Button>
    </div>
  ) : (
    <>
      <Button onClick={requestClose}>Cancel</Button>
      <Button
        variant="primary"
        disabled={!words.trim() || sending}
        aria-busy={sending || undefined}
        onClick={() => void send()}
      >
        {sending ? "Sending…" : "Send report"}
      </Button>
    </>
  );

  const tools = useMemo(
    () =>
      TOOLS.map((item) => (
        <button
          key={item.tool}
          type="button"
          className={styles.tool}
          aria-pressed={tool === item.tool}
          aria-label={`${item.label} (${item.key.toUpperCase()})`}
          title={`${item.label} (${item.key.toUpperCase()})`}
          onClick={() => setTool(item.tool)}
        >
          {item.icon}
        </button>
      )),
    [tool],
  );

  return (
    <dialog
      ref={dialog}
      className={styles.dialog}
      aria-labelledby={`${wordsId}-title`}
      onCancel={(event) => {
        event.preventDefault();
        requestClose();
      }}
      onKeyDown={keys}
      onPaste={(event) => {
        const pasted = Array.from(event.clipboardData?.files ?? []);
        if (!pasted.length || !advancedServer()) return;
        event.preventDefault();
        void addFiles(pasted);
      }}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes("Files")) event.preventDefault();
      }}
      onDrop={(event) => {
        if (!event.dataTransfer.files.length || !advancedServer()) return;
        event.preventDefault();
        void addFiles(Array.from(event.dataTransfer.files));
      }}
    >
      {/* Its own picture leaves the reporter out (capture.ts). */}
      <div className={styles.frame} data-bug-reporter="">
        <header className={styles.head}>
          <span className={styles.mark} aria-hidden="true">
            <Bug size={18} />
          </span>
          <h2 id={`${wordsId}-title`} className={styles.title}>
            Report a problem
          </h2>
          <span className={styles.badge}>Advanced</span>
          <button
            type="button"
            className={styles.close}
            aria-label="Close"
            title="Close (Esc)"
            onClick={requestClose}
          >
            <X size={18} aria-hidden="true" />
          </button>
        </header>

        {outcome ? (
          <div className={styles.sent} role="status">
            <span
              className={styles.sentIcon}
              data-outcome={outcome}
              aria-hidden="true"
            >
              {outcome === "sent" ? (
                <CheckCircle2 size={30} />
              ) : (
                <CloudOff size={28} />
              )}
            </span>
            <strong>
              {outcome === "sent"
                ? "Sent. We'll tell you when it's fixed."
                : "Saved on this device."}
            </strong>
            <p>
              {outcome === "sent"
                ? "The team sees it now, with your marks on the picture."
                : "It goes by itself as soon as you're back online."}
            </p>
          </div>
        ) : (
          <div className={styles.body}>
            <section
              className={styles.stage}
              aria-label="Picture of the screen"
            >
              <div
                className={styles.toolbar}
                role="toolbar"
                aria-label="Mark up"
              >
                <div className={styles.toolGroup}>
                  {tools}
                  <button
                    type="button"
                    className={styles.tool}
                    aria-label="Comment on a part of the screen (E)"
                    title="Comment on a part of the screen (E)"
                    onClick={() => void pick()}
                  >
                    <MousePointerClick size={17} aria-hidden="true" />
                  </button>
                </div>
                <span className={styles.divider} aria-hidden="true" />
                <div
                  className={styles.toolGroup}
                  role="radiogroup"
                  aria-label="Colour"
                >
                  {SWATCHES.map((item, index) => (
                    <button
                      key={item.name}
                      type="button"
                      role="radio"
                      aria-checked={swatch === index}
                      aria-label={item.name}
                      title={item.name}
                      className={styles.swatch}
                      style={{ background: item.css }}
                      onClick={() => setSwatch(index)}
                    />
                  ))}
                </div>
                <span className={styles.divider} aria-hidden="true" />
                <div className={styles.toolGroup}>
                  <button
                    type="button"
                    className={styles.tool}
                    aria-label="Undo (Ctrl Z)"
                    title="Undo (Ctrl Z)"
                    disabled={!history.past.length}
                    onClick={() => setHistory(undo)}
                  >
                    <Undo2 size={17} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className={styles.tool}
                    aria-label="Redo (Ctrl Shift Z)"
                    title="Redo (Ctrl Shift Z)"
                    disabled={!history.future.length}
                    onClick={() => setHistory(redo)}
                  >
                    <Redo2 size={17} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className={styles.tool}
                    aria-label="Clear all marks"
                    title="Clear all marks"
                    disabled={!edited(history)}
                    onClick={() => change(EMPTY)}
                  >
                    <Trash2 size={17} aria-hidden="true" />
                  </button>
                </div>
              </div>
              <p className={styles.hint}>{ready ? HINTS[tool] : " "}</p>
              {ready ? (
                <AnnotateCanvas
                  picture={picture.image}
                  size={picture.size}
                  markup={markup}
                  tool={tool}
                  color={color}
                  pins={pins}
                  colors={pinColors}
                  onCommit={change}
                />
              ) : (
                <div className={styles.room}>
                  <div className={styles.empty}>
                    {picture.state === "taking" ? (
                      <>
                        <span className={styles.loading} aria-hidden="true" />
                        <strong>Taking a picture of this screen…</strong>
                        <small>You can start writing.</small>
                      </>
                    ) : (
                      <>
                        <strong>No picture</strong>
                        <small>{picture.note}</small>
                        <Button onClick={() => fileInput.current?.click()}>
                          <ImagePlus size={16} aria-hidden="true" />
                          Choose a picture
                        </Button>
                      </>
                    )}
                  </div>
                </div>
              )}
            </section>

            <aside className={styles.panel} aria-label="Your report">
              {seed?.about ? (
                <p className={styles.about}>
                  <TriangleAlert size={15} aria-hidden="true" />
                  <span>About: {seed.about.title}</span>
                </p>
              ) : null}
              <div className={styles.field}>
                <label className={styles.label} htmlFor={wordsId}>
                  What went wrong?
                </label>
                <textarea
                  id={wordsId}
                  ref={wordsArea}
                  className={styles.words}
                  value={words}
                  rows={5}
                  maxLength={4000}
                  autoCapitalize="sentences"
                  placeholder="What did you do, and what happened instead?"
                  onChange={(event) => {
                    setWords(event.target.value);
                    setDiscarding(false);
                    setAsking(false);
                  }}
                  onKeyDown={(event) => {
                    if (event.key !== "Enter" || event.shiftKey || event.altKey)
                      return;
                    // Enter that picks a word (Hindi, Marathi) is the keyboard's.
                    if (event.nativeEvent.isComposing || event.keyCode === 229)
                      return;
                    if (event.ctrlKey || event.metaKey) return; // the editor's own Ctrl+Enter
                    if (!enterSends()) return;
                    event.preventDefault();
                    sendFromKeys();
                  }}
                />
              </div>
              <div className={styles.chips}>
                <button
                  type="button"
                  className={styles.chip}
                  aria-pressed={blocksWork}
                  onClick={() => {
                    tick();
                    setBlocksWork(!blocksWork);
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
                  {ready ? "Use another picture" : "Choose a picture"}
                </button>
                <input
                  ref={fileInput}
                  className={styles.file}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  tabIndex={-1}
                  aria-hidden="true"
                  onChange={(event) => {
                    void choose(event.target.files?.[0]);
                    event.target.value = "";
                  }}
                />
              </div>
              <section className={styles.comments} aria-label="On the screen">
                <div className={styles.sectionHead}>
                  <h3 className={styles.sectionTitle}>On the screen</h3>
                  {comments.length ? (
                    <span className={styles.count}>{comments.length}</span>
                  ) : null}
                </div>
                {comments.length ? (
                  <ol className={styles.commentList}>
                    {comments.map((item, index) => (
                      <li key={item.id} className={styles.comment}>
                        <span className={styles.pinNumber} aria-hidden="true">
                          {index + 1}
                        </span>
                        <div className={styles.commentBody}>
                          <div className={styles.commentHead}>
                            {item.crop ? (
                              // eslint-disable-next-line @next/next/no-img-element -- a local blob preview
                              <img
                                className={styles.crop}
                                src={item.crop}
                                alt=""
                              />
                            ) : (
                              <span
                                className={styles.cropWaiting}
                                aria-hidden="true"
                              />
                            )}
                            <span className={styles.where}>
                              <strong>{shortName(item.picked)}</strong>
                              <small title={item.picked.selector}>
                                {item.pin
                                  ? item.picked.selector
                                  : "Not on the picture: the page had scrolled"}
                              </small>
                            </span>
                            <button
                              type="button"
                              className={styles.tool}
                              aria-label={`Remove comment ${index + 1}`}
                              title="Remove"
                              onClick={() => removeComment(item.id)}
                            >
                              <Trash2 size={16} aria-hidden="true" />
                            </button>
                          </div>
                          <textarea
                            className={styles.note}
                            aria-label={`Comment ${index + 1}`}
                            placeholder="What is wrong with this part?"
                            rows={2}
                            maxLength={500}
                            autoFocus={item.id === fresh}
                            value={item.note}
                            onChange={(event) => {
                              const note = event.target.value;
                              setComments((now) =>
                                now.map((other) =>
                                  other.id === item.id
                                    ? { ...other, note }
                                    : other,
                                ),
                              );
                            }}
                          />
                        </div>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className={styles.fine}>
                    Point at a button, a row or a number and say what is wrong
                    with it.
                  </p>
                )}
                <button
                  type="button"
                  className={styles.chip}
                  onClick={() => void pick()}
                >
                  <MousePointerClick size={15} aria-hidden="true" />
                  {comments.length
                    ? "Comment on another part"
                    : "Comment on a part of the screen"}
                </button>
              </section>
              <StepsSection steps={steps} onChange={setSteps} />
              {/* Files go where the server takes them (not yet on an older server). */}
              {advancedServer() ? (
                <FilesSection
                  files={files}
                  onAdd={(list) => void addFiles(list)}
                  onRemove={removeFile}
                />
              ) : null}
              <CapturedSection captured={captured} />
            </aside>
          </div>
        )}

        <footer className={styles.foot}>{footer}</footer>
      </div>
    </dialog>
  );
}
