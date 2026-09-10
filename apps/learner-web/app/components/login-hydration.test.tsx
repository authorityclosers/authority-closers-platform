// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { LoginForm } from "./login-form";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
it("server HTML cannot serialize credentials in a native GET before hydration", () => {
  const dom = document.createElement("div");
  dom.innerHTML = renderToStaticMarkup(<LoginForm />);
  expect(dom.querySelector("form")?.method).toBe("post");
  for (const element of dom.querySelectorAll<
    HTMLInputElement | HTMLButtonElement
  >("input, button"))
    expect(element.disabled).toBe(true);
});
it("the real hydrated component enables login while retaining POST defense", async () => {
  const dom = document.createElement("div");
  document.body.append(dom);
  const root = createRoot(dom);
  try {
    await act(async () => root.render(<LoginForm />));
    expect(dom.querySelector("form")?.method).toBe("post");
    for (const element of dom.querySelectorAll<
      HTMLInputElement | HTMLButtonElement
    >("input, button"))
      expect(element.disabled).toBe(false);
  } finally {
    await act(async () => root.unmount());
    dom.remove();
  }
});
