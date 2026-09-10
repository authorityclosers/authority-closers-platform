// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { URL as NodeURL } from "node:url";
import { renderToStaticMarkup } from "react-dom/server";
import {
  ActionButton,
  ChoiceOption,
  FocusSession,
  SessionStep,
  LearningSymbol,
  ProgressOrbit,
} from "@ac/ui";
import { expect, it } from "vitest";

it("shares safe native actions and stable radio slots", () => {
  const root = document.createElement("div");
  root.innerHTML = renderToStaticMarkup(<ActionButton>Continue</ActionButton>);
  expect(root.querySelector("button")?.type).toBe("button");
  root.innerHTML = renderToStaticMarkup(
    <fieldset>
      <legend>Choose a response</legend>
      <ChoiceOption
        label="Ask a question"
        marker="A"
        name="answer"
        checked={false}
        readOnly
      />
      <ChoiceOption label="Listen" marker="B" name="answer" checked readOnly />
    </fieldset>,
  );
  const labels = root.querySelectorAll("label");
  expect(labels[0].children.length).toBe(labels[1].children.length);
  expect(labels[0].querySelector("input")?.type).toBe("radio");
  expect(labels[0].querySelectorAll("span")[1].textContent).toBe(
    "Ask a question",
  );
  expect(labels[1].querySelector("input")?.checked).toBe(true);
});

it("owns focused task chrome separately from its scroll body and persistent action", () => {
  const root = document.createElement("div");
  root.innerHTML = renderToStaticMarkup(
    <FocusSession
      header={
        <ActionButton variant="icon" aria-label="Exit">
          ×
        </ActionButton>
      }
    >
      <SessionStep
        labelledBy="question"
        footer={<ActionButton>Check</ActionButton>}
      >
        <h1 id="question">What would you ask?</h1>
      </SessionStep>
    </FocusSession>,
  );
  expect(root.querySelectorAll("main").length).toBe(1);
  expect(root.querySelector("nav")).toBeNull();
  expect(
    root
      .querySelector('[data-session-scroll="body"]')
      ?.contains(root.querySelector("footer")!),
  ).toBe(false);
  expect(root.querySelector("footer button")?.textContent).toBe("Check");
});

it("uses existing global semantic tokens rather than an Arcade palette", () => {
  const base = readFileSync(
    new NodeURL("../styles.css", import.meta.url),
    "utf8",
  );
  expect(base.match(/(?:^|\n)body\s*\{([^}]+)\}/)?.[1]).toMatch(
    /min-width:\s*0;/,
  );
  const theme = readFileSync(
    new NodeURL("../theme.css", import.meta.url),
    "utf8",
  );
  const paths = [
    "../../../../packages/typescript/ui/src/interaction-primitives.module.css",
    "../../../../packages/typescript/ui/src/learning-symbol.module.css",
    "./learning-journey.module.css",
    "./practice-arcade.module.css",
    "./practice-engine.module.css",
    "./avatar-crop-dialog.module.css",
  ];
  for (const path of paths) {
    const css = readFileSync(new NodeURL(path, import.meta.url), "utf8");
    for (const [, token] of css.matchAll(/var\((--theme-[\w-]+)/g)) {
      expect(theme, token).toContain(token + ":");
    }
    expect(css).not.toContain("--theme-primary");
    expect(css).not.toContain("--theme-on-primary");
  }
  const arcade = readFileSync(
    new NodeURL("./practice-arcade.module.css", import.meta.url),
    "utf8",
  );
  expect(arcade).not.toContain("--font-serif");
  expect(arcade).not.toMatch(/#[0-9a-f]{3,8}\b/i);
});

it("draws original bounded symbols without external assets or invented status", () => {
  const root = document.createElement("div");
  root.innerHTML = renderToStaticMarkup(
    <>
      <LearningSymbol kind="watch" />
      <LearningSymbol kind="review" label="Review your work" />
      <LearningSymbol kind="reflect" muted />
      <LearningSymbol kind="credits" />
      <LearningSymbol kind="experience" />
      <LearningSymbol kind="rhythm" />
    </>,
  );
  expect(root.querySelectorAll("svg")).toHaveLength(6);
  expect(root.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  expect(root.querySelector('[role="img"]')?.getAttribute("aria-label")).toBe(
    "Review your work",
  );
  expect(
    root.querySelectorAll("image, use, script, foreignObject"),
  ).toHaveLength(0);
  expect(root.textContent).not.toMatch(/credits|XP|completed/);
});

it("paints the exact projected percentage and treats nonfinite progress as unknown", () => {
  const root = document.createElement("div");
  for (const [value, expected] of [
    [0, 0],
    [17, 17],
    [100, 100],
    [-1, 0],
    [120, 100],
  ]) {
    root.innerHTML = renderToStaticMarkup(
      <ProgressOrbit value={value} label="Course completion" />,
    );
    expect(
      root.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow"),
    ).toBe(String(expected));
    expect(
      root
        .querySelector('[pathLength="100"]')
        ?.getAttribute("stroke-dasharray"),
    ).toBe(`${expected} 100`);
  }
  root.innerHTML = renderToStaticMarkup(
    <ProgressOrbit value={NaN} label="Course completion" />,
  );
  expect(
    root.querySelector('[role="progressbar"]')?.hasAttribute("aria-valuenow"),
  ).toBe(false);
  expect(
    root.querySelector('[role="progressbar"]')?.getAttribute("aria-valuetext"),
  ).toBe("Progress unavailable");
});
