/**
 * Settings → This phone → Call uploads (SX-AUTOUPLOAD, owner 25 Nov 2026: "auto upload is not working for any of
 * the people who are using it currently ... fix that feature"). One glance says whether this phone's lead calls go
 * up by themselves, and each problem has one tap. Judged design: call-uploads round 1, U1 v01-2 (status first).
 * Pure, so every state is tested without a phone.
 */
import type {
  AutoCaptureItem,
  AutoCaptureStatus,
  SetupStatus,
} from "../../leads/native-phone";

export type Where = "android" | "iphone" | "web";

export type Tone = "ok" | "attention" | "off" | "blocked";

/** What the top card says, and the one thing to tap (if any). */
export type Headline = Readonly<{
  tone: Tone;
  title: string;
  line: string;
  action:
    | "turn_on"
    | "agree"
    | "notices"
    | "recorder"
    | "share_help"
    | "upload"
    | "open_app"
    | null;
}>;

const MIN = 60_000;
const HOUR = 60 * MIN;

/** "just now", "4 min ago", "3 h ago", "yesterday", "2 days ago". */
export function agoText(at: number, now: number): string {
  const gap = Math.max(0, now - at);
  if (gap < MIN) return "just now";
  if (gap < HOUR) return `${Math.floor(gap / MIN)} min ago`;
  if (gap < 24 * HOUR) return `${Math.floor(gap / HOUR)} h ago`;
  const days = Math.floor(gap / (24 * HOUR));
  return days === 1 ? "yesterday" : `${days} days ago`;
}

/** Holds a seller can fix with Retry here; the rest go by themselves or need the lead. */
const RETRYABLE = new Set(["review", "access", "folder", "network", "other"]);

export function canRetry(item: AutoCaptureItem): boolean {
  return item.state === "held" && !!item.id && RETRYABLE.has(item.hold ?? "");
}

/** Why one held call waits, in a few words. */
export function holdWords(hold: string | undefined): string {
  switch (hold) {
    case "terms":
      return "Waiting for you to agree to the new upload terms";
    case "consent":
      return "Automatic analysis is off";
    case "notices":
      return "Upload notices are blocked";
    case "signed_out":
      return "Sign in on this phone";
    case "profile":
      return "Add your name and phone in Profile";
    case "allowance":
      return "Call minutes used up";
    case "workspace":
      return "Waiting for your organisation workspace";
    case "folder":
      return "Sales X-Ray can't read the recording any more";
    case "network":
      return "Your phone held back the upload";
    case "expired":
      return "Older than 3 days: add it on the lead by hand";
    case "access":
      return "The server said not now; tries again hourly";
    default:
      return "Didn't upload";
  }
}

export type Counts = Readonly<{
  today: number;
  waiting: AutoCaptureItem[];
  failed: AutoCaptureItem[];
}>;

function startOfIndiaDay(now: number): number {
  const ist = 5.5 * HOUR;
  return Math.floor((now + ist) / (24 * HOUR)) * 24 * HOUR - ist;
}

/** Uploaded today (India day), on the way, and held: rows that add up to the figures above them. */
export function counts(items: readonly AutoCaptureItem[], now: number): Counts {
  const since = startOfIndiaDay(now);
  const sent = new Set(["analysing", "report_ready", "received"]);
  return {
    today: items.filter(
      (item) => sent.has(item.state) && (item.uploadedAt ?? 0) >= since,
    ).length,
    waiting: items
      .filter((item) => item.state === "waiting" || item.state === "uploading")
      .sort((a, b) => (b.stamp ?? 0) - (a.stamp ?? 0)),
    failed: items
      .filter((item) => item.state === "held")
      .sort((a, b) => (b.stamp ?? 0) - (a.stamp ?? 0)),
  };
}

/**
 * The top card. Order: things that make uploads impossible here (iPhone, a web browser, Google's Phone app,
 * recording off), then uploads off, then a hold that needs the seller, then all well.
 */
