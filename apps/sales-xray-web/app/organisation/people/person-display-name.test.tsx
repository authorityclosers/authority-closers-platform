// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import { PersonDisplayName } from "./person-display-name";
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
it("keeps a capitalised full name accessible while fitting the available line", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () =>
    root.render(<PersonDisplayName name="alexandria fictional sampleworth" />),
  );
  expect(
    host.querySelector('[aria-label="Alexandria Fictional Sampleworth"]'),
  ).not.toBeNull();
  expect(
    host.querySelector('[title="Alexandria Fictional Sampleworth"]'),
  ).not.toBeNull();
  await act(async () => root.unmount());
  host.remove();
});
