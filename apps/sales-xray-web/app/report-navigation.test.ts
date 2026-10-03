import { expect, it } from "vitest";
import {
  reportSectionAddress,
  reportSectionFromSearch,
} from "./report-navigation";

const call = "c2793fdf-4948-47e4-a4bc-973f2b7720bc";
const other = "7b6443d3-9b2d-4f97-9e70-5e82e54f8738";

it("selects only a supported section of the bound call", () => {
  expect(reportSectionFromSearch(`?call=${call}&section=analysis`, call)).toBe(
    "analysis",
  );
  for (const search of [
    `?call=${other}&section=analysis`,
    `?call=${call}&call=${call}&section=analysis`,
    `?call=${call}&section=analysis&section=coaching`,
    `?call=${call}&section=processing`,
    `?call=${call}&stage=C5&approved=true`,
    "?section=analysis",
  ])
    expect(reportSectionFromSearch(search, call)).toBe("overview");
});

it("creates a bookmark for a validated new report without changing the route", () => {
  expect(
    reportSectionAddress(
      new URL("http://salesxray.localhost:3016/?new=1"),
      call,
      "moments",
    ),
  ).toBe(`/?call=${call}&section=moments`);
  expect(
    reportSectionAddress(
      new URL(
        `https://learner.authorityclosers.com/sales-xray?call=${call}&section=overview#report`,
      ),
      call,
      "analysis",
    ),
  ).toBe(`/sales-xray?call=${call}&section=analysis#report`);
});

it("refuses stale call navigation and invalid section identities", () => {
  expect(
    reportSectionAddress(
      new URL(`https://example.com/?call=${other}`),
      call,
      "analysis",
    ),
  ).toBeNull();
  expect(
    reportSectionAddress(
      new URL(`https://example.com/?call=${call}&call=${call}`),
      call,
      "analysis",
    ),
  ).toBeNull();
  expect(
    reportSectionAddress(new URL("https://example.com/"), "bad", "skills"),
  ).toBeNull();
  expect(
    reportSectionAddress(
      new URL("https://example.com/"),
      call,
      "https://example.com",
    ),
  ).toBeNull();
});
