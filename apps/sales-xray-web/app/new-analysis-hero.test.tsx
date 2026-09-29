// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { NewAnalysisFooter, NewAnalysisHero } from "./new-analysis-hero";
import { updateShellState } from "./shell/shell-store";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  updateShellState({ profileName: null });
});

it("welcomes the person by first name", async () => {
  updateShellState({ profileName: "Suyash Rahegaonkar" });
  await act(async () => root.render(<NewAnalysisHero />));
  expect(host.querySelector("h2")?.textContent).toBe(
    "Let's analyse your next call, Suyash🎧",
  );
});

it("leaves the name out when the profile has none", async () => {
  await act(async () => root.render(<NewAnalysisHero />));
  expect(host.querySelector("h2")?.textContent).toBe(
    "Let's analyse your next call🎧",
  );
});

it("shows the allowance and the three steps under the card", async () => {
  await act(async () =>
    root.render(<NewAnalysisFooter allowanceLabel="Unlimited analysis time" />),
  );
  expect(host.textContent).toContain("Unlimited analysis time");
  expect(
    [...host.querySelectorAll("li")].map((step) => step.textContent),
  ).toEqual(["1Upload", "2We analyse", "3Your report"]);
});
