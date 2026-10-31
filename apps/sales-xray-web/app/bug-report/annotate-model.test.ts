import { expect, it } from "vitest";

import {
  EMPTY,
  boxOf,
  clampBox,
  commit,
  edited,
  haloFor,
  lineWidth,
  redo,
  startHistory,
  tooSmall,
  undo,
  type Shape,
} from "./annotate-model";

const arrow = (id: number, to = { x: 50, y: 50 }): Shape => ({
  id,
  kind: "arrow",
  color: "red",
  width: 4,
  from: { x: 0, y: 0 },
  to,
});

const ids = (shapes: readonly Shape[]) => shapes.map((shape) => shape.id);

it("undoes and redoes every mark, and a new mark drops what was undone", () => {
  let history = startHistory();
  expect(edited(history)).toBe(false);
  history = commit(history, { ...history.now, shapes: [arrow(1)] });
  history = commit(history, {
    ...history.now,
    shapes: [...history.now.shapes, arrow(2)],
  });
  expect(ids(history.now.shapes)).toEqual([1, 2]);
  history = undo(history);
  expect(ids(history.now.shapes)).toEqual([1]);
  history = redo(history);
  expect(ids(history.now.shapes)).toEqual([1, 2]);
  history = undo(undo(history));
  expect(edited(history)).toBe(false);
  expect(undo(history)).toBe(history);
  history = commit(history, {
    ...history.now,
    crop: { x: 0, y: 0, w: 10, h: 10 },
  });
  expect(history.future).toEqual([]);
  expect(redo(history)).toBe(history);
  expect(edited(history)).toBe(true);
});

it("keeps the last sixty steps", () => {
  let history = startHistory();
  for (let n = 1; n <= 70; n += 1) {
    history = commit(history, { ...EMPTY, shapes: [arrow(n)] });
  }
  expect(history.past).toHaveLength(60);
  expect(ids(history.now.shapes)).toEqual([70]);
});

it("makes boxes either way round, keeps crops inside, and tells a tap from a mark", () => {
  expect(boxOf({ x: 30, y: 40 }, { x: 10, y: 0 })).toEqual({
    x: 10,
    y: 0,
    w: 20,
    h: 40,
  });
  expect(clampBox({ x: -5, y: 10, w: 50, h: 500 }, 40, 100)).toEqual({
    x: 0,
    y: 10,
    w: 40,
    h: 90,
  });
  expect(clampBox({ x: 1, y: 1, w: 4, h: 40 }, 100, 100)).toBeNull();
  expect(tooSmall(arrow(1, { x: 3, y: 2 }))).toBe(true);
  expect(tooSmall(arrow(1))).toBe(false);
  expect(
    tooSmall({
      id: 1,
      kind: "text",
      color: "red",
      size: 16,
      at: { x: 0, y: 0 },
      text: "  ",
    }),
  ).toBe(true);
  expect(
    tooSmall({
      id: 1,
      kind: "pen",
      color: "red",
      width: 4,
      points: [{ x: 0, y: 0 }],
    }),
  ).toBe(true);
});

it("sizes lines to the picture and gives light text a dark halo", () => {
  expect(lineWidth(1600, 900, "pen")).toBe(6);
  expect(lineWidth(1600, 900, "highlight")).toBe(30);
  expect(lineWidth(300, 200, "arrow")).toBe(3);
  expect(haloFor("rgb(255, 255, 255)")).toBe("black");
  expect(haloFor("rgb(198, 40, 40)")).toBe("white");
  expect(haloFor("white")).toBe("black");
  expect(haloFor("black")).toBe("white");
});
