import { afterEach, expect, it } from "vitest";

import { captureHeader, fromPhone, rememberCapture } from "./capture-source";

afterEach(() => sessionStorage.clear());

it("maps the phone's three ways to capture sources", () => {
  expect(fromPhone("dialer")).toBe("android_dialer_pickup");
  expect(fromPhone("in_app")).toBe("android_in_app_recorder");
  expect(fromPhone("accessibility")).toBe("android_call_recorder");
  expect(fromPhone("anything else")).toBeNull();
  expect(fromPhone(undefined)).toBeNull();
});

it("sends the header only for the file the phone noted", () => {
  const file = {
    name: "Sales Xray call recording 2026-10-19 10.00.00.m4a",
    size: 373087,
  };
  expect(captureHeader(file)).toEqual({});
  rememberCapture(file, "android_call_recorder");
  expect(captureHeader(file)).toEqual({
    "X-Capture-Source": "android_call_recorder",
  });
  expect(captureHeader({ ...file, size: 1 })).toEqual({});
  rememberCapture({ name: "x.m4a", size: 2 }, null);
  expect(captureHeader({ name: "x.m4a", size: 2 })).toEqual({});
});

it("ignores a note that isn't a known source", () => {
  sessionStorage.setItem("sx.capture:y.m4a:3", "file_name_guess");
  expect(captureHeader({ name: "y.m4a", size: 3 })).toEqual({});
});
