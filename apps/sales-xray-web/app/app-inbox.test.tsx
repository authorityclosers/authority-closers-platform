import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AppInbox, parseAppUploads, uploadFileName } from "./app-inbox";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT =
  true;

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const waiting = {
  uploads: [
    {
      id: "u1",
      app: "Pulse",
      title: "Discovery call — Greenleaf",
      file_name: "greenleaf-call",
      media_type: "audio/mpeg",
      bytes: 2_400_000,
      call_at: "2026-10-25T04:00:00Z",
    },
    { id: "broken" },
  ],
};

it("reads waiting recordings and names files so the uploader accepts them", () => {
  const [upload, ...rest] = parseAppUploads(waiting);
  expect(rest).toEqual([]);
  expect(upload.title).toBe("Discovery call — Greenleaf");
  expect(uploadFileName(upload)).toBe("greenleaf-call.mp3");
  expect(uploadFileName({ ...upload, fileName: "call.m4a" })).toBe("call.m4a");
  expect(parseAppUploads(null)).toEqual([]);
});

it("hands a recording from Pulse to the uploader, then marks it added", async () => {
  const sent: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      sent.push(`${init?.method ?? "GET"} ${url}`);
      if (url.endsWith("/file"))
        return new Response(new Blob(["fake-audio"]), { status: 200 });
      if (url.endsWith("/imported")) return Response.json({ state: "added" });
      return Response.json(waiting);
    }),
  );
  const onFile = vi.fn();
  await act(async () =>
    root.render(<AppInbox disabled={false} onFile={onFile} submissionId={null} />),
  );
  await act(async () => {});
  expect(host.textContent).toContain("From Pulse: 1 recording for you");
  const add = Array.from(host.querySelectorAll("button")).find(
    (button) => button.textContent === "Add",
  )!;
  await act(async () => add.click());
  await act(async () => {});
  expect(onFile).toHaveBeenCalledTimes(1);
  const file = onFile.mock.calls[0][0] as File;
  expect(file.name).toBe("greenleaf-call.mp3");
  expect(file.type).toBe("audio/mpeg");
  await act(async () =>
    root.render(
      <AppInbox disabled={false} onFile={onFile} submissionId="call-1" />,
    ),
  );
  await act(async () => {});
  expect(sent).toContain("POST /v1/sales-xray/app-uploads/u1/imported");
  expect(host.textContent).toBe("");
});

it("shows nothing when no app sent anything", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ uploads: [] })),
  );
  await act(async () =>
    root.render(<AppInbox disabled={false} onFile={vi.fn()} submissionId={null} />),
  );
  expect(host.textContent).toBe("");
});
