/**
 * A new lead that came in by itself rings on a computer (owner, 17 Nov 2026:
 * "a nice notification to grab attention … so the hot lead gets contacted as
 * fast as possible"): a short two-note chime when the browser lets the page
 * play sound, and, while the tab is in the background, a system notification
 * that opens the lead. Only where notifications are already allowed: this never
 * asks for permission (no prompt mid-use).
 */

type AudioContextClass = new () => AudioContext;

let audio: AudioContext | null = null;

function context(): AudioContext | null {
  if (audio) return audio;
  const Context =
    window.AudioContext ??
    (window as Window & { webkitAudioContext?: AudioContextClass })
      .webkitAudioContext;
  if (!Context) return null;
  audio = new Context();
  return audio;
}

/** Two short rising notes; silent where the browser blocks sound. */
export function chime(): void {
  try {
    const ctx = context();
    if (!ctx) return;
    const play = () => {
      const start = ctx.currentTime;
      [880, 1320].forEach((frequency, index) => {
        const at = start + index * 0.16;
        const tone = ctx.createOscillator();
        const gain = ctx.createGain();
        tone.type = "sine";
        tone.frequency.setValueAtTime(frequency, at);
        gain.gain.setValueAtTime(0.0001, at);
        gain.gain.exponentialRampToValueAtTime(0.2, at + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.15);
        tone.connect(gain);
        gain.connect(ctx.destination);
        tone.start(at);
        tone.stop(at + 0.16);
      });
    };
    if (ctx.state === "suspended") {
      // Without a tap on the page first the browser keeps it quiet: no error.
      void ctx.resume().then(play, () => undefined);
      return;
    }
    play();
  } catch {
    // No sound here: the banner and the bell still show the lead.
  }
}

/** A system notification while the tab is hidden, where already allowed. */
export function popOnComputer(
  id: string,
  title: string,
  body: string | undefined,
  open: () => void,
): boolean {
  try {
    if (typeof window.Notification !== "function") return false;
    if (window.Notification.permission !== "granted") return false;
    if (document.visibilityState !== "hidden") return false;
    const shown = new window.Notification(title, {
      body: body ?? "",
      tag: `lead-new:${id}`,
      requireInteraction: true,
    });
    shown.onclick = () => {
      window.focus();
      open();
      shown.close();
    };
    return true;
  } catch {
    // Android's WebView and Chrome on a phone have no page notifications.
    return false;
  }
}

export function ringNewLead(
  id: string,
  title: string,
  body: string | undefined,
  open: () => void,
): void {
  chime();
  popOnComputer(id, title, body, open);
}
