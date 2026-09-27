import { createElement, type SVGProps } from "react";

type Attributes = Readonly<Record<string, string>>;
type GlyphNode = Readonly<{
  tag: "circle" | "path" | "rect";
  attrs: Attributes;
}>;
type GlyphDefinition = Readonly<{
  root: Attributes;
  nodes: readonly GlyphNode[];
}>;

const box = { viewBox: "0 0 24 24" } as const;
const line = {
  ...box,
  fill: "none",
  stroke: "currentColor",
  "stroke-width": "1.75",
  "stroke-linecap": "round",
  "stroke-linejoin": "round",
} as const;
const dot = (cx: string, cy: string, r: string): GlyphNode => ({
  tag: "circle",
  attrs: { cx, cy, r, fill: "currentColor", stroke: "none" },
});
const circle = (cx: string, cy: string, r: string, extra: Attributes = {}) =>
  ({ tag: "circle", attrs: { cx, cy, r, ...extra } }) as const;
const path = (d: string, extra: Attributes = {}) =>
  ({ tag: "path", attrs: { d, ...extra } }) as const;
const rect = (
  x: string,
  y: string,
  width: string,
  height: string,
  rx: string,
) => ({ tag: "rect", attrs: { x, y, width, height, rx } }) as const;

/**
 * Inline copy of assets/glyphs/lightbox-glyphs.svg. Inline symbols also render
 * inside the learner-web embed, where /lightbox/ is not served. Parity with the
 * sprite is asserted by glyph.test.tsx.
 */
