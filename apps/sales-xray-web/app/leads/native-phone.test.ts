import { afterEach, describe, expect, it, vi } from "vitest";

import {
  inPhoneApp,
  missedReason,
  onPhoneCall,
  parseCall,
  readLastCall,
  readPhoneRecording,
  startPhoneCall,
} from "./native-phone";

type Listener = (event: { data: unknown }) => void;

/** A stand-in for the app's SXPhone object that answers like the phone. */
function fakePhone(
  answer: (message: {
    id: string;
    method: string;
    args: Record<string, unknown>;
  }) => unknown,
) {
  const listeners: Listener[] = [];
  const sent: { method: string; args: Record<string, unknown> }[] = [];
  const phone = {
    addEventListener: (_: string, listener: Listener) =>
      listeners.push(listener),
    postMessage: (data: string) => {
      const message = JSON.parse(data) as {
        id: string;
        method: string;
        args: Record<string, unknown>;
      };
      sent.push({ method: message.method, args: message.args });
      const result = answer(message);
      queueMicrotask(() =>
        listeners.forEach((listener) =>
          listener({
            data: JSON.stringify({ id: message.id, ok: true, result }),
          }),
        ),
      );
    },
    emit: (payload: unknown) =>
      listeners.forEach((listener) =>
        listener({ data: JSON.stringify(payload) }),
      ),
  };
  vi.stubGlobal("SXPhone", phone);
  return { phone, sent };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the phone app's channel", () => {
  it("is absent in a browser, so Call stays a tel: link", async () => {
    expect(inPhoneApp()).toBe(false);
    expect(await readLastCall("lead-1")).toBeNull();
  });

  it("places the call and reads the finished call back", async () => {
    const { sent } = fakePhone((message) =>
      message.method === "lastCall"
        ? {
            leadId: "lead-1",
            number: "+919876543210",
            startedMs: 1000,
            endedMs: 223000,
            durationSeconds: 221.6,
            connected: true,
            result: "answered",
            recording: {
              source: "media:content://1",
              name: "Asha_2410.m4a",
              size: 1200,
              durationMs: 221000,
              ext: "m4a",
              mime: "audio/mp4",
              supported: true,
            },
            final: true,
          }
        : {},
    );
    expect(inPhoneApp()).toBe(true);
    await startPhoneCall({
      leadId: "lead-1",
      number: "+919876543210",
      name: "Asha",
    });
    const call = await readLastCall("lead-1");
    expect(sent.map((item) => item.method)).toEqual(["call", "lastCall"]);
    expect(call).toMatchObject({
      connected: true,
      durationSeconds: 222,
      final: true,
    });
    expect(call?.recording?.name).toBe("Asha_2410.m4a");
  });

  it("hears when a call ends", () => {
    const { phone } = fakePhone(() => ({}));
    const heard: string[] = [];
    const stop = onPhoneCall((call) =>
      heard.push(`${call.leadId}:${call.result}`),
    );
    phone.emit({
      event: "call",
      call: { leadId: "lead-2", result: "no_answer", connected: false },
    });
    stop();
    phone.emit({ event: "call", call: { leadId: "lead-3", result: "busy" } });
    expect(heard).toEqual(["lead-2:no_answer"]);
  });

  it("reads a recording in pieces into one file", async () => {
    const pieces = [btoa("abc"), btoa("de")];
    fakePhone((message) => {
      const index = (message.args.offset as number) === 0 ? 0 : 1;
      return { data: pieces[index], eof: index === 1 };
    });
    const file = await readPhoneRecording({
      source: "media:content://1",
      name: "call.m4a",
      size: 5,
      durationMs: 1000,
      ext: "m4a",
      mime: "audio/mp4",
      supported: true,
    });
    expect(file.name).toBe("call.m4a");
    expect(await file.text()).toBe("abcde");
  });
});

describe("reading the phone's answer", () => {
  it("keeps a call the phone placed with no network", () => {
    expect(
      parseCall({ leadId: "x", result: "no_network", connected: false }),
    ).toMatchObject({ result: "no_network", connected: false });
  });

  it("keeps only well-formed calls", () => {
    expect(parseCall(null)).toBeNull();
    expect(parseCall({ result: "answered" })).toBeNull();
    expect(
      parseCall({ leadId: "x", result: "odd", durationSeconds: -3 }),
    ).toMatchObject({
      result: "unknown",
      durationSeconds: null,
      connected: null,
      recording: null,
      final: false,
    });
  });

  it("maps what the phone saw to a reason", () => {
    expect(missedReason("no_answer")).toBe("did_not_pick");
    expect(missedReason("busy")).toBe("busy");
    expect(missedReason("rejected")).toBe("disconnected");
    expect(missedReason("failed")).toBe("not_connected");
    expect(missedReason("no_network")).toBe("out_of_coverage");
    expect(missedReason("answered")).toBeNull();
  });
});
