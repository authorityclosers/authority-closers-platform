import { afterEach, expect, it } from "vitest";
import {
  isNewCallRequested,
  linksToThisNewCall,
  newCallHref,
  setNewCallRequested,
} from "./new-call-navigation";

afterEach(() => window.history.replaceState(null, "", "/"));

it("builds an explicit new-call URL for standalone and embedded navigation", () => {
  expect(newCallHref()).toBe("/analysis/new");
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

it("knows a link to this page's own new-call address, with or without the app's trailing slash (U3)", () => {
  window.history.replaceState(null, "", "/analysis/new");
  expect(linksToThisNewCall("/analysis/new")).toBe(true);
  expect(linksToThisNewCall("/analysis/new/")).toBe(true);
  expect(linksToThisNewCall("/leads")).toBe(false);
  expect(linksToThisNewCall("/analysis/new?call=old")).toBe(false);
  window.history.replaceState(null, "", "/analysis/new/");
  expect(linksToThisNewCall("/analysis/new")).toBe(true);
  window.history.replaceState(null, "", "/sales-xray?view=compact&new=1");
  expect(linksToThisNewCall("/sales-xray?view=compact&new=1")).toBe(true);
  expect(linksToThisNewCall("/sales-xray?view=compact")).toBe(false);
  // A saved call's own page is not a new call, even linked to itself.
  window.history.replaceState(null, "", "/analysis/calls/old");
  expect(linksToThisNewCall("/analysis/calls/old")).toBe(false);
  // A new analysis takes its call's address: New analysis from there is a
  // new call only while that call is the one shown.
  const shown = "11111111-1111-4111-8111-111111111111";
  window.history.replaceState(null, "", `/analysis/calls/${shown}`);
  expect(linksToThisNewCall("/analysis/new", shown)).toBe(true);
  expect(linksToThisNewCall("/analysis/new")).toBe(false);
  expect(
    linksToThisNewCall("/analysis/new", "22222222-2222-4222-8222-222222222222"),
  ).toBe(false);
  expect(linksToThisNewCall("/leads", shown)).toBe(false);
});