export const GLYPHS = {
  strength: {
    root: line,
    nodes: [circle("12", "12", "9"), path("M7.8 12.6l2.7 2.6 5.7-6.2")],
  },
  focus: {
    root: line,
    nodes: [
      circle("12", "12", "8.5"),
      circle("12", "12", "4"),
      path("M12 1.8v3.4M12 18.8v3.4M1.8 12h3.4M18.8 12h3.4"),
      dot("12", "12", ".9"),
    ],
  },
  missed: {
    root: line,
    nodes: [
      path("M12 2.8l9.2 9.2-9.2 9.2L2.8 12z"),
      path("M12 8.2v4.6"),
      dot("12", "16", ".95"),
    ],
  },
  hypothesis: {
    root: line,
    nodes: [
      circle("12", "12", "9", { "stroke-dasharray": "2.6 2.9" }),
      path("M9.6 9.4a2.5 2.5 0 1 1 3.6 2.3c-.8.4-1.2.9-1.2 1.8"),
      dot("12", "16.6", ".95"),
    ],
  },
  objection: {
    root: line,
    nodes: [
      path("M4 5.5h16v10H11l-4.5 3.5v-3.5H4z"),
      path("M9 9l6 3M15 9l-6 3"),
    ],
  },
  quote: {
    root: line,
    nodes: [
      path("M4 6.5h16v10h-8.5L7 20v-3.5H4z"),
      path("M8 11.5v1M10.5 9.8v4.4M13 10.6v2.8M15.5 11v2"),
    ],
  },
  "play-clip": {
    root: line,
    nodes: [
      rect("3", "4", "18", "16", "4"),
      path("M10 8.8v6.4l5.2-3.2z", { fill: "currentColor" }),
    ],
  },
  "seek-moment": {
    root: line,
    nodes: [
      path("M3 12h3M8 8v8M11 5v14M14 9v6M17 7v10M20 11v2"),
      path("M11 2.5l-1.6 1.6M11 2.5l1.6 1.6"),
    ],
  },
  "speaker-seller": {
    root: line,
    nodes: [
      circle("10", "8", "3.5"),
      path("M3.5 19.5c.8-3.4 3.4-5.5 6.5-5.5s5.7 2.1 6.5 5.5"),
      path("M18.5 6.5a4 4 0 0 1 0 5M20.8 4.5a7 7 0 0 1 0 9"),
    ],
  },
  "speaker-buyer": {
    root: line,
    nodes: [
      circle("12", "8", "3.5"),
      path("M5.5 19.5c.8-3.4 3.4-5.5 6.5-5.5s5.7 2.1 6.5 5.5"),
    ],
  },
  "skill-observed": {
    root: box,
    nodes: [circle("12", "12", "7.5", { fill: "currentColor" })],
  },
  "skill-insufficient": {
    root: {
      ...box,
      fill: "none",
      stroke: "currentColor",
      "stroke-width": "1.75",
      "stroke-linecap": "round",
    },
    nodes: [circle("12", "12", "7.5", { "stroke-dasharray": "1.2 3.2" })],
  },
  "skill-conflicted": {
    root: box,
    nodes: [
      circle("12", "12", "7.5", {
        fill: "none",
        stroke: "currentColor",
        "stroke-width": "1.75",
      }),
      path("M12 4.5a7.5 7.5 0 0 1 0 15z", { fill: "currentColor" }),
    ],
  },
  "skill-na": {
    root: {
      ...box,
      fill: "none",
      stroke: "currentColor",
      "stroke-width": "1.75",
      "stroke-linecap": "round",
    },
    nodes: [circle("12", "12", "7.5"), path("M8.5 12h7")],
  },
  "chapter-overview": {
    root: line,
    nodes: [
      rect("3.5", "4", "17", "16", "3"),
      path("M7.5 9h9M7.5 12.5h6M7.5 16h4"),
    ],
  },
  "chapter-moments": {
    root: line,
    nodes: [
      path("M3 18h18"),
      path("M6 18v-5M10 18V8M14 18v-8M18 18v-3"),
      circle("10", "5", "1.6"),
    ],
  },
  "chapter-skills": {
    root: line,
    nodes: [
      circle("6", "7", "2.5"),
      circle("18", "7", "2.5"),
      circle("12", "17", "2.5"),
      path("M8.2 8.3l2.4 6.3M15.8 8.3l-2.4 6.3M8.5 7h7"),
    ],
  },
  "chapter-prospect": {
    root: line,
    nodes: [
      circle("9", "8.5", "3.5"),
      path("M2.8 19.5c.8-3.2 3.3-5.3 6.2-5.3 1.5 0 2.9.5 4 1.5"),
      circle("17.5", "16.5", "3.2"),
      path("M19.8 18.8L22 21"),
    ],
  },
  "chapter-plan": {
    root: line,
    nodes: [
      rect("4", "3.5", "16", "17", "3"),
      path(
        "M8 9l1.6 1.6L12.5 7.8M8 15l1.6 1.6 2.9-2.8M14.5 9.5H17M14.5 15.5H17",
      ),
    ],
  },
  "chapter-transcript": {
    root: line,
    nodes: [path("M4 5h11M4 9h16M4 13h9M4 17h13"), path("M17 13.5l2 2 2-2")],
  },
  upload: {
    root: line,
    nodes: [
      path("M12 15.5V4M7.5 8.5L12 4l4.5 4.5"),
      path("M4 14.5v3a2.5 2.5 0 0 0 2.5 2.5h11a2.5 2.5 0 0 0 2.5-2.5v-3"),
    ],
  },
  listen: {
    root: line,
    nodes: [path("M4 12h1.5M7.5 8v8M10.5 5v14M13.5 9v6M16.5 7v10M19.5 11v2")],
  },
  understand: {
    root: line,
    nodes: [
      circle("10.5", "10.5", "6.5"),
      path("M15.5 15.5L21 21"),
      path("M7 10.5h1M9.2 8v5M11.6 9v3M14 10.5h.5"),
    ],
  },
  write: {
    root: line,
    nodes: [path("M14.5 4.5l5 5L9 20H4v-5z"), path("M12.5 6.5l5 5")],
  },
  saved: {
    root: line,
    nodes: [path("M6 3.5h12v17l-6-4-6 4z"), path("M9 9.5l2 2 4-4")],
  },
  shield: {
    root: line,
    nodes: [
      path("M12 3l7.5 3v5.5c0 4.5-3.2 8.2-7.5 9.5-4.3-1.3-7.5-5-7.5-9.5V6z"),
      path("M9 12l2.2 2.2L15.5 10"),
    ],
  },
  copy: {
    root: line,
    nodes: [
      rect("8", "8", "12", "12", "2.5"),
      path(
        "M16 8V6.5A2.5 2.5 0 0 0 13.5 4h-7A2.5 2.5 0 0 0 4 6.5v7A2.5 2.5 0 0 0 6.5 16H8",
      ),
    ],
  },
  retry: {
    root: line,
    nodes: [path("M20 12a8 8 0 1 1-2.4-5.7"), path("M20 4.5v4h-4")],
  },
} as const satisfies Record<string, GlyphDefinition>;

export type GlyphName = keyof typeof GLYPHS;

const reactNames: Readonly<Record<string, string>> = {
  "stroke-width": "strokeWidth",
  "stroke-linecap": "strokeLinecap",
  "stroke-linejoin": "strokeLinejoin",
  "stroke-dasharray": "strokeDasharray",
};

function props(attrs: Attributes) {
  return Object.fromEntries(
    Object.entries(attrs).map(([name, value]) => [
      reactNames[name] ?? name,
      value,
    ]),
  );
}

/** Semantic glyphs inherit currentColor; meaning also lives in adjacent text. */
export function Glyph({
  name,
  size = 20,
  label,
  className,
  ...rest
}: Omit<SVGProps<SVGSVGElement>, "name"> & {
  name: GlyphName;
  size?: number;
  /** Only for a glyph that carries meaning on its own. */
  label?: string;
}) {
  const glyph: GlyphDefinition = GLYPHS[name];
  return (
    <svg
      {...rest}
      {...props(glyph.root)}
      className={className}
      width={size}
      height={size}
      focusable="false"
      data-glyph={name}
      {...(label
        ? { role: "img", "aria-label": label }
        : { "aria-hidden": true })}
    >
      {glyph.nodes.map(({ tag, attrs }, index) =>
        createElement(tag, { key: index, ...props(attrs) }),
      )}
    </svg>
  );
}
