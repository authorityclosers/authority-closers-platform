/**
 * A picture of the screen for a bug report, made on the device.
 *
 * The visible part of the page is copied with its computed styles into an SVG
 * foreignObject, drawn on a canvas and saved as WebP (JPEG where WebP cannot
 * be written). It is what the person sees: inner panels keep their scroll,
 * fields keep what was typed (passwords are dotted). Left out: sheets and
 * dialogs, the corner cards, anything marked data-capture-skip, video, frames
 * and pictures from other sites (blank boxes). Nothing leaves the device here;
 * the person sees the picture and chooses to send it.
 *
 * Fails quietly: any problem, or more than eight seconds, gives null, and the
 * reporter offers "Choose a picture" instead.
 */

const SKIP =
  "dialog, [data-capture-skip], script, noscript, template, iframe, video, audio, object, embed, link, meta, style";
const SVG_NS = "http://www.w3.org/2000/svg";
const MAX_NODES = 8000;
const MAX_EDGE = 1600;
const MAX_INLINE_BYTES = 3 * 1024 * 1024;
const TIME_LIMIT_MS = 8000;
// A picture has nothing to scroll: no scroll bars over its panels.
const NO_SCROLLBARS =
  "*{scrollbar-width:none!important}*::-webkit-scrollbar{display:none!important}";

type Run = {
  budget: number;
  width: number;
  height: number;
  defaults: Map<string, Map<string, string>>;
  sandbox: Document;
  pseudo: string[];
  images: Array<[HTMLImageElement, HTMLImageElement]>;
  serial: number;
};

function defaultsFor(run: Run, element: Element): Map<string, string> {
  const svg = element.namespaceURI === SVG_NS;
  const key = `${svg ? "svg:" : ""}${element.localName}`;
  const known = run.defaults.get(key);
  if (known) return known;
  const probe = svg
    ? run.sandbox.createElementNS(SVG_NS, element.localName)
    : run.sandbox.createElement(element.localName);
  const host = svg
    ? run.sandbox.body.appendChild(run.sandbox.createElementNS(SVG_NS, "svg"))
    : run.sandbox.body;
  host.appendChild(probe);
  const style = run.sandbox.defaultView!.getComputedStyle(probe);
  const values = new Map<string, string>();
  for (let index = 0; index < style.length; index += 1) {
    const name = style.item(index);
    values.set(name, style.getPropertyValue(name));
  }
  probe.remove();
  if (svg) host.remove();
  run.defaults.set(key, values);
  return values;
}

/** Only the properties that differ from the element's plain default. */
function styleText(
  style: CSSStyleDeclaration,
  defaults: Map<string, string>,
): string {
  const parts: string[] = [];
  for (let index = 0; index < style.length; index += 1) {
    const name = style.item(index);
    const value = style.getPropertyValue(name);
    if (defaults.get(name) !== value) parts.push(`${name}:${value}`);
  }
  return parts.join(";");
}

function outside(run: Run, element: Element): boolean {
  const box = element.getBoundingClientRect();
  return (
    box.bottom < 0 ||
    box.right < 0 ||
    box.top > run.height ||
    box.left > run.width
  );
}

function copyPseudo(run: Run, element: Element, out: Element) {
  for (const which of ["::before", "::after"] as const) {
    const style = getComputedStyle(element, which);
    const content = style.getPropertyValue("content");
    if (!content || content === "none" || content === "normal") continue;
    const name = `sxcap${(run.serial += 1)}`;
    out.classList.add(name);
    const parts: string[] = [];
    for (let index = 0; index < style.length; index += 1) {
      const property = style.item(index);
      parts.push(`${property}:${style.getPropertyValue(property)}`);
    }
    run.pseudo.push(`.${name}${which}{${parts.join(";")}}`);
  }
}

/** Lets the page breathe every so often, so typing in the sheet never stalls. */
function breathe(run: Run): Promise<void> | null {
  return run.budget % 120 === 0
    ? new Promise((resolve) => window.setTimeout(resolve, 0))
    : null;
}

