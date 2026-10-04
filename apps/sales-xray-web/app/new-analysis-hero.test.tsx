// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { NewAnalysisFooter, NewAnalysisHero } from "./new-analysis-hero";
import {
  invalidateShellProfile,
  readShellProfile,
} from "./shell/profile-store";

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
  invalidateShellProfile();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

it("welcomes the person by first name", async () => {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      Response.json({
        name: "Suyash Rahegaonkar",
        email: "person@example.test",
        phone_number_e164: null,
        phone_verified: false,
        profile_complete: false,
        revision: 0,
      }),
    ),
  );
  await readShellProfile("document");
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
    root.render(
      <NewAnalysisFooter allowanceLabel="Remaining analysis time · 166 h" />,
    ),
  );
  expect(host.textContent).toContain("Remaining analysis time · 166 h");
  expect(
    [...host.querySelectorAll("li")].map((step) => step.textContent),
  ).toEqual(["1Upload", "2We analyse", "3Your report"]);
});
