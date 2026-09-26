import { afterEach, describe, expect, it, vi } from "vitest";

import {
  rememberPendingUpload,
  rememberSubmission,
} from "../acquisition-client";
import { sendSource } from "./source-upload";

const id = "11111111-1111-4111-8111-111111111111";
const recordingId = "22222222-2222-4222-8222-222222222222";
const sha = "a".repeat(64);
const policySha = "b".repeat(64);
const source = new File(["local audio bytes"], "call.wav", {
  type: "audio/wav",
});
const consent = { accepted: true, policySha256: policySha } as const;
const boundSubmission = {
  submission_id: id,
  recording_id: recordingId,
  source_sha256: sha,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("source upload reconciliation", () => {
  it("always reads the pending submission before the first PUT", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 404 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(boundSubmission), { status: 200 }),
      );
    vi.stubGlobal("fetch", fetch);
    const onPut = vi.fn();

    const result = await sendSource({
      id,
      file: source,
      sha,
      policySha,
      uploadConsent: consent,
      signal: new AbortController().signal,
      onPut,
    });

    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[0]?.[0]).toBe(
      `/v1/conversation/acquisition/submissions/${id}`,
    );
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    });
    expect(fetch.mock.calls[1]?.[0]).toBe(
      `/v1/conversation/acquisition/submissions/${id}/source`,
    );
    expect(fetch.mock.calls[1]?.[1]).toMatchObject({
      method: "PUT",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: {
        accept: "application/json",
        "Content-Type": "application/octet-stream",
        "X-Source-SHA256": sha,
        "X-Upload-Policy": policySha,
        "X-Upload-Consent": "accepted",
      },
      body: source,
    });
    expect(onPut).toHaveBeenCalledOnce();
    expect(result).toMatchObject({
      submissionId: id,
      bound: { id, recordingId, sha },
      recovered: false,
    });
    expect(localStorage.getItem("ac.xray.pending-upload.v1")).toBeNull();
    expect(localStorage.getItem("ac.xray.submission.v1")).toBe(id);
  });

  it("recovers an already accepted upload without sending the File again", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify(boundSubmission), { status: 200 }),
      );
    vi.stubGlobal("fetch", fetch);

    const result = await sendSource({
      id,
      file: source,
      sha,
      policySha,
      uploadConsent: consent,
      signal: new AbortController().signal,
    });

    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch.mock.calls[0]?.[0]).toBe(
      `/v1/conversation/acquisition/submissions/${id}`,
    );
    expect(result.recovered).toBe(true);
    expect(localStorage.getItem("ac.xray.submission.v1")).toBe(id);
  });

  it("requires current consent after a safe read finds no saved upload", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response("", { status: 404 }));
    vi.stubGlobal("fetch", fetch);

    await expect(
      sendSource({
        id,
        file: source,
        sha,
        policySha,
        uploadConsent: { accepted: false, policySha256: policySha },
        signal: new AbortController().signal,
      }),
    ).rejects.toThrow("current_upload_consent_required");
    await expect(
      sendSource({
        id,
        file: source,
        sha,
        policySha,
        uploadConsent: { accepted: true, policySha256: "c".repeat(64) },
        signal: new AbortController().signal,
      }),
    ).rejects.toThrow("current_upload_consent_required");
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      `/v1/conversation/acquisition/submissions/${id}`,
      `/v1/conversation/acquisition/submissions/${id}`,
    ]);
    expect(fetch.mock.calls.every(([, init]) => init?.method !== "PUT")).toBe(
      true,
    );
  });

  it("reconciles a saved upload without asking for consent again", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify(boundSubmission), { status: 200 }),
      );
    vi.stubGlobal("fetch", fetch);

    await expect(
      sendSource({
        id,
        file: source,
        sha,
        policySha,
        uploadConsent: { accepted: false, policySha256: policySha },
        signal: new AbortController().signal,
      }),
    ).resolves.toMatchObject({
      submissionId: id,
      recovered: true,
    });
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch.mock.calls[0]?.[0]).toBe(
      `/v1/conversation/acquisition/submissions/${id}`,
    );
    expect(fetch.mock.calls[0]?.[1]?.method ?? "GET").toBe("GET");
    expect(localStorage.getItem("ac.xray.submission.v1")).toBe(id);
  });

  it.each([
    ["a denied read", () => Promise.resolve(new Response("", { status: 403 }))],
    [
      "a redirect failure",
      () => Promise.reject(new TypeError("Failed to fetch")),
    ],
  ])("never PUTs after %s", async (_label, recoveryRead) => {
    const fetch = vi.fn().mockImplementation(recoveryRead);
    vi.stubGlobal("fetch", fetch);

    await expect(
      sendSource({
        id,
        file: source,
        sha,
        policySha,
        uploadConsent: consent,
        signal: new AbortController().signal,
      }),
    ).rejects.toBeDefined();
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("keeps a pending selector after an uncertain PUT, then reads it before retry", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 404 }))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(boundSubmission), { status: 200 }),
      );
    vi.stubGlobal("fetch", fetch);
    const request = () =>
      sendSource({
        id,
        file: source,
        sha,
        policySha,
        uploadConsent: consent,
        signal: new AbortController().signal,
      });

    await expect(request()).rejects.toThrow("Failed to fetch");
    expect(localStorage.getItem("ac.xray.pending-upload.v1")).toBe(id);
    await expect(request()).resolves.toMatchObject({ recovered: true });
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(fetch.mock.calls[2]?.[0]).toBe(
      `/v1/conversation/acquisition/submissions/${id}`,
    );
    expect(localStorage.getItem("ac.xray.pending-upload.v1")).toBeNull();
    expect(localStorage.getItem("ac.xray.submission.v1")).toBe(id);
  });

  it("requires a reconciled response to match both the ID and source hash", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ ...boundSubmission, source_sha256: "c".repeat(64) }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetch);

    await expect(
      sendSource({
        id,
        file: source,
        sha,
        policySha,
        uploadConsent: consent,
        signal: new AbortController().signal,
      }),
    ).rejects.toThrow("uploaded_source_mismatch");
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("does not save a late successful GET after the request is aborted", async () => {
    const lateRead = deferred<Response>();
    const fetch = vi.fn(() => lateRead.promise);
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();
    const request = sendSource({
      id,
      file: source,
      sha,
      policySha,
      uploadConsent: consent,
      signal: controller.signal,
    });

    expect(fetch).toHaveBeenCalledOnce();
    controller.abort();
    lateRead.resolve(
      new Response(JSON.stringify(boundSubmission), { status: 200 }),
    );

    await expect(request).rejects.toBeDefined();
    expect(localStorage.getItem("ac.xray.submission.v1")).toBeNull();
    expect(localStorage.getItem("ac.xray.pending-upload.v1")).toBeNull();
  });

  it("does not start a PUT when its missing-source read resolves after abort", async () => {
    const lateRead = deferred<Response>();
    const fetch = vi.fn(() => lateRead.promise);
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();
    const request = sendSource({
      id,
      file: source,
      sha,
      policySha,
      uploadConsent: consent,
      signal: controller.signal,
    });

    controller.abort();
    lateRead.resolve(new Response("", { status: 404 }));

    await expect(request).rejects.toBeDefined();
    expect(fetch).toHaveBeenCalledOnce();
    expect(localStorage.getItem("ac.xray.pending-upload.v1")).toBeNull();
  });

  it("does not restore selectors from a late PUT after sign-out clears them", async () => {
    const latePut = deferred<Response>();
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 404 }))
      .mockReturnValueOnce(latePut.promise);
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();
    const request = sendSource({
      id,
      file: source,
      sha,
      policySha,
      uploadConsent: consent,
      signal: controller.signal,
    });

    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(localStorage.getItem("ac.xray.pending-upload.v1")).toBe(id);
    controller.abort();
    rememberSubmission(null);
    rememberPendingUpload(null);
    latePut.resolve(
      new Response(JSON.stringify(boundSubmission), { status: 200 }),
    );

    await expect(request).rejects.toBeDefined();
    expect(localStorage.getItem("ac.xray.submission.v1")).toBeNull();
    expect(localStorage.getItem("ac.xray.pending-upload.v1")).toBeNull();
  });
});
