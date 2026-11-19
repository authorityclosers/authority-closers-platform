import { existsSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  CHARACTER_LOOP,
  CharacterLoop,
  CharacterStill,
  stillSrc,
  type CharacterStillName,
} from "./characters";

const PUBLIC = join(dirname(fileURLToPath(import.meta.url)), "../../public");
const STILLS: CharacterStillName[] = [
  "aman-neutral",
  "aman-worried",
  "aman-confident",
  "aman-aha",
  "aman-relieved",
  "rohit-neutral",
  "rohit-sceptical",
  "rohit-thinking",
  "rohit-worried",
  "rohit-annoyed",
  "rohit-grateful",
];

describe("Aman and Rohit (character kit v2)", () => {
  it("ships every still and both loops, each small", () => {
    for (const name of STILLS) {
      const file = join(PUBLIC, stillSrc(name));
      expect(existsSync(file), name).toBe(true);
      expect(statSync(file).size).toBeLessThan(20_000);
    }
    for (const { name } of Object.values(CHARACTER_LOOP))
      for (const type of ["webm", "mp4"]) {
        const file = join(PUBLIC, `media/ask-dipak/characters/${name}.${type}`);
        expect(existsSync(file), `${name}.${type}`).toBe(true);
        expect(statSync(file).size).toBeLessThan(60_000);
      }
  });

  it("keeps the colours by meaning: the hook is Rohit, the payoff Aman", () => {
    expect(CHARACTER_LOOP.hook.still.startsWith("rohit")).toBe(true);
    expect(CHARACTER_LOOP.payoff.still.startsWith("aman")).toBe(true);
  });

  it("a still is decorative unless it is named", () => {
    expect(
      renderToStaticMarkup(<CharacterStill name="rohit-sceptical" />),
    ).toContain('aria-hidden="true"');
    expect(
      renderToStaticMarkup(<CharacterStill name="aman-confident" labelled />),
    ).toContain('alt="Aman, the salesperson"');
  });

  it("a loop starts as its still (no video until it is near and motion is allowed)", () => {
    const html = renderToStaticMarkup(<CharacterLoop loop="hook" size={56} />);
    expect(html).toContain('aria-label="Rohit, the customer"');
    expect(html).toContain(stillSrc("rohit-sceptical"));
    expect(html).not.toContain("<video");
  });
});
