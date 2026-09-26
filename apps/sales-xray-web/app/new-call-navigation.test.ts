import { afterEach, expect, it } from "vitest";
import {
  isNewCallRequested,
  newCallHref,
  setNewCallRequested,
} from "./new-call-navigation";

afterEach(() => window.history.replaceState(null, "", "/"));

it("builds an explicit new-call URL for standalone and embedded navigation", () => {
  expect(newCallHref()).toBe("/?new=1");
  expect(newCallHref("/sales-xray?call=old&view=compact#upload")).toBe(
    "/sales-xray?view=compact&new=1#upload",
  );
});

it("preserves history state and unrelated parameters without touching saved selectors", () => {
  localStorage.setItem("ac.xray.submission.v1", "saved-selector");
  window.history.replaceState(
    { router: "preserved" },
    "",
    "/?call=old&view=compact",
  );
  setNewCallRequested(true);
  expect(isNewCallRequested()).toBe(true);
  expect(window.location.search).toBe("?view=compact&new=1");
  setNewCallRequested(false);
  expect(isNewCallRequested()).toBe(false);
  expect(window.location.search).toBe("?view=compact");
  expect(window.history.state).toEqual({ router: "preserved" });
  expect(localStorage.getItem("ac.xray.submission.v1")).toBe("saved-selector");
  localStorage.removeItem("ac.xray.submission.v1");
});
