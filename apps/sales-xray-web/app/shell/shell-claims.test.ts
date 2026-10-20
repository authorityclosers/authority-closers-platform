import { expect, it } from "vitest";

import {
  claimShell,
  releaseShell,
  shownClaim,
  type ShellClaims,
} from "./shell-claims";

type Page = { active: string; mobileFit?: boolean };

const leads = { page: { active: "leads" }, standIn: false };
const chatsOutline = {
  page: { active: "leads", mobileFit: true },
  standIn: true,
};

it("gives a page its chrome back when the outline standing in over it goes", () => {
  // Leads is on screen; a press on Chats puts Chats' outline up.
  let claims: ShellClaims<Page> = claimShell([], "leads", leads);
  claims = claimShell(claims, "outline", chatsOutline);
  expect(shownClaim(claims)?.page.mobileFit).toBe(true);
  // The press became a scroll: the outline goes and Leads scrolls again.
  claims = releaseShell(claims, "outline");
  expect(shownClaim(claims)).toEqual(leads);
});

it("keeps the stand-in on top while the page under it changes its settings", () => {
  let claims: ShellClaims<Page> = claimShell([], "leads", leads);
  claims = claimShell(claims, "outline", chatsOutline);
  claims = claimShell(claims, "leads", {
    page: { active: "leads", mobileFit: false },
    standIn: false,
  });
  expect(shownClaim(claims)).toEqual(chatsOutline);
});

it("shows the newest page, and a page that updates keeps its place", () => {
  const home = { page: { active: "home" }, standIn: false };
  let claims: ShellClaims<Page> = claimShell([], "home", home);
  claims = claimShell(claims, "leads", leads);
  claims = claimShell(claims, "home", {
    page: { active: "home", mobileFit: true },
    standIn: false,
  });
  expect(shownClaim(claims)).toEqual(leads);
  expect(claims.map(([id]) => id)).toEqual(["home", "leads"]);
});

it("keeps the last page shown after it leaves, until the next page arrives", () => {
  const calls = { page: { active: "calls" }, standIn: false };
  let claims: ShellClaims<Page> = claimShell([], "leads", leads);
  claims = releaseShell(claims, "leads");
  expect(shownClaim(claims)).toEqual(leads);
  claims = claimShell(claims, "calls", calls);
  expect(shownClaim(claims)).toEqual(calls);
  expect(claims).toHaveLength(1);
});

it("lets a stand-in that leaves on its own show nothing stale", () => {
  let claims: ShellClaims<Page> = claimShell([], "outline", chatsOutline);
  claims = releaseShell(claims, "outline");
  expect(shownClaim(claims)).toBeNull();
  expect(releaseShell(claims, "missing")).toEqual([]);
});
