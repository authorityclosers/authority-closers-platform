/**
 * The advanced reporter's marks on a picture of the screen (owner, 31 Oct
 * 2026): arrows, boxes, circles, pen, highlighter, text, blur and a crop, kept
 * as shapes over the untouched picture so every step can be undone and redone.
 * Points are in the picture's own pixels. `paint` draws the picture with its
 * marks; `flatten` makes the picture that is sent, cropped, with the marks and
 * the numbered element pins burnt in. Everything happens on the device.
 */

export type Point = Readonly<{ x: number; y: number }>;
export type Box = Readonly<{ x: number; y: number; w: number; h: number }>;

export type Tool =
  | "arrow"
  | "rect"
  | "ellipse"
  | "pen"
  | "highlight"
  | "text"
  | "blur"
  | "crop";

type Drag = Readonly<{
  id: number;
  kind: "arrow" | "rect" | "ellipse" | "blur";
  color: string;
  width: number;
  from: Point;
  to: Point;
}>;
type Stroke = Readonly<{
  id: number;
  kind: "pen" | "highlight";
  color: string;
  width: number;
  points: readonly Point[];
}>;
type Label = Readonly<{
  id: number;
  kind: "text";
  color: string;
  size: number;
  at: Point;
  text: string;
}>;
export type Shape = Drag | Stroke | Label;

export type Markup = Readonly<{ shapes: readonly Shape[]; crop: Box | null }>;

/** A numbered element comment, drawn where the element sat on the picture. */
export type Pin = Readonly<{ n: number; box: Box }>;

export const EMPTY: Markup = { shapes: [], crop: null };

// ---------- History ----------

const STEPS = 60;

export type History = Readonly<{
  past: readonly Markup[];
  now: Markup;
  future: readonly Markup[];
}>;

export const startHistory = (now: Markup = EMPTY): History => ({
  past: [],
  now,
  future: [],
});

export function commit(history: History, next: Markup): History {
  if (next === history.now) return history;
  return {
    past: [...history.past, history.now].slice(-STEPS),
    now: next,
    future: [],
  };
}

export function undo(history: History): History {
  const last = history.past[history.past.length - 1];
  if (!last) return history;
  return {
    past: history.past.slice(0, -1),
    now: last,
    future: [history.now, ...history.future],
  };
}

export function redo(history: History): History {
  const [next, ...rest] = history.future;
  if (!next) return history;
  return { past: [...history.past, history.now], now: next, future: rest };
}

export const edited = (history: History) =>
  history.now.shapes.length > 0 || history.now.crop !== null;

// ---------- Sizes ----------

/** A line that reads at the picture's size: about 1/250 of its long edge. */
export function lineWidth(width: number, height: number, tool: Tool): number {
  const base = Math.max(3, Math.round(Math.max(width, height) / 250));
  return tool === "highlight" ? base * 5 : base;
}

export function textSize(width: number, height: number): number {
  return Math.max(16, Math.round(Math.max(width, height) / 45));
}

/** A box from two corners, with a positive width and height. */
export function boxOf(from: Point, to: Point): Box {
  return {
    x: Math.min(from.x, to.x),
    y: Math.min(from.y, to.y),
    w: Math.abs(to.x - from.x),
    h: Math.abs(to.y - from.y),
  };
}

/** A box kept inside the picture; null when it is too small to mean anything. */
export function clampBox(box: Box, width: number, height: number): Box | null {
  const x = Math.max(0, Math.min(width, box.x));
  const y = Math.max(0, Math.min(height, box.y));
  const w = Math.min(width, box.x + box.w) - x;
  const h = Math.min(height, box.y + box.h) - y;
  return w >= 8 && h >= 8
    ? { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) }
    : null;
}

/** A drag shorter than this is a tap, not a mark. */
export function tooSmall(shape: Shape): boolean {
  if ("text" in shape) return shape.text.trim() === "";
  if ("points" in shape) return shape.points.length < 2;
  return Math.hypot(shape.to.x - shape.from.x, shape.to.y - shape.from.y) < 6;
}

// ---------- Painting ----------

export type Canvas2D = CanvasRenderingContext2D;

