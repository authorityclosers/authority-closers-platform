// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { resetBackCloseForTests } from "../ui/back-close";
import { MarkupEditor } from "./markup";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Mark up or blur loads its picture from a blob address. The QA robot, 8 Nov
// 2026 (fecaec8b, da117607): the address was let go while the picture was
// still loading, and the browser logged ERR_FILE_NOT_FOUND for it.
class TestImage {
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  src = "";
  naturalWidth = 4;
  naturalHeight = 3;
  constructor() {
    images.push(this);
  }
}
let images: TestImage[];
let made: number;
let revoked: string[];
let host: HTMLDivElement;
let root: Root | null;
const original = {
  create: URL.createObjectURL,
  revoke: URL.revokeObjectURL,
};

beforeEach(() => {
  resetBackCloseForTests();
  images = [];
  made = 0;
  revoked = [];
  URL.createObjectURL = () => `blob:test/${++made}`;
  URL.revokeObjectURL = (url: string) => {
    revoked.push(url);
  };
  vi.stubGlobal("Image", TestImage);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  host.remove();
  URL.createObjectURL = original.create;
  URL.revokeObjectURL = original.revoke;
  vi.unstubAllGlobals();
});

const show = () =>
  act(async () =>
    root!.render(
      <MarkupEditor
        source={new Blob(["picture"], { type: "image/png" })}
        onDone={vi.fn()}
        onCancel={vi.fn()}
      />,
    ),
  );

it("keeps the picture's address until the picture has loaded, even when the step closes first", async () => {
  await show();
  expect(images).toHaveLength(1);
  expect(images[0].src).toBe("blob:test/1");
  await act(async () => root!.unmount());
  root = null;
  expect(revoked).toEqual([]);
  await act(async () => images[0].onload?.());
  expect(revoked).toEqual(["blob:test/1"]);
});

it("lets the address go once the picture has loaded, or failed", async () => {
  await show();
  await act(async () => images[0].onload?.());
  expect(revoked).toEqual(["blob:test/1"]);

  await act(async () => root!.unmount());
  root = createRoot(host);
  await show();
  await act(async () => images[1].onerror?.());
  expect(revoked).toEqual(["blob:test/1", "blob:test/2"]);
});
