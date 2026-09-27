// @vitest-environment happy-dom
import { act } from "react";
import { hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { expect, it, vi } from "vitest";
import { AccountAuth } from "./account-auth";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

it("enables password navigation only after hydration, even while configuration is pending", async () => {
  const host = document.createElement("div");
  const fetcher = vi.fn(() => new Promise<Response>(() => {}));
  vi.stubGlobal("fetch", fetcher);
  const onAuthenticated = vi.fn();
  const component = <AccountAuth onAuthenticated={onAuthenticated} />;
  host.innerHTML = renderToString(component);
  document.body.append(host);
  const passwordChoice = () =>
    [...host.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Use my existing password"),
    )!;
  let root: Root | undefined;
  try {
    expect(passwordChoice().disabled).toBe(true);
    passwordChoice().click();
    expect(fetcher).not.toHaveBeenCalled();
    await act(async () => {
      root = hydrateRoot(host, component);
    });
    expect(passwordChoice().disabled).toBe(false);
    await act(async () => passwordChoice().click());
    expect(host.querySelector("#account-auth-heading")?.textContent).toBe(
      "Welcome back.",
    );
    expect(host.querySelector("#account-password")).not.toBeNull();
    expect(onAuthenticated).not.toHaveBeenCalled();
    expect(fetcher).toHaveBeenCalledTimes(1);
  } finally {
    await act(async () => root?.unmount());
    host.remove();
    vi.unstubAllGlobals();
  }
});