/** The picture pixelated inside one box, so nothing in it can be read. */
function pixelate(
  context: Canvas2D,
  picture: CanvasImageSource,
  box: Box,
  block: number,
) {
  if (box.w < 2 || box.h < 2) return;
  const small = document.createElement("canvas");
  small.width = Math.max(1, Math.ceil(box.w / block));
  small.height = Math.max(1, Math.ceil(box.h / block));
  const shrink = small.getContext("2d");
  if (!shrink) return;
  shrink.drawImage(
    picture,
    box.x,
    box.y,
    box.w,
    box.h,
    0,
    0,
    small.width,
    small.height,
  );
  const smoothing = context.imageSmoothingEnabled;
  context.imageSmoothingEnabled = false;
  context.drawImage(
    small,
    0,
    0,
    small.width,
    small.height,
    box.x,
    box.y,
    box.w,
    box.h,
  );
  context.imageSmoothingEnabled = smoothing;
}

function arrow(context: Canvas2D, shape: Drag) {
  const { from, to, width } = shape;
  const angle = Math.atan2(to.y - from.y, to.x - from.x);
  const head = Math.max(12, width * 4);
  const back = {
    x: to.x - Math.cos(angle) * head * 0.8,
    y: to.y - Math.sin(angle) * head * 0.8,
  };
  context.beginPath();
  context.moveTo(from.x, from.y);
  context.lineTo(back.x, back.y);
  context.stroke();
  context.beginPath();
  context.moveTo(to.x, to.y);
  context.lineTo(
    to.x - head * Math.cos(angle - Math.PI / 7),
    to.y - head * Math.sin(angle - Math.PI / 7),
  );
  context.lineTo(
    to.x - head * Math.cos(angle + Math.PI / 7),
    to.y - head * Math.sin(angle + Math.PI / 7),
  );
  context.closePath();
  context.fill();
}

function stroke(context: Canvas2D, points: readonly Point[]) {
  const [first, ...rest] = points;
  if (!first) return;
  context.beginPath();
  context.moveTo(first.x, first.y);
  // Smooth through the midpoints so a quick line is not jagged.
  for (let index = 0; index < rest.length; index += 1) {
    const point = rest[index]!;
    const next = rest[index + 1];
    if (next) {
      context.quadraticCurveTo(
        point.x,
        point.y,
        (point.x + next.x) / 2,
        (point.y + next.y) / 2,
      );
    } else {
      context.lineTo(point.x, point.y);
    }
  }
  context.stroke();
}

