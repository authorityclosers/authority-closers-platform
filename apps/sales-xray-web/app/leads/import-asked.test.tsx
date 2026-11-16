// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { importAsk, useImportAsked, type ImportAsk } from "./import-asked";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

function Probe({
  query,
  onAsk,
}: {
  query: string;
  onAsk: (ask: ImportAsk) => void;
}) {
  useImportAsked(new URLSearchParams(query), onAsk);
  return null;
}

it("reads only the two import asks", () => {
  expect(importAsk(new URLSearchParams("import=file"))).toBe("file");
  expect(importAsk(new URLSearchParams("import=google"))).toBe("google");
  expect(importAsk(new URLSearchParams("import=other"))).toBeNull();
  expect(importAsk(new URLSearchParams(""))).toBeNull();
  expect(importAsk(null)).toBeNull();
});

// Owner, 16 Nov 2026, on a laptop: on Leads, + → Import leads changed the
// address to ?import=file and opened nothing.
it("opens Import when the ask arrives on an open Leads, each time it comes", () => {
  const onAsk = vi.fn();
  act(() => root.render(<Probe query="tab=all" onAsk={onAsk} />));
  expect(onAsk).not.toHaveBeenCalled();
  act(() => root.render(<Probe query="tab=all&import=file" onAsk={onAsk} />));
  expect(onAsk).toHaveBeenCalledTimes(1);
  expect(onAsk).toHaveBeenLastCalledWith("file");
  // The same address drawn again is not a new ask.
  act(() => root.render(<Probe query="import=file&tab=all" onAsk={onAsk} />));
  expect(onAsk).toHaveBeenCalledTimes(1);
  // Closing Import clears the ask; asking again opens it again.
  act(() => root.render(<Probe query="tab=all" onAsk={onAsk} />));
  act(() => root.render(<Probe query="tab=all&import=file" onAsk={onAsk} />));
  expect(onAsk).toHaveBeenCalledTimes(2);
  act(() => root.render(<Probe query="import=google" onAsk={onAsk} />));
  expect(onAsk).toHaveBeenLastCalledWith("google");
});

it("leaves the ask Leads opened with to the page's own first state", () => {
  const onAsk = vi.fn();
  act(() => root.render(<Probe query="import=file" onAsk={onAsk} />));
  expect(onAsk).not.toHaveBeenCalled();
});

// A dialog's history entry shares the page's address; closing it goes back to
// the page's entry. Had that kept ?import=file, the next Import leads would go
// to the address already shown and open nothing.
it("takes the ask off the address at once, keeping the rest and the router's state", () => {
  window.history.replaceState(
    { router: "kept" },
    "",
    "/leads?tab=all&import=file#top",
  );
  const onAsk = vi.fn();
  act(() => root.render(<Probe query="tab=all" onAsk={onAsk} />));
  act(() => root.render(<Probe query="tab=all&import=file" onAsk={onAsk} />));
  expect(onAsk).toHaveBeenCalledTimes(1);
  expect(window.location.pathname).toBe("/leads");
  expect(window.location.search).toBe("?tab=all");
  expect(window.location.hash).toBe("#top");
  expect(window.history.state).toEqual({ router: "kept" });
});

it("drops the ask Leads opened with from the address too", () => {
  window.history.replaceState(null, "", "/leads?import=google");
  act(() => root.render(<Probe query="import=google" onAsk={vi.fn()} />));
  expect(window.location.search).toBe("");
});