async function copyNode(run: Run, node: Node): Promise<Node | null> {
  if (node.nodeType === Node.TEXT_NODE) {
    return document.createTextNode(node.textContent ?? "");
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return null;
  const element = node as Element;
  if (element.matches(SKIP) || run.budget <= 0) return null;
  run.budget -= 1;
  await breathe(run);
  const style = getComputedStyle(element);
  if (style.display === "none") return null;

  let out: Element;
  if (element instanceof HTMLCanvasElement) {
    out = document.createElement("img");
    try {
      out.setAttribute("src", element.toDataURL());
    } catch {
      // A canvas holding another site's pixels stays a blank box.
    }
  } else {
    out = element.cloneNode(false) as Element;
  }
  for (const attribute of Array.from(out.attributes)) {
    if (
      attribute.name.startsWith("on") ||
      attribute.name === "srcset" ||
      attribute.name === "sizes" ||
      attribute.name === "loading"
    ) {
      out.removeAttribute(attribute.name);
    }
  }
  const text = styleText(style, defaultsFor(run, element));
  if (text) out.setAttribute("style", text);

  if (element instanceof HTMLImageElement && out instanceof HTMLImageElement) {
    out.removeAttribute("src");
    run.images.push([element, out]);
  } else if (element instanceof HTMLInputElement) {
    if (element.type === "password") out.setAttribute("value", "••••••");
    else if (element.type === "checkbox" || element.type === "radio") {
      if (element.checked) out.setAttribute("checked", "");
      else out.removeAttribute("checked");
    } else out.setAttribute("value", element.value);
  } else if (element instanceof HTMLTextAreaElement) {
    out.textContent = element.value;
    return out;
  } else if (element instanceof HTMLSelectElement) {
    for (const option of Array.from(out.querySelectorAll("option"))) {
      option.removeAttribute("selected");
    }
  }

  // A box wholly off the screen keeps its size, not its insides.
  if (!(element instanceof SVGElement) && outside(run, element)) return out;
  if (element instanceof HTMLElement || element instanceof SVGSVGElement) {
    copyPseudo(run, element, out);
  }
  for (const child of Array.from(element.childNodes)) {
    const copied = await copyNode(run, child);
    if (copied) out.appendChild(copied);
  }
  if (element instanceof HTMLSelectElement) {
    const chosen = out.querySelectorAll("option")[element.selectedIndex];
    chosen?.setAttribute("selected", "");
  }
  // Inner panels keep their scroll: their children move up and left.
  const top = element.scrollTop;
  const left = element.scrollLeft;
  if (top || left) {
    for (const child of Array.from(out.children)) {
      if (!(child instanceof HTMLElement || child instanceof SVGElement))
        continue;
      const before = child.style.transform;
      child.style.transform = `translate(${-left}px, ${-top}px)${
        before && before !== "none" ? ` ${before}` : ""
      }`;
    }
  }
  return out;
}

function asDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(new Error("unreadable"));
    reader.readAsDataURL(blob);
  });
}

/** Same-site pictures go inside the copy; others stay blank boxes. */
async function inlineImages(run: Run) {
  let total = 0;
  for (const [original, copy] of run.images.slice(0, 30)) {
    const source = original.currentSrc || original.src;
    if (!source) continue;
    if (source.startsWith("data:")) {
      copy.setAttribute("src", source);
      continue;
    }
    let url: URL;
    try {
      url = new URL(source, window.location.href);
    } catch {
      continue;
    }
    if (url.origin !== window.location.origin && url.protocol !== "blob:")
      continue;
    try {
      const blob = await (
        await fetch(url, { credentials: "same-origin" })
      ).blob();
      total += blob.size;
      if (total > MAX_INLINE_BYTES || !blob.type.startsWith("image/")) continue;
      copy.setAttribute("src", await asDataUrl(blob));
    } catch {
      // Left blank.
    }
  }
}