/** A dark halo round light text, a white one round the rest. */
export function haloFor(color: string): string {
  const named: Record<string, string> = { white: "black", black: "white" };
  if (named[color]) return named[color];
  const rgb = /rgba?\((\d+)[,\s]+(\d+)[,\s]+(\d+)/.exec(color);
  if (!rgb) return "white";
  const [r, g, b] = rgb.slice(1).map(Number) as [number, number, number];
  return 0.299 * r + 0.587 * g + 0.114 * b > 165 ? "black" : "white";
}

/** Text with a halo in the opposite tone, readable on any screen. */
function label(context: Canvas2D, shape: Label) {
  const halo = haloFor(shape.color);
  context.font = `600 ${shape.size}px system-ui, -apple-system, "Segoe UI", sans-serif`;
  context.textBaseline = "top";
  context.lineJoin = "round";
  context.lineWidth = Math.max(3, shape.size / 5);
  context.strokeStyle = halo;
  shape.text.split("\n").forEach((line, index) => {
    const y = shape.at.y + index * shape.size * 1.2;
    context.strokeText(line, shape.at.x, y);
    context.fillText(line, shape.at.x, y);
  });
}

function draw(context: Canvas2D, shape: Shape) {
  context.save();
  context.strokeStyle = shape.color;
  context.fillStyle = shape.color;
  context.lineCap = "round";
  context.lineJoin = "round";
  switch (shape.kind) {
    case "arrow":
      context.lineWidth = shape.width;
      arrow(context, shape);
      break;
    case "rect": {
      const box = boxOf(shape.from, shape.to);
      context.lineWidth = shape.width;
      context.strokeRect(box.x, box.y, box.w, box.h);
      break;
    }
    case "ellipse": {
      const box = boxOf(shape.from, shape.to);
      context.lineWidth = shape.width;
      context.beginPath();
      context.ellipse(
        box.x + box.w / 2,
        box.y + box.h / 2,
        Math.max(1, box.w / 2),
        Math.max(1, box.h / 2),
        0,
        0,
        Math.PI * 2,
      );
      context.stroke();
      break;
    }
    case "pen":
      context.lineWidth = shape.width;
      stroke(context, shape.points);
      break;
    case "highlight":
      context.globalAlpha = 0.35;
      context.lineCap = "square";
      context.lineWidth = shape.width;
      stroke(context, shape.points);
      break;
    case "text":
      label(context, shape);
      break;
    case "blur":
      break;
  }
  context.restore();
}

/** A numbered marker for an element comment: a ring round it and its number. */
function pin(context: Canvas2D, item: Pin, scale: number, colors: PinColors) {
  const { box } = item;
  const line = Math.max(2, scale * 2);
  context.save();
  context.setLineDash([line * 3, line * 2]);
  context.lineWidth = line;
  context.strokeStyle = colors.fill;
  context.strokeRect(box.x, box.y, box.w, box.h);
  context.setLineDash([]);
  const radius = Math.max(11, scale * 13);
  const x = Math.max(radius, box.x);
  const y = Math.max(radius, box.y);
  context.beginPath();
  context.arc(x, y, radius, 0, Math.PI * 2);
  context.fillStyle = colors.fill;
  context.fill();
  context.lineWidth = Math.max(2, scale * 2);
  context.strokeStyle = colors.ink;
  context.stroke();
  context.fillStyle = colors.ink;
  context.font = `700 ${Math.round(radius * 1.1)}px system-ui, -apple-system, "Segoe UI", sans-serif`;
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(String(item.n), x, y + radius * 0.04);
  context.restore();
}

export type PinColors = Readonly<{ fill: string; ink: string }>;

export type PaintOptions = Readonly<{
  /** A shape being drawn now, not yet in the history. */
  draft?: Shape | null;
  pins?: readonly Pin[];
  pinColors?: PinColors;
  /** Picture pixels per screen pixel, so pins keep their size on screen. */
  scale?: number;
  /** The editor shows the crop as a frame over a dimmed picture. */
  showCrop?: boolean;
  dim?: string;
}>;

/** The picture with its marks, in the picture's own pixels (the caller scales). */
export function paint(
  context: Canvas2D,
  picture: CanvasImageSource,
  size: Readonly<{ width: number; height: number }>,
  markup: Markup,
  options: PaintOptions = {},
) {
  const shapes = options.draft
    ? [...markup.shapes, options.draft]
    : markup.shapes;
  context.drawImage(picture, 0, 0, size.width, size.height);
  // Blur hides the picture itself, so it goes first: marks stay readable over it.
  const block = Math.max(8, Math.round(Math.max(size.width, size.height) / 90));
  for (const shape of shapes) {
    if (shape.kind === "blur") {
      pixelate(context, picture, boxOf(shape.from, shape.to), block);
    }
  }
  for (const shape of shapes) {
    if (shape.kind !== "blur") draw(context, shape);
  }
  const colors = options.pinColors ?? { fill: "crimson", ink: "white" };
  for (const item of options.pins ?? []) {
    pin(context, item, options.scale ?? 1, colors);
  }
  if (options.showCrop && markup.crop) {
    const { x, y, w, h } = markup.crop;
    context.save();
    context.fillStyle = options.dim ?? "rgba(0, 0, 0, 0.55)";
    context.beginPath();
    context.rect(0, 0, size.width, size.height);
    context.rect(x, y, w, h);
    context.fill("evenodd");
    context.setLineDash([8 * (options.scale ?? 1), 6 * (options.scale ?? 1)]);
    context.lineWidth = 2 * (options.scale ?? 1);
    context.strokeStyle = "white";
    context.strokeRect(x, y, w, h);
    context.restore();
  }
}

/** The picture that is sent: cropped, with every mark and pin burnt in. */
export function flatten(
  picture: CanvasImageSource,
  size: Readonly<{ width: number; height: number }>,
  markup: Markup,
  options: Omit<PaintOptions, "draft" | "showCrop"> = {},
): Promise<Blob | null> {
  const crop = markup.crop ?? { x: 0, y: 0, w: size.width, h: size.height };
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(crop.w));
  canvas.height = Math.max(1, Math.round(crop.h));
  const context = canvas.getContext("2d");
  if (!context) return Promise.resolve(null);
  context.translate(-crop.x, -crop.y);
  paint(context, picture, size, markup, options);
  return new Promise((resolve) => {
    canvas.toBlob(
      (webp) => {
        if (webp?.type === "image/webp") return resolve(webp);
        canvas.toBlob((jpeg) => resolve(jpeg), "image/jpeg", 0.88);
      },
      "image/webp",
      0.86,
    );
  });
}
