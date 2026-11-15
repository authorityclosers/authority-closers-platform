/** Whose a task is, on a row that isn't the viewer's own (owner bugs 218-219). */
import { expect, it } from "vitest";

import { forWhom } from "./tasks-view";

it("says whose a task is only when it isn't the viewer's", () => {
  const task = { owner_person_id: "p2", owner_name: "Priya Deshmukh" };
  expect(forWhom(task, "p1")).toBe("for Priya");
  expect(forWhom(task, "p2")).toBe("");
  expect(forWhom({ ...task, owner_name: null }, "p1")).toBe("");
  expect(forWhom({ owner_person_id: null }, "p1")).toBe("");
  expect(forWhom(task, null)).toBe("");
});