export function headline(
  where: Where,
  status: AutoCaptureStatus | null,
  setup: SetupStatus | null,
  now: number,
): Headline {
  if (where === "iphone")
    return {
      tone: "blocked",
      title: "iPhone can't send calls by itself",
      line: "Apple lets no app read call recordings. Save the call's recording to Files, then upload it here; it reaches the lead and is analysed.",
      action: "upload",
    };
  if (where === "web" || !status?.supported)
    return {
      tone: "blocked",
      title: "Calls upload from the Android app",
      line: "Open Sales X-Ray on your Android phone; it sends your lead calls by itself.",
      action: "open_app",
    };
  if (setup?.recorder?.kind === "private")
    return {
      tone: "blocked",
      title: "Your Phone app keeps recordings to itself",
      line: `${setup.recorder.dialerLabel || "Google's Phone app"} saves call recordings where no other app can read them, so nothing can send them by itself. Share each call's recording to Sales X-Ray from the Phone app instead.`,
      action: "share_help",
    };
  if (setup?.recorder && setup.recorder.recording === "off")
    return {
      tone: "attention",
      title: "Your phone isn't recording calls",
      line: "Turn on call recording in your Phone app's settings; calls then upload by themselves.",
      action: "recorder",
    };
  const health = status.health ?? (status.on ? "ok" : "off");
  if (!status.on) {
    if (health === "consent" || health === "terms")
      return {
        tone: "off",
        title: "Uploads stopped: agree to the new upload terms",
        line: "Sales X-Ray's upload terms changed. Agree to them and your calls upload by themselves again.",
        action: "agree",
      };
    if (health === "notices")
      return {
        tone: "off",
        title: "Uploads stopped: notices are blocked",
        line: "Each call shows a notice with 60 seconds to Undo. Allow notices, then turn uploads on.",
        action: "notices",
      };
    return {
      tone: "off",
      title: "Automatic uploads are off",
      line: "Recordings stay on this phone until you turn uploads on.",
      action: "turn_on",
    };
  }
  if (health === "terms")
    return {
      tone: "attention",
      title: "Agree to the new upload terms",
      line: `${waiting(status.healthCalls)} Sales X-Ray's upload terms changed; agree and they upload by themselves.`,
      action: "agree",
    };
  if (health !== "ok")
    return {
      tone: "attention",
      title: "Calls are waiting on this phone",
      line: `${waiting(status.healthCalls)} ${holdWords(health)}.`,
      action: null,
    };
  const last = status.lastUploadAt;
  return {
    tone: "ok",
    title: "Uploading by itself",
    line: last
      ? `Last call uploaded ${agoText(last, now)}${status.lastUploadLead ? ` · ${status.lastUploadLead}` : ""}`
      : "Your next lead call uploads after its 60-second Undo.",
    action: null,
  };
}

function waiting(calls: number | undefined): string {
  if (!calls) return "Your next lead calls wait on this phone.";
  return calls === 1
    ? "1 lead call waits on this phone."
    : `${calls} lead calls wait on this phone.`;
}

/** The recordings folder row: what this phone reads. */
export function folderLine(
  status: AutoCaptureStatus | null,
  setup: SetupStatus | null,
): string {
  const picked = status?.folders?.[0];
  if (picked) return picked.split("/").filter(Boolean).join(" / ");
  const found = setup?.recorder?.folders?.find(
    (folder) => folder.recordings > 0,
  );
  if (found)
    return `${found.path.split("/").filter(Boolean).join(" / ")} (found by itself)`;
  return "Not chosen";
}

/** "6 min call · 3:40 PM" in India time. */
export function callLine(item: AutoCaptureItem): string {
  const parts: string[] = [];
  if (item.seconds && item.seconds > 0)
    parts.push(
      item.seconds < 60
        ? `${item.seconds} sec call`
        : `${Math.round(item.seconds / 60)} min call`,
    );
  if (item.stamp)
    parts.push(
      new Date(item.stamp).toLocaleTimeString("en-IN", {
        hour: "numeric",
        minute: "2-digit",
        timeZone: "Asia/Kolkata",
      }),
    );
  return parts.join(" · ");
}
