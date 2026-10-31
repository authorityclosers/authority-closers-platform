/**
 * Pick a part of the screen to comment on (owner, 31 Oct 2026: "like Claude
 * Code's browser comments"). While picking, the reporter steps aside: the part
 * under the mouse is outlined with its name, and a click picks it; on a phone
 * a tap outlines it and "Comment on this" (or a second tap) picks it. Nothing
 * on the page reacts meanwhile: presses are caught before the app sees them,
 * while scrolling still works. Esc or Cancel stops.
 *
 * What is kept about the part: a CSS path to it, its data-testid, the React
 * components round it, its role, and where it sat. Its text and labels are
 * never read (a label can carry a name, "Call Asha"); the picture shows what
 * the person chose to send.
 */

import type { Box } from "./annotate-model";

export type Picked = Readonly<{
  selector: string;
  testid?: string;
  components: readonly string[];
  tag: string;
  role?: string;
  label?: string;
  /** Where it sat in the window, in CSS pixels. */
  box: Box;
  /** True when the page or a panel round it scrolled after the picture was taken. */
  moved: boolean;
}>;

// ---------- Where things sat when the picture was taken ----------

export type ScrollMark = Readonly<{
  x: number;
  y: number;
  width: number;
  height: number;
  panels: WeakMap<Element, readonly [number, number]>;
}>;

/** The window's and every scrolled panel's scroll, as the picture saw them. */
export function markScroll(): ScrollMark {
  const panels = new WeakMap<Element, readonly [number, number]>();
  for (const element of Array.from(document.body.querySelectorAll("*"))) {
    if (element.scrollTop || element.scrollLeft) {
      panels.set(element, [element.scrollTop, element.scrollLeft]);
    }
  }
  return {
    x: window.scrollX,
    y: window.scrollY,
    width: window.innerWidth,
    height: window.innerHeight,
    panels,
  };
}

function movedSince(mark: ScrollMark | null, element: Element): boolean {
  if (!mark) return true;
  if (
    mark.x !== window.scrollX ||
    mark.y !== window.scrollY ||
    mark.width !== window.innerWidth ||
    mark.height !== window.innerHeight
  )
    return true;
  for (let node = element.parentElement; node; node = node.parentElement) {
    const [top, left] = mark.panels.get(node) ?? [0, 0];
    if (node.scrollTop !== top || node.scrollLeft !== left) return true;
  }
  return false;
}

// ---------- What the part is ----------

// React and Next.js parts that name no screen.
const PLAIN = new Set([
  "Suspense",
  "Fragment",
  "StrictMode",
  "ErrorBoundary",
  "ErrorBoundaryHandler",
  "LoadingBoundary",
  "InnerLayoutRouter",
  "OuterLayoutRouter",
  "RenderFromTemplateContext",
  "ScrollAndFocusHandler",
  "InnerScrollAndFocusHandler",
  "RedirectBoundary",
  "RedirectErrorBoundary",
  "HTTPAccessFallbackBoundary",
  "HTTPAccessFallbackErrorBoundary",
  "Router",
  "AppRouter",
  "HotReload",
  "Link",
  "LinkComponent",
]);

type Fiber = { type?: unknown; return?: Fiber | null };

function nameOf(type: unknown): string | null {
  if (!type || (typeof type !== "function" && typeof type !== "object"))
    return null;
  const item = type as {
    displayName?: unknown;
    name?: unknown;
    render?: { displayName?: unknown; name?: unknown };
    type?: unknown;
  };
  const name =
    item.displayName ??
    item.name ??
    item.render?.displayName ??
    item.render?.name;
  if (typeof name === "string") return name;
  return item.type ? nameOf(item.type) : null;
}

