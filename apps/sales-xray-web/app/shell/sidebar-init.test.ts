// @vitest-environment happy-dom
import { afterEach, expect, it } from "vitest";

import {
  markSidebar,
  SIDEBAR_ATTRIBUTE,
  sidebarInitScript,
} from "./shell-store";

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute(SIDEBAR_ATTRIBUTE);
});

it("draws a collapsed sidebar from the first frame when the person collapsed it", () => {
  localStorage.setItem("sx.sidebar.collapsed", "true");
  new Function(sidebarInitScript())();
  expect(document.documentElement.getAttribute(SIDEBAR_ATTRIBUTE)).toBe(
    "collapsed",
  );
});

it("leaves an open sidebar open, and follows the person's later choice", () => {
  localStorage.setItem("sx.sidebar.collapsed", "false");
  new Function(sidebarInitScript())();
  expect(document.documentElement.hasAttribute(SIDEBAR_ATTRIBUTE)).toBe(false);
  markSidebar(true);
  expect(document.documentElement.getAttribute(SIDEBAR_ATTRIBUTE)).toBe(
    "collapsed",
  );
  markSidebar(false);
  expect(document.documentElement.hasAttribute(SIDEBAR_ATTRIBUTE)).toBe(false);
});
