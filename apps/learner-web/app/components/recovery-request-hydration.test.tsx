// @vitest-environment happy-dom
import { act } from "react";
import { hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as apiModule from "../lib/learner-api";
import type { LearnerApi } from "../lib/learner-api";
import { RecoveryRequestForm } from "./password-auth-forms";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root | undefined;
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
});
afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  root = undefined;
  container.remove();
  vi.restoreAllMocks();
});

it("keeps pre-hydration recovery inert and account email out of native GET targets", () => {
  container.innerHTML = renderToString(<RecoveryRequestForm />);
  const form = container.querySelector("form")!;
  expect(form.method).toBe("post");
  const input = container.querySelector<HTMLInputElement>("#recovery-email")!;
  const button = container.querySelector("button")!;
  expect(input.disabled).toBe(true);
  expect(button.disabled).toBe(true);
  input.value = "synthetic-recovery@example.test";
  expect([...new FormData(form).entries()]).toEqual([]);
});

it("enables the hydrated command and refuses a duplicate while pending", async () => {
  let finish!: () => void;
  const requestPasswordRecovery = vi.fn(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
    requestPasswordRecovery,
  } as unknown as LearnerApi);
  container.innerHTML = renderToString(<RecoveryRequestForm />);
  await act(async () => {
    root = hydrateRoot(container, <RecoveryRequestForm />);
  });
  const form = container.querySelector("form")!;
  const input = container.querySelector<HTMLInputElement>("#recovery-email")!;
  expect(input.disabled).toBe(false);
  input.value = "synthetic-recovery@example.test";
  await act(async () =>
    form.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    ),
  );
  expect(container.querySelector("button")!.disabled).toBe(true);
  await act(async () =>
    form.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    ),
  );
  expect(requestPasswordRecovery).toHaveBeenCalledExactlyOnceWith(
    "synthetic-recovery@example.test",
  );
  await act(async () => finish());
  expect(container.textContent).toContain("Check your inbox.");
});
