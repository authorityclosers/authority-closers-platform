import { EventEmitter } from "node:events";
import { Readable } from "node:stream";

import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchLocalLearnerWire } from "./local-api-upstream";

const httpRequest = vi.hoisted(() => vi.fn());

vi.mock("node:http", () => ({ request: httpRequest }));

describe("local learner API native wire", () => {
  beforeEach(() => {
    httpRequest.mockReset();
  });

  it("uses the trusted learner Host, preserves cookies, and returns redirects without following them", async () => {
    const request = Object.assign(new EventEmitter(), { end: vi.fn() });
    httpRequest.mockImplementation(
      (
        _input: URL,
        options: { headers?: Record<string, string> },
        callback: (response: Readable) => void,
      ) => {
        expect(options.headers).toEqual({
          "accept-encoding": "identity",
          "content-type": "application/json",
          cookie: "ac_session=fixture",
          host: "learner.localhost:8000",
        });
        const response = Object.assign(
          Readable.from([Buffer.from("fixture")]),
          {
            statusCode: 302,
            rawHeaders: [
              "content-type",
              "application/json",
              "content-length",
              "7",
              "connection",
              "close",
              "location",
              "/v1/login",
              "set-cookie",
              "ac_session=fixture; Path=/; HttpOnly",
            ],
          },
        );
        queueMicrotask(() => callback(response));
        return request;
      },
    );

    const response = await fetchLocalLearnerWire(
      "http://127.0.0.1:8000/v1/me",
      {
        method: "GET",
        headers: {
          "content-type": "application/json",
          cookie: "ac_session=fixture",
          host: "attacker.example",
          "accept-encoding": "gzip",
          "x-forwarded-host": "attacker.example",
        },
      },
    );

    expect(response.status).toBe(302);
    expect(await response.text()).toBe("fixture");
    expect(response.headers.get("location")).toBe("/v1/login");
    expect(response.headers.get("set-cookie")).toBe(
      "ac_session=fixture; Path=/; HttpOnly",
    );
    expect(response.headers.get("content-length")).toBeNull();
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(response.headers.get("x-ac-dev-data-mode")).toBe(
      "local-learner-sandbox",
    );
    expect(request.end).toHaveBeenCalledWith(undefined);
  });

  it.each([
    "https://127.0.0.1:8000/v1/me",
    "http://localhost:8000/v1/me",
    "http://127.0.0.1:8001/v1/me",
    "http://127.0.0.1:8000/me",
    "http://127.0.0.1:8000/v1/me#fragment",
    "http://user:password@127.0.0.1:8000/v1/me",
  ])("rejects an unsafe wire URL before IO: %s", async (url) => {
    await expect(fetchLocalLearnerWire(url)).rejects.toThrow(
      "numeric HTTP loopback URL on port 8000 under /v1/",
    );
    expect(httpRequest).not.toHaveBeenCalled();
  });

  it("accepts only an ArrayBuffer body and honors an already-cancelled request before IO", async () => {
    await expect(
      fetchLocalLearnerWire("http://127.0.0.1:8000/v1/me", {
        method: "POST",
        body: "unbounded string body",
      }),
    ).rejects.toThrow("bounded ArrayBuffer body");

    const controller = new AbortController();
    controller.abort(new Error("fixture cancellation"));
    await expect(
      fetchLocalLearnerWire("http://127.0.0.1:8000/v1/me", {
        signal: controller.signal,
        body: new ArrayBuffer(0),
      }),
    ).rejects.toThrow("fixture cancellation");
    expect(httpRequest).not.toHaveBeenCalled();
  });

  it("rejects an in-flight request when its caller aborts", async () => {
    const request = Object.assign(new EventEmitter(), { end: vi.fn() });
    httpRequest.mockImplementation(
      (_input: URL, options: { signal?: AbortSignal }) => {
        options.signal?.addEventListener(
          "abort",
          () => request.emit("error", options.signal?.reason),
          { once: true },
        );
        return request;
      },
    );
    const controller = new AbortController();
    const pending = fetchLocalLearnerWire("http://127.0.0.1:8000/v1/me", {
      signal: controller.signal,
    });

    controller.abort(new Error("in-flight fixture cancellation"));
    await expect(pending).rejects.toThrow("in-flight fixture cancellation");
  });

  it("rejects a response that exceeds the bounded native response limit", async () => {
    const request = Object.assign(new EventEmitter(), { end: vi.fn() });
    httpRequest.mockImplementation(
      (
        _input: URL,
        _options: { signal?: AbortSignal },
        callback: (response: Readable) => void,
      ) => {
        const response = Object.assign(
          Readable.from([Buffer.alloc(8 * 1024 * 1024 + 1)]),
          { statusCode: 200, rawHeaders: [] },
        );
        queueMicrotask(() => callback(response));
        return request;
      },
    );

    await expect(
      fetchLocalLearnerWire("http://127.0.0.1:8000/v1/me"),
    ).rejects.toThrow("bounded limit");
  });
});
