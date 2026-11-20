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
  it("ships every still, each small, and no idle loop (not approved, 19 Nov 2026)", () => {
    for (const name of STILLS) {
      const file = join(PUBLIC, stillSrc(name));
      expect(existsSync(file), name).toBe(true);
      expect(statSync(file).size).toBeLessThan(20_000);
    }
    for (const loop of ["rohit-sceptical-loop", "aman-confident-loop"])
      for (const type of ["webm", "mp4"])
        expect(
          existsSync(
            join(PUBLIC, `media/ask-dipak/characters/${loop}.${type}`),
          ),
          `${loop}.${type}`,
        ).toBe(false);
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

  it("the hook and the payoff show their still pose only: no video, no loop file", () => {
    const hook = renderToStaticMarkup(<CharacterLoop loop="hook" size={56} />);
    expect(hook).toContain('aria-label="Rohit, the customer"');
    expect(hook).toContain(stillSrc("rohit-sceptical"));
    const payoff = renderToStaticMarkup(
      <CharacterLoop loop="payoff" size={64} />,
    );
    expect(payoff).toContain('aria-label="Aman, the salesperson"');
    expect(payoff).toContain(stillSrc("aman-confident"));
    for (const html of [hook, payoff]) {
      expect(html).not.toContain("<video");
      expect(html).not.toMatch(/\.(webm|mp4)/);
    }
  });
});
