"use client";

/**
 * The picture of the screen with its marks, drawn sharp on any screen (the
 * canvas has the device's pixels) and fitted to the room it has. Pointer
 * events, so a mouse, a pen and a finger all draw; the canvas takes the touch,
 * so drawing never scrolls the page. Text is typed where it is tapped; a crop
 * is a frame over the dimmed picture.
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import {
  boxOf,
  clampBox,
  lineWidth,
  paint,
  textSize,
  tooSmall,
  type Markup,
  type Pin,
  type Point,
  type Shape,
  type Tool,
} from "./annotate-model";
import styles from "./advanced-reporter.module.css";

export type CanvasColors = Readonly<{
  pinFill: string;
  pinInk: string;
}>;

type View = Readonly<{ width: number; height: number; fit: number }>;
type Typing = Readonly<{ at: Point; text: string }>;

export function AnnotateCanvas({
  picture,
  size,
  markup,
  tool,
  color,
  pins,
  colors,
  onCommit,
}: {
  picture: HTMLImageElement;
  size: Readonly<{ width: number; height: number }>;
  markup: Markup;
  tool: Tool;
  color: string;
  pins: readonly Pin[];
  colors: CanvasColors;
  onCommit: (next: Markup) => void;
}) {
  const room = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const draft = useRef<Shape | { kind: "crop"; from: Point; to: Point } | null>(
    null,
  );
  const frame = useRef(0);
  const serial = useRef(
    markup.shapes.reduce((top, s) => Math.max(top, s.id), 0),
  );
  const [view, setView] = useState<View | null>(null);
  const [typing, setTyping] = useState<Typing | null>(null);
  // The label being typed, read when it is placed: once, by Enter, a tap or leaving it.
  const typed = useRef<Typing | null>(null);
  const type = (next: Typing | null) => {
    typed.current = next;
    setTyping(next);
  };

  // Fit the picture to the room, whole, at the device's sharpness.
  useLayoutEffect(() => {
    const box = room.current;
    if (!box) return;
    const measure = () => {
      const width = box.clientWidth;
      const height = box.clientHeight;
      if (!width || !height) return;
      const fit = Math.min(width / size.width, height / size.height);
      setView({
        width: Math.max(1, Math.floor(size.width * fit)),
        height: Math.max(1, Math.floor(size.height * fit)),
        fit,
      });
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const watch = new ResizeObserver(measure);
    watch.observe(box);
    return () => watch.disconnect();
  }, [size.width, size.height]);

  const repaint = useCallback(() => {
    const target = canvas.current;
    const context = target?.getContext("2d");
    if (!target || !context || !view) return;
    const ratio = window.devicePixelRatio || 1;
    const width = Math.round(view.width * ratio);
    const height = Math.round(view.height * ratio);
    if (target.width !== width || target.height !== height) {
      target.width = width;
      target.height = height;
    }
    const scale = (view.width * ratio) / size.width;
    context.setTransform(1, 0, 0, 1, 0, 0);
    context.clearRect(0, 0, width, height);
    context.setTransform(scale, 0, 0, scale, 0, 0);
    const now = draft.current;
    const cropping = now?.kind === "crop";
    paint(
      context,
      picture,
      size,
      cropping ? { ...markup, crop: boxOf(now.from, now.to) } : markup,
      {
        draft: now && now.kind !== "crop" ? now : null,
        pins,
        pinColors: { fill: colors.pinFill, ink: colors.pinInk },
        scale: 1 / view.fit,
        // While a crop is being drawn, or with none chosen, the whole picture shows.
        showCrop: cropping || tool === "crop" || markup.crop !== null,
      },
    );
  }, [picture, size, markup, pins, colors, view, tool]);

  useEffect(() => {
    repaint();
  }, [repaint]);

  const later = () => {
    if (frame.current) return;
    frame.current = window.requestAnimationFrame(() => {
      frame.current = 0;
      repaint();
    });
  };
  useEffect(() => () => window.cancelAnimationFrame(frame.current), []);

  const at = (event: { clientX: number; clientY: number }): Point => {
    const box = canvas.current!.getBoundingClientRect();
    return {
      x: Math.max(
        0,
        Math.min(
          size.width,
          ((event.clientX - box.left) / box.width) * size.width,
        ),
      ),
      y: Math.max(
        0,
        Math.min(
          size.height,
          ((event.clientY - box.top) / box.height) * size.height,
        ),
      ),
    };
  };

  const place = () => {
    const now = typed.current;
    type(null);
    if (!now?.text.trim()) return;
    serial.current += 1;
    onCommit({
      ...markup,
      shapes: [
        ...markup.shapes,
        {
          id: serial.current,
          kind: "text",
          color,
          size: textSize(size.width, size.height),
          at: now.at,
          text: now.text.trim(),
        },
      ],
    });
  };

  const textScreen =
    typing && view
      ? {
          left: typing.at.x * view.fit,
          top: typing.at.y * view.fit,
          fontSize: Math.max(13, textSize(size.width, size.height) * view.fit),
        }
      : null;

  return (
    <div ref={room} className={styles.room} data-tool={tool}>
      {view ? (
        <div
          className={styles.paper}
          style={{ width: view.width, height: view.height }}
        >
          <canvas
            ref={canvas}
            className={styles.canvas}
            style={{ width: view.width, height: view.height }}
            role="img"
            aria-label="The picture of the screen, with your marks"
            data-tool={tool}
            onPointerDown={(event) => {
              if (event.button > 0) return;
              const point = at(event);
              if (tool === "text") {
                event.preventDefault();
                if (typed.current) place();
                else type({ at: point, text: "" });
                return;
              }
              event.currentTarget.setPointerCapture(event.pointerId);
              serial.current += 1;
              const width = lineWidth(size.width, size.height, tool);
              draft.current =
                tool === "crop"
                  ? { kind: "crop", from: point, to: point }
                  : tool === "pen" || tool === "highlight"
                    ? {
                        id: serial.current,
                        kind: tool,
                        color,
                        width,
                        points: [point],
                      }
                    : {
                        id: serial.current,
                        kind: tool,
                        color,
                        width,
                        from: point,
                        to: point,
                      };
              later();
            }}
            onPointerMove={(event) => {
              const now = draft.current;
              if (!now) return;
              const point = at(event);
              if ("points" in now) {
                const last = now.points[now.points.length - 1]!;
                if (Math.hypot(point.x - last.x, point.y - last.y) < 1.5)
                  return;
                draft.current = { ...now, points: [...now.points, point] };
              } else if ("to" in now) {
                draft.current = { ...now, to: point };
              }
              later();
            }}
            onPointerUp={() => {
              const now = draft.current;
              draft.current = null;
              if (!now) return;
              if (now.kind === "crop") {
                const crop = clampBox(
                  boxOf(now.from, now.to),
                  size.width,
                  size.height,
                );
                // A tap with the crop tool keeps the picture whole again.
                onCommit({ ...markup, crop });
              } else if (!tooSmall(now)) {
                onCommit({ ...markup, shapes: [...markup.shapes, now] });
              }
              later();
            }}
            onPointerCancel={() => {
              draft.current = null;
              later();
            }}
          />
          {typing && textScreen ? (
            <textarea
              // A label typed where it was tapped; Enter places it, Esc drops it.
              className={styles.typing}
              style={{
                left: textScreen.left,
                top: textScreen.top,
                fontSize: textScreen.fontSize,
                color,
              }}
              aria-label="Text on the picture"
              autoFocus
              rows={1}
              value={typing.text}
              onChange={(event) =>
                type({ ...typing, text: event.target.value })
              }
              onKeyDown={(event) => {
                event.stopPropagation();
                if (event.key === "Escape") {
                  event.preventDefault();
                  type(null);
                } else if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  place();
                }
              }}
              onBlur={place}
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
