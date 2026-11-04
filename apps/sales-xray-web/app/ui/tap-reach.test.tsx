// @vitest-environment happy-dom
import { needsReach, tagTapReach } from "@ac/ui/kit/tap-reach";
import { afterEach, expect, it } from "vitest";

const sized = (id: string, width: number, height: number) => {
  const el = document.getElementById(id);
  if (!el) throw new Error(`no #${id}`);
  el.getBoundingClientRect = () =>
    ({
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      width,
      height,
      right: width,
      bottom: height,
    }) as DOMRect;
};

afterEach(() => document.body.replaceChildren());

// The QA robot's tap-target rows (3 Nov 2026): a control drawn under 48 px gets
// the reach; anything that would move or draw differently is left alone.
it("gives the 48 px reach only to small controls that can take it", () => {
  document.body.innerHTML = `
    <button id="small">Today</button>
    <button id="big">Call</button>
    <button id="placed" style="position: absolute">Close</button>
    <button id="parts">Bell<span style="position: absolute">2</span></button>
    <p><a id="inline" href="/read">read more</a></p>
    <a id="block" href="/open" style="display: inline-flex">Open</a>
    <button id="hidden">Later</button>`;
  sized("small", 68, 32);
  sized("big", 120, 48);
  sized("placed", 28, 28);
  sized("parts", 40, 40);
  sized("inline", 60, 18);
  sized("block", 70, 36);
  sized("hidden", 0, 0);
  expect(tagTapReach(document.body)).toBe(2);
  expect(
    [...document.querySelectorAll("[data-reach]")].map((el) => el.id),
  ).toEqual(["small", "block"]);
});

it("measures a control once, when it first shows", () => {
  document.body.innerHTML = `<button id="later">Later</button>`;
  sized("later", 0, 0);
  const seen = new WeakSet<Element>();
  expect(tagTapReach(document.body, seen)).toBe(0);
  sized("later", 80, 32);
  expect(tagTapReach(document.body, seen)).toBe(1);
  expect(tagTapReach(document.body, seen)).toBe(0);
  const later = document.getElementById("later");
  expect(later && needsReach(later)).toBe(true);
});
