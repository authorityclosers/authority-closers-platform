import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { NativeCall } from "../leads/native-phone";
import { answeredCallFor, rememberDial } from "../leads/pending-answer";
import { AfterCallGuard, showingLead } from "./after-call-guard";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const phone = vi.hoisted(() => ({
  inApp: true,
  listeners: [] as ((call: NativeCall) => void)[],
  handed: [] as string[],
  last: null as NativeCall | null,
}));

vi.mock("../leads/native-phone", () => ({
  inPhoneApp: () => phone.inApp,
  onPhoneCall: (listener: (call: NativeCall) => void) => {
    phone.listeners.push(listener);
    return () => {
      phone.listeners = phone.listeners.filter((item) => item !== listener);
    };
  },
  onPhoneSignal: () => () => undefined,
  readLastCall: async (leadId: string) =>
    phone.last?.leadId === leadId ? phone.last : null,
}));
vi.mock("../leads/lead-handoff", () => ({
  handOverAnswer: (leadId: string) => phone.handed.push(leadId),
}));
vi.mock("../workspace-access", () => ({
  useWorkspaceAccess: () => ({
    context: { personId: "person-1", tenantId: "tenant-1" },
  }),
}));

const ACCOUNT = "tenant-1:person-1";
let root: Root;
let host: HTMLDivElement;
const opened: string[] = [];

const ended = (leadId: string, connected: boolean | null): NativeCall => ({
  leadId,
  number: "+919876543210",
  startedMs: Date.now() - 60_000,
  endedMs: Date.now() - 5_000,
  durationSeconds: null,
  connected,
  result: connected === false ? "no_answer" : "answered",
  recording: null,
  final: true,
});

const hear = (call: NativeCall) =>
  act(() => phone.listeners.forEach((listen) => listen(call)));

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
  vi.setSystemTime(Date.parse("2026-11-19T12:00:00Z"));
  phone.inApp = true;
  phone.listeners = [];
  phone.handed = [];
  phone.last = null;
  opened.length = 0;
  localStorage.clear();
  window.history.replaceState(null, "", "/home");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

const mount = () =>
  act(() =>
    root.render(<AfterCallGuard openLead={(href) => opened.push(href)} />),
  );

it("brings the seller back to the lead's question after a call, until it is answered", () => {
  mount();
  hear(ended("lead-1", null));
  expect(phone.handed).toEqual(["lead-1"]);
  expect(opened).toEqual(["/leads?lead=lead-1"]);

  // On the lead: nothing more. Navigating away: back again.
  window.history.replaceState(null, "", "/leads?lead=lead-1");
  act(() => vi.advanceTimersByTime(4_000));
  expect(opened).toHaveLength(1);
  window.history.replaceState(null, "", "/calls");
  act(() => vi.advanceTimersByTime(2_000));
  expect(opened).toEqual(["/leads?lead=lead-1", "/leads?lead=lead-1"]);

  // Saved: the seller goes where they like.
  act(() => answeredCallFor(ACCOUNT, "lead-1"));
  window.history.replaceState(null, "", "/home");
  act(() => vi.advanceTimersByTime(6_000));
  expect(opened).toHaveLength(2);
});

it("holds nobody after a call the phone knows didn't connect", () => {
  mount();
  hear(ended("lead-1", false));
  act(() => vi.advanceTimersByTime(4_000));
  expect(opened).toEqual([]);
});

it("does nothing in a browser", () => {
  phone.inApp = false;
  mount();
  expect(phone.listeners).toHaveLength(0);
});

it("still holds after the app is closed and opened again", () => {
  mount();
  hear(ended("lead-2", true));
  act(() => root.unmount());
  opened.length = 0;
  root = createRoot(host);
  window.history.replaceState(null, "", "/home");
  mount();
  expect(opened).toEqual(["/leads?lead=lead-2"]);
});

it("knows when the lead is the one open", () => {
  const at = (href: string) =>
    new URL(href, "https://x.test") as unknown as Location;
  expect(showingLead(at("/leads?lead=a"), "a")).toBe(true);
  expect(showingLead(at("/leads/?lead=a&view=all"), "a")).toBe(true);
  expect(showingLead(at("/leads?lead=b"), "a")).toBe(false);
  expect(showingLead(at("/home?lead=a"), "a")).toBe(false);
});

it("holds a call whose end the page never heard, read from the phone on return", async () => {
  // Android closed the page during a long call: no "call ended" event came.
  rememberDial("lead-3");
  phone.last = ended("lead-3", null);
  await act(async () => {
    root.render(<AfterCallGuard openLead={(href) => opened.push(href)} />);
    await Promise.resolve();
  });
  expect(opened).toEqual(["/leads?lead=lead-3"]);
});