/** The nearest named React components round an element, innermost first. */
export function componentsOf(element: Element): string[] {
  let node: Element | null = element;
  let fiber: Fiber | null = null;
  while (node && !fiber) {
    const key = Object.keys(node).find((name) =>
      name.startsWith("__reactFiber$"),
    );
    fiber = key
      ? ((node as unknown as Record<string, Fiber>)[key] ?? null)
      : null;
    node = node.parentElement;
  }
  const names: string[] = [];
  for (let step = 0; fiber && names.length < 3 && step < 400; step += 1) {
    const name = nameOf(fiber.type);
    // Built names are short in production; only real words name a part.
    if (
      name &&
      /^[A-Z][A-Za-z0-9]{2,40}$/.test(name) &&
      !PLAIN.has(name) &&
      names[names.length - 1] !== name
    ) {
      names.push(name);
    }
    fiber = fiber.return ?? null;
  }
  return names;
}

const GENERATED_ID = /^:|«|[0-9a-f]{8,}|\d{3,}/i;

function escape(value: string): string {
  return typeof CSS !== "undefined" && CSS.escape
    ? CSS.escape(value)
    : value.replace(/[^\w-]/g, "\\$&");
}

/** A short CSS path to the element, stopping at a test id or a stable id. */
export function selectorOf(element: Element): string {
  const parts: string[] = [];
  let node: Element | null = element;
  while (node && node !== document.body && parts.length < 5) {
    const testid = node.getAttribute("data-testid");
    if (testid) {
      parts.unshift(`[data-testid="${testid.replace(/"/g, "")}"]`);
      break;
    }
    if (node.id && !GENERATED_ID.test(node.id)) {
      parts.unshift(`#${escape(node.id)}`);
      break;
    }
    let part = node.localName;
    const classes = Array.from(node.classList)
      .filter((name) => name.length <= 48)
      .slice(0, 2);
    if (classes.length)
      part += classes.map((name) => `.${escape(name)}`).join("");
    const parent: Element | null = node.parentElement;
    if (parent) {
      const same = Array.from(parent.children).filter(
        (child) => child.localName === node!.localName,
      );
      if (same.length > 1) part += `:nth-of-type(${same.indexOf(node) + 1})`;
    }
    parts.unshift(part);
    node = parent;
  }
  return parts.join(" > ").slice(0, 400);
}

export function describe(element: Element, mark: ScrollMark | null): Picked {
  const rect = element.getBoundingClientRect();
  const testid = element.closest("[data-testid]")?.getAttribute("data-testid");
  const role = element.getAttribute("role") ?? undefined;
  return {
    selector: selectorOf(element),
    ...(testid ? { testid: testid.slice(0, 80) } : {}),
    components: componentsOf(element),
    tag: element.localName,
    ...(role ? { role: role.slice(0, 40) } : {}),
    box: {
      x: Math.round(rect.left),
      y: Math.round(rect.top),
      w: Math.round(rect.width),
      h: Math.round(rect.height),
    },
    moved: movedSince(mark, element),
  };
}

/** "LeadRow · button" for the outline's tag and the comment list. */
export function shortName(picked: Picked): string {
  const first = picked.components[0];
  const what = picked.testid ?? picked.role ?? picked.tag;
  return first ? `${first} · ${what}` : what;
}

// ---------- Picking ----------

const LAYER_STYLE =
  "position:fixed;inset:0;margin:0;padding:0;border:0;background:transparent;pointer-events:none;overflow:visible;z-index:2147483646;width:100vw;height:100vh;max-width:none;max-height:none";

function layer(): HTMLElement {
  const host = document.createElement("div");
  host.setAttribute("data-capture-skip", "");
  host.setAttribute("aria-hidden", "true");
  host.style.cssText = LAYER_STYLE;
  // The top layer, so the outline shows over open sheets and dialogs too.
  if ("popover" in host) host.setAttribute("popover", "manual");
  document.body.appendChild(host);
  try {
    (host as HTMLElement & { showPopover?: () => void }).showPopover?.();
  } catch {
    // Not in the top layer here; the fixed layer still sits over the page.
  }
  return host;
}

