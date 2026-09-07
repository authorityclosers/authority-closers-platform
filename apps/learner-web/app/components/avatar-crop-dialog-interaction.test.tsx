// @vitest-environment happy-dom

import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from "vitest";

import type {
  AvatarPresentation,
  AvatarUploadPort,
  AvatarUploadResult,
} from "../lib/avatar-upload";
import { AvatarCropDialog } from "./avatar-crop-dialog";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

class DecodedFixtureImage {
  static pending: DecodedFixtureImage[] = [];
  naturalWidth = 512;
  naturalHeight = 512;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  set src(_value: string) {
    DecodedFixtureImage.pending.push(this);
  }
}

let root: Root;
let container: HTMLDivElement;
let adapter: AvatarUploadPort;
let onClose: Mock<() => void>;
let onSuccess: Mock<(avatar: AvatarPresentation) => void>;
let unmounted: boolean;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  unmounted = false;
  DecodedFixtureImage.pending = [];
  vi.stubGlobal("Image", DecodedFixtureImage);
  let sequence = 0;
  vi.spyOn(URL, "createObjectURL").mockImplementation(
    () => `blob:profile-fixture-${++sequence}`,
  );
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  onClose = vi.fn();
  onSuccess = vi.fn();
  adapter = {
    upload: vi.fn<AvatarUploadPort["upload"]>(async () => ({
      status: "retryable_error",
      message: "Synthetic provider unavailable. Try again.",
    })),
  };
});

afterEach(async () => {
  if (!unmounted) await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function mount() {
  await act(async () =>
    root.render(
      <StrictMode>
        <AvatarCropDialog
          displayName="Photo fixture"
          adapter={adapter}
          currentAvatar={{
            deliveryUrl: "https://avatar.example.invalid/current.png",
            alt: "Current fixture photo",
            revision: "1",
          }}
          onClose={onClose}
          onSuccess={onSuccess}
        />
      </StrictMode>,
    ),
  );
}

function button(label: string) {
  const control = Array.from(container.querySelectorAll("button")).find(
    (element) => element.textContent?.trim() === label,
  );
  expect(control, label).toBeDefined();
  return control!;
}

async function choose(name = "fixture.png") {
  const field =
    container.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(field, "files", {
    configurable: true,
    value: [new File(["synthetic-image-bytes"], name, { type: "image/png" })],
  });
  await act(async () =>
    field.dispatchEvent(new Event("change", { bubbles: true })),
  );
  return DecodedFixtureImage.pending.at(-1)!;
}

describe("StrictMode mounted avatar editor", () => {
  it("finishes image decoding, supports keyboard crop, and cancels without an upload", async () => {
    await mount();
    const image = await choose();
    expect(button("Checking image…").disabled).toBe(true);
    await act(async () => image.onload?.());
    expect(container.textContent).toContain(
      "Local preview only. Nothing has been uploaded.",
    );
    expect(button("Upload avatar").disabled).toBe(false);
    const preview = container.querySelector<HTMLElement>(
      '[aria-label="Circular avatar crop preview"]',
    )!;
    await act(async () =>
      preview.dispatchEvent(
        new KeyboardEvent("keydown", { key: "+", bubbles: true }),
      ),
    );
    expect(preview.querySelector("img")?.style.transform).toContain(
      "scale(1.06)",
    );
    await act(async () =>
      preview.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Home", bubbles: true }),
      ),
    );
    expect(preview.querySelector("img")?.style.transform).toContain("scale(1)");
    await act(async () => button("Cancel").click());
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(adapter.upload).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("keeps the newer crop selection when an older image decode settles late", async () => {
    await mount();
    const oldImage = await choose("old.png");
    const nextImage = await choose("next.png");
    await act(async () => nextImage.onload?.());
    const nextPreview = container.querySelector<HTMLImageElement>(
      'img[alt="Local avatar preview"]',
    )!.src;
    await act(async () => oldImage.onload?.());
    expect(
      container.querySelector<HTMLImageElement>(
        'img[alt="Local avatar preview"]',
      )!.src,
    ).toBe(nextPreview);
    expect(button("Upload avatar").disabled).toBe(false);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:profile-fixture-1");
    expect(URL.revokeObjectURL).not.toHaveBeenCalledWith(nextPreview);
    expect(adapter.upload).not.toHaveBeenCalled();
  });

  it("revokes a pending preview and ignores decoding after unmount", async () => {
    await mount();
    const image = await choose();
    await act(async () => root.unmount());
    unmounted = true;
    await act(async () => image.onload?.());
    expect(container.childElementCount).toBe(0);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:profile-fixture-1");
    expect(onSuccess).not.toHaveBeenCalled();
    expect(adapter.upload).not.toHaveBeenCalled();
  });

  it("retains the selected crop after a failed upload and retries without claiming success", async () => {
    await mount();
    const image = await choose();
    await act(async () => image.onload?.());
    const src = container.querySelector<HTMLImageElement>(
      'img[alt="Local avatar preview"]',
    )!.src;
    await act(async () => button("Upload avatar").click());
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Synthetic provider unavailable",
    );
    expect(
      container.querySelector<HTMLImageElement>(
        'img[alt="Local avatar preview"]',
      )!.src,
    ).toBe(src);
    expect(button("Upload avatar").disabled).toBe(false);
    await act(async () => button("Upload avatar").click());
    expect(adapter.upload).toHaveBeenCalledTimes(2);
    expect(onSuccess).not.toHaveBeenCalled();
    expect(container.textContent).not.toContain("Avatar updated.");
  });

  it("aborts an in-flight upload on cancellation and ignores its late success", async () => {
    let finish!: (value: AvatarUploadResult) => void;
    let signal: AbortSignal | undefined;
    adapter.upload = vi.fn((_input, uploadSignal) => {
      signal = uploadSignal;
      return new Promise<AvatarUploadResult>((resolve) => {
        finish = resolve;
      });
    });
    await mount();
    const image = await choose();
    await act(async () => image.onload?.());
    await act(async () => button("Upload avatar").click());
    expect(signal?.aborted).toBe(false);
    await act(async () => button("Cancel").click());
    expect(signal?.aborted).toBe(true);
    await act(async () =>
      finish({
        status: "success",
        avatar: {
          deliveryUrl: "https://avatar.example.invalid/late.png",
          alt: "Late fixture",
          revision: "2",
        },
      }),
    );
    expect(onSuccess).not.toHaveBeenCalled();
  });
});
