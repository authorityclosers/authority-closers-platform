import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  challengeOf,
  finishConnect,
  newVerifier,
  readReturn,
  startConnect,
  UPDATE_APP,
} from "./app-connect";

type Listener = (event: { data: unknown }) => void;

/** The app's SXPhone object, answering status and openConnect like the phone. */
function fakePhone(status: Record<string, unknown>, opened = true) {
  const listeners: Listener[] = [];
  const sent: { method: string; args: Record<string, unknown> }[] = [];
  vi.stubGlobal("SXPhone", {
    addEventListener: (_: string, listener: Listener) =>
      listeners.push(listener),
    postMessage: (data: string) => {
      const message = JSON.parse(data) as {
        id: string;
        method: string;
        args: Record<string, unknown>;
      };
      sent.push({ method: message.method, args: message.args });
      const result = message.method === "status" ? status : { opened: opened };
      queueMicrotask(() =>
        listeners.forEach((listener) =>
          listener({
            data: JSON.stringify({ id: message.id, ok: true, result }),
          }),
        ),
      );
    },
  });
  return sent;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

let calls: { url: string; init?: RequestInit }[];

beforeEach(() => {
  calls = [];
  window.localStorage.clear();
  window.history.replaceState(null, "", "/leads?tab=sources");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Connect from the Sales X-Ray app", () => {
  it("answers the S256 challenge the server checks", async () => {
    // RFC 7636, appendix B.
    expect(
      await challengeOf("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
    ).toBe("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
    const verifier = newVerifier();
    expect(verifier).toMatch(/^[A-Za-z0-9_-]{64}$/);
    expect(newVerifier()).not.toBe(verifier);
  });

  it("reads only its own provider's return from the address", () => {
    const handoff = "A".repeat(40);
    expect(readReturn(`#connect=meta&handoff=${handoff}`, "meta")).toEqual({
      handoff,
    });
    expect(readReturn(`#connect=meta&handoff=${handoff}`, "google")).toBe(null);
    expect(readReturn("#connect=google&result=cancelled", "google")).toEqual({
      result: "cancelled",
    });
    expect(readReturn("#connect=google&result=<b>", "google")).toEqual({
      result: "failed",
    });
    expect(readReturn("", "meta")).toBe(null);
  });

  it("opens the sign-in in the phone's browser with a challenge it can answer", async () => {
    const sent = fakePhone({ platform: "android", connect: true });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(input), init });
        return json({ url: "https://www.facebook.com/v23.0/dialog/oauth?x=1" });
      }),
    );

    expect(await startConnect("meta")).toBe(null);

    const url = new URL(calls[0].url, "https://app.test");
    expect(url.pathname).toBe("/v1/lead-desk/meta/connect");
    expect(url.searchParams.get("format")).toBe("json");
    const kept = JSON.parse(window.localStorage.getItem("sx.appConnect")!) as {
      provider: string;
      verifier: string;
    };
    expect(kept.provider).toBe("meta");
    expect(url.searchParams.get("app_challenge")).toBe(
      await challengeOf(kept.verifier),
    );
    expect(sent.map((message) => message.method)).toEqual([
      "status",
      "openConnect",
    ]);
    expect(sent[1].args).toEqual({
      url: "https://www.facebook.com/v23.0/dialog/oauth?x=1",
    });
  });

  it("asks for an app update when the app can't open the browser", async () => {
    const sent = fakePhone({ platform: "android", calling: true });
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    expect(await startConnect("google")).toEqual({
      result: "update_app",
      message: UPDATE_APP,
    });
    expect(fetch).not.toHaveBeenCalled();
    expect(sent.map((message) => message.method)).toEqual(["status"]);
  });

  it("says so when the phone's browser doesn't open", async () => {
    fakePhone({ connect: true }, false);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ url: "https://accounts.google.com/o/oauth2" })),
    );
    expect(await startConnect("google")).toMatchObject({ result: "failed" });
  });

  it("finishes on this page's own session with the verifier it kept, once", async () => {
    window.localStorage.setItem(
      "sx.appConnect",
      JSON.stringify({
        provider: "whatsapp",
        verifier: "v".repeat(64),
        at: Date.now(),
      }),
    );
    const handoff = "H".repeat(60);
    window.history.replaceState(
      null,
      "",
      `/organisation?tab=integrations#connect=whatsapp&handoff=${handoff}`,
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(input), init });
        return json({ result: "connected" });
      }),
    );

    expect(await finishConnect("whatsapp")).toEqual({ result: "connected" });

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/v1/lead-desk/whatsapp/app-complete");
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      handoff,
      verifier: "v".repeat(64),
    });
    expect(window.location.hash).toBe("");
    expect(window.location.search).toBe("?tab=integrations");
    expect(window.localStorage.getItem("sx.appConnect")).toBe(null);
    // Nothing left to finish a second time.
    expect(await finishConnect("whatsapp")).toBe(null);
    expect(calls).toHaveLength(1);
  });

  it("shows the server's words when it refuses, and starts over after too long", async () => {
    window.localStorage.setItem(
      "sx.appConnect",
      JSON.stringify({
        provider: "meta",
        verifier: "v".repeat(64),
        at: Date.now(),
      }),
    );
    window.history.replaceState(
      null,
      "",
      `/leads#connect=meta&handoff=${"H".repeat(30)}`,
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json({ detail: "That didn't come from this app. Connect again." }, 403),
      ),
    );
    expect(await finishConnect("meta")).toEqual({
      result: "failed",
      message: "That didn't come from this app. Connect again.",
    });

    window.localStorage.setItem(
      "sx.appConnect",
      JSON.stringify({
        provider: "meta",
        verifier: "v".repeat(64),
        at: Date.now() - 11 * 60 * 1000,
      }),
    );
    window.history.replaceState(
      null,
      "",
      `/leads#connect=meta&handoff=${"H".repeat(30)}`,
    );
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    expect(await finishConnect("meta")).toEqual({
      result: "failed",
      message: "That took too long. Connect again.",
    });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("passes a cancelled sign-in straight through", async () => {
    window.history.replaceState(
      null,
      "",
      "/leads#connect=google&result=cancelled",
    );
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    expect(await finishConnect("google")).toEqual({ result: "cancelled" });
    expect(fetch).not.toHaveBeenCalled();
    expect(window.location.hash).toBe("");
  });
});