const BAR_TEXT = {
  mouse: "Click the part of the screen you mean.",
  touch: "Tap the part of the screen you mean.",
};

/**
 * Lets the person pick one part of the screen. Resolves with what it is, or
 * null when they stop (Esc, Cancel). The page underneath never reacts.
 */
export function pickElement(mark: ScrollMark | null): Promise<Picked | null> {
  return new Promise((resolve) => {
    const host = layer();
    const outline = document.createElement("div");
    outline.style.cssText =
      "position:fixed;display:none;box-sizing:border-box;border:2px solid var(--sx-accent, royalblue);background:color-mix(in srgb, var(--sx-accent, royalblue) 12%, transparent);border-radius:4px;pointer-events:none;transition:all 60ms linear";
    const tag = document.createElement("div");
    tag.style.cssText =
      "position:fixed;display:none;max-width:70vw;padding:2px 8px;border-radius:6px;background:var(--sx-accent, royalblue);color:var(--sx-accent-ink, white);font:600 12px/18px system-ui,-apple-system,'Segoe UI',sans-serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;pointer-events:none";
    const bar = document.createElement("div");
    bar.style.cssText =
      "position:fixed;left:50%;bottom:calc(16px + env(safe-area-inset-bottom, 0px));translate:-50% 0;display:flex;align-items:center;gap:8px;max-width:calc(100vw - 24px);padding:8px 8px 8px 14px;border-radius:999px;background:var(--sx-ink, black);color:var(--sx-surface, white);box-shadow:0 8px 28px rgba(0,0,0,.28);font:600 13px/1.3 system-ui,-apple-system,'Segoe UI',sans-serif;pointer-events:none";
    const words = document.createElement("span");
    words.style.cssText =
      "min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
    const pill =
      "flex:none;min-height:36px;padding:0 14px;border:0;border-radius:999px;font:inherit;cursor:pointer";
    const use = document.createElement("button");
    use.type = "button";
    use.textContent = "Comment on this";
    use.style.cssText = `${pill};display:none;background:var(--sx-accent, royalblue);color:var(--sx-accent-ink, white)`;
    const stop = document.createElement("button");
    stop.type = "button";
    stop.textContent = "Cancel";
    stop.style.cssText = `${pill};background:transparent;color:inherit;box-shadow:inset 0 0 0 1px currentColor`;
    bar.append(words, use, stop);
    host.append(outline, tag, bar);

    let current: Element | null = null;
    let touch = false;
    let start: { x: number; y: number } | null = null;
    words.textContent = BAR_TEXT.mouse;

    const under = (x: number, y: number): Element | null => {
      for (const element of document.elementsFromPoint(x, y)) {
        if (
          host.contains(element) ||
          element === document.documentElement ||
          element === document.body
        )
          continue;
        return element;
      }
      return null;
    };
    const show = (element: Element | null) => {
      current = element;
      if (!element) {
        outline.style.display = "none";
        tag.style.display = "none";
        use.style.display = "none";
        return;
      }
      const rect = element.getBoundingClientRect();
      Object.assign(outline.style, {
        display: "block",
        left: `${rect.left}px`,
        top: `${rect.top}px`,
        width: `${rect.width}px`,
        height: `${rect.height}px`,
      });
      tag.textContent = shortName(describe(element, null));
      Object.assign(tag.style, {
        display: "block",
        left: `${Math.max(4, Math.min(rect.left, window.innerWidth - 160))}px`,
        top: `${rect.top > 26 ? rect.top - 24 : Math.min(window.innerHeight - 24, rect.bottom + 4)}px`,
      });
      if (touch) use.style.display = "block";
    };
    const inside = (button: HTMLElement, x: number, y: number) => {
      if (button.style.display === "none") return false;
      const rect = button.getBoundingClientRect();
      return (
        x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom
      );
    };
    let done = false;
    const finish = (picked: Picked | null) => {
      if (done) return;
      done = true;
      // The press that picked still has its mouseup, click or touchend to come:
      // they are swallowed a moment longer, so neither the app nor the reporter
      // coming back acts on them.
      window.setTimeout(() => {
        for (const [name, handler] of listeners)
          window.removeEventListener(name, handler, true);
      }, 400);
      try {
        (host as HTMLElement & { hidePopover?: () => void }).hidePopover?.();
      } catch {
        // Already hidden.
      }
      host.remove();
      resolve(picked);
    };
    const pick = () => {
      if (current) finish(describe(current, mark));
    };
    const swallow = (event: Event) => {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
    };

    const onMove = (event: PointerEvent) => {
      if (done) return;
      if (event.pointerType === "mouse" || event.pointerType === "pen") {
        touch = false;
        words.textContent = BAR_TEXT.mouse;
        show(under(event.clientX, event.clientY));
      }
      event.stopPropagation();
    };
    const onDown = (event: PointerEvent) => {
      // Presses never reach the app; a touch may still scroll the page.
      event.stopPropagation();
      event.stopImmediatePropagation();
      if (event.pointerType === "mouse") event.preventDefault();
      if (!done) start = { x: event.clientX, y: event.clientY };
    };
    const onUp = (event: PointerEvent) => {
      swallow(event);
      if (done) return;
      const begin = start;
      start = null;
      const { clientX: x, clientY: y } = event;
      if (inside(stop, x, y)) return finish(null);
      if (inside(use, x, y)) return pick();
      if (begin && Math.hypot(x - begin.x, y - begin.y) > 10) return; // a scroll
      if (event.pointerType === "mouse" || event.pointerType === "pen") {
        show(under(x, y));
        return pick();
      }
      touch = true;
      words.textContent = BAR_TEXT.touch;
      const found = under(x, y);
      // A second tap on the outlined part picks it.
      if (found && found === current) return pick();
      show(found);
    };
    const onKey = (event: KeyboardEvent) => {
      if (done) return;
      if (event.key === "Escape") {
        swallow(event);
        finish(null);
      } else if (event.key === "Enter" && current) {
        swallow(event);
        pick();
      }
    };
    const onScroll = () => {
      if (done) return;
      if (current?.isConnected) show(current);
      else show(null);
    };
    const listeners: Array<[string, EventListener]> = [
      ["pointermove", onMove as EventListener],
      ["pointerdown", onDown as EventListener],
      ["pointerup", onUp as EventListener],
      ["mousedown", swallow],
      ["mouseup", swallow],
      ["click", swallow],
      ["dblclick", swallow],
      ["contextmenu", swallow],
      ["touchend", swallow],
      ["keydown", onKey as EventListener],
      ["scroll", onScroll],
    ];
    for (const [name, handler] of listeners) {
      window.addEventListener(name, handler, { capture: true, passive: false });
    }
  });
}

/** The part's own small picture, cut from a fresh picture of the screen. */
export function cropOf(shot: Blob, box: Box): Promise<Blob | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(shot);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      const scale = image.naturalWidth / Math.max(1, window.innerWidth);
      const pad = 12;
      const x = Math.max(0, (box.x - pad) * scale);
      const y = Math.max(0, (box.y - pad) * scale);
      const w = Math.min(image.naturalWidth - x, (box.w + pad * 2) * scale);
      const h = Math.min(image.naturalHeight - y, (box.h + pad * 2) * scale);
      if (w < 4 || h < 4) return resolve(null);
      const fit = Math.min(1, 640 / Math.max(w, h));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(w * fit));
      canvas.height = Math.max(1, Math.round(h * fit));
      const context = canvas.getContext("2d");
      if (!context) return resolve(null);
      context.drawImage(image, x, y, w, h, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(
        (webp) => {
          if (webp?.type === "image/webp") return resolve(webp);
          canvas.toBlob((jpeg) => resolve(jpeg), "image/jpeg", 0.86);
        },
        "image/webp",
        0.84,
      );
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      resolve(null);
    };
    image.src = url;
  });
}