/** The page's own fonts (same site), so the picture's text looks like the screen. */
async function fontRules(): Promise<string> {
  const rules: string[] = [];
  let total = 0;
  for (const sheet of Array.from(document.styleSheets)) {
    let list: CSSRuleList;
    try {
      list = sheet.cssRules;
    } catch {
      continue; // another site's sheet
    }
    for (const rule of Array.from(list)) {
      if (!(rule instanceof CSSFontFaceRule)) continue;
      let text = rule.cssText;
      const urls = [...text.matchAll(/url\(["']?([^"')]+)["']?\)/g)];
      let usable = true;
      for (const [whole, raw] of urls) {
        try {
          const url = new URL(raw, sheet.href ?? window.location.href);
          if (url.origin !== window.location.origin) {
            usable = false;
            break;
          }
          const blob = await (await fetch(url)).blob();
          total += blob.size;
          if (total > MAX_INLINE_BYTES) return rules.join("");
          text = text.replace(whole, `url("${await asDataUrl(blob)}")`);
        } catch {
          usable = false;
          break;
        }
      }
      if (usable) rules.push(text);
    }
  }
  return rules.join("");
}

function escapeStyle(text: string): string {
  return text.replace(/</g, "\\3c ").replace(/]]>/g, "]] >");
}

function drawn(
  svg: string,
  width: number,
  height: number,
): Promise<Blob | null> {
  return new Promise((resolve) => {
    const image = new Image();
    image.decoding = "async";
    image.onload = () => {
      const scale = Math.min(
        window.devicePixelRatio || 1,
        MAX_EDGE / Math.max(width, height),
      );
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(width * scale));
      canvas.height = Math.max(1, Math.round(height * scale));
      const context = canvas.getContext("2d");
      if (!context) return resolve(null);
      context.scale(scale, scale);
      try {
        context.drawImage(image, 0, 0, width, height);
        canvas.toBlob(
          (webp) => {
            if (webp?.type === "image/webp") return resolve(webp);
            canvas.toBlob((jpeg) => resolve(jpeg), "image/jpeg", 0.85);
          },
          "image/webp",
          0.82,
        );
      } catch {
        resolve(null); // a tainted canvas
      }
    };
    image.onerror = () => resolve(null);
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  });
}

async function capture(): Promise<Blob | null> {
  const width = window.innerWidth;
  const height = window.innerHeight;
  const frame = document.createElement("iframe");
  frame.setAttribute("aria-hidden", "true");
  frame.setAttribute("data-capture-skip", "");
  frame.style.cssText =
    "position:fixed;left:-10000px;top:0;width:10px;height:10px;border:0;visibility:hidden";
  document.body.appendChild(frame);
  try {
    const sandbox = frame.contentDocument;
    if (!sandbox?.body) return null;
    const run: Run = {
      budget: MAX_NODES,
      width,
      height,
      defaults: new Map(),
      sandbox,
      pseudo: [],
      images: [],
      serial: 0,
    };
    const page = document.createElement("div");
    page.setAttribute(
      "style",
      `${styleText(getComputedStyle(document.documentElement), defaultsFor(run, document.documentElement))};width:${width}px;height:${height}px;overflow:hidden;margin:0`,
    );
    const body = document.createElement("div");
    body.setAttribute(
      "style",
      `${styleText(getComputedStyle(document.body), defaultsFor(run, document.body))};margin:0;transform:translate(${-window.scrollX}px, ${-window.scrollY}px)`,
    );
    for (const child of Array.from(document.body.childNodes)) {
      const copied = await copyNode(run, child);
      if (copied) body.appendChild(copied);
    }
    page.appendChild(body);
    await inlineImages(run);
    const fonts = await fontRules().catch(() => "");
    const markup = new XMLSerializer().serializeToString(page);
    const svg =
      `<svg xmlns="${SVG_NS}" width="${width}" height="${height}">` +
      `<style>${escapeStyle(fonts + NO_SCROLLBARS + run.pseudo.join(""))}</style>` +
      `<foreignObject x="0" y="0" width="100%" height="100%">${markup}</foreignObject></svg>`;
    return await drawn(svg, width, height);
  } finally {
    frame.remove();
  }
}

/** A picture of what is on the screen now, or null. */
export function captureScreen(): Promise<Blob | null> {
  if (typeof window === "undefined" || typeof XMLSerializer === "undefined") {
    return Promise.resolve(null);
  }
  return Promise.race([
    capture().catch(() => null),
    new Promise<null>((resolve) =>
      window.setTimeout(() => resolve(null), TIME_LIMIT_MS),
    ),
  ]);
}
