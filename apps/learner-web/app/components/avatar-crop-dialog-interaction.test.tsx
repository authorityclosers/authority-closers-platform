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

function closeButton() {
  return container.querySelector<HTMLButtonElement>(
    '[aria-label="Close avatar editor"]',
  )!;
}

function localPreview() {
  return container.querySelector<HTMLImageElement>(
    'img[alt="Local avatar preview"]',
  )!;
}

async function pressKey(
  key: string,
  target: EventTarget = document,
  shiftKey = false,
) {
  const event = new KeyboardEvent("keydown", {
    key,
    shiftKey,
    bubbles: true,
    cancelable: true,
  });
  await act(async () => target.dispatchEvent(event));
  return event;
}

const closeRoutes = ["Cancel", "X", "Escape", "backdrop"] as const;
type CloseRoute = (typeof closeRoutes)[number];

async function requestClose(route: CloseRoute) {
  if (route === "Escape") {
    await pressKey("Escape");
    return;
  }
  if (route === "backdrop") {
    await act(async () =>
      container
        .querySelector('[role="presentation"]')!
        .dispatchEvent(new MouseEvent("mousedown", { bubbles: true })),
    );
    return;
  }
  const trigger = route === "Cancel" ? button("Cancel") : closeButton();
  trigger.focus();
  await act(async () => trigger.click());
}

function holdUpload() {
  let finish!: (value: AvatarUploadResult) => void;
  let signal: AbortSignal | undefined;
  adapter.upload = vi.fn((_input, uploadSignal) => {
    signal = uploadSignal;
    return new Promise<AvatarUploadResult>((resolve) => {
      finish = resolve;
    });
  });
  return {
    get signal() {
      return signal;
    },
    finish(value: AvatarUploadResult) {
      finish(value);
    },
  };
}

describe("StrictMode mounted avatar editor", () => {
  it("finishes image decoding, supports keyboard crop, and cancels without an upload", async () => {
    await mount();
    const image = await choose();
    expect(button("Checking image…").disabled).toBe(true);
    await act(async () => image.onload?.());
    expect(container.textContent).toContain(
      "Only you can see this preview. Save when you’re ready.",
    );
    expect(button("Save photo").disabled).toBe(false);
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
    expect(onClose).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Discard this photo?");
    await act(async () => button("Discard photo").click());
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
    expect(button("Save photo").disabled).toBe(false);
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
    await act(async () => button("Save photo").click());
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Synthetic provider unavailable",
    );
    expect(
      container.querySelector<HTMLImageElement>(
        'img[alt="Local avatar preview"]',
      )!.src,
    ).toBe(src);
    expect(button("Save photo").disabled).toBe(false);
    await act(async () => button("Save photo").click());
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
    await act(async () => button("Save photo").click());
    expect(signal?.aborted).toBe(false);
    await act(async () => button("Cancel").click());
    expect(container.textContent).toContain("Leave photo editor?");
    expect(container.textContent).not.toContain("Discard this photo?");
    expect(signal?.aborted).toBe(false);
    expect(onClose).not.toHaveBeenCalled();
    await act(async () => button("Close editor").click());
    expect(signal?.aborted).toBe(true);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledWith({ saveMayBePending: true });
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

describe("photo editor close confirmation", () => {
  it.each(closeRoutes)(
    "closes an untouched editor immediately through %s",
    async (route) => {
      await mount();
      await requestClose(route);
      expect(onClose).toHaveBeenCalledTimes(1);
      expect(container.textContent).not.toContain("Discard this photo?");
      expect(container.textContent).not.toContain("Leave photo editor?");
      expect(adapter.upload).not.toHaveBeenCalled();
    },
  );

  it.each(closeRoutes)(
    "protects a local crop through %s and keeps its exact preview and framing",
    async (route) => {
      await mount();
      const image = await choose();
      await act(async () => image.onload?.());
      const preview = container.querySelector<HTMLElement>(
        '[aria-label="Circular avatar crop preview"]',
      )!;
      await pressKey("+", preview);
      await pressKey("ArrowRight", preview);
      preview.focus();
      const src = localPreview().src;
      const framing = localPreview().style.transform;
      const priorTrigger =
        route === "Cancel"
          ? button("Cancel")
          : route === "X"
            ? closeButton()
            : preview;

      await requestClose(route);
      expect(container.textContent).toContain("Discard this photo?");
      expect(document.activeElement).toBe(button("Keep editing"));
      expect(onClose).not.toHaveBeenCalled();
      expect(adapter.upload).not.toHaveBeenCalled();
      expect(URL.revokeObjectURL).not.toHaveBeenCalledWith(src);

      await act(async () => button("Keep editing").click());
      expect(container.textContent).not.toContain("Discard this photo?");
      expect(localPreview().src).toBe(src);
      expect(localPreview().style.transform).toBe(framing);
      expect(document.activeElement).toBe(
        priorTrigger.isConnected ? priorTrigger : closeButton(),
      );
      expect(onClose).not.toHaveBeenCalled();
      expect(onSuccess).not.toHaveBeenCalled();
      expect(adapter.upload).not.toHaveBeenCalled();
      expect(URL.revokeObjectURL).not.toHaveBeenCalledWith(src);

      await requestClose(route);
      await act(async () => button("Discard photo").click());
      expect(onClose).toHaveBeenCalledTimes(1);
      expect(onClose).toHaveBeenCalledWith({ saveMayBePending: false });
      expect(adapter.upload).not.toHaveBeenCalled();
      expect(onSuccess).not.toHaveBeenCalled();
    },
  );

  it("protects a file while decoding and allows decoding to finish after Keep editing", async () => {
    await mount();
    const image = await choose();
    const src = localPreview().src;
    await requestClose("Cancel");
    expect(container.textContent).toContain("Discard this photo?");
    expect(onClose).not.toHaveBeenCalled();
    await act(async () => button("Keep editing").click());
    await act(async () => image.onload?.());
    expect(localPreview().src).toBe(src);
    expect(button("Save photo").disabled).toBe(false);
    expect(URL.revokeObjectURL).not.toHaveBeenCalledWith(src);
    expect(adapter.upload).not.toHaveBeenCalled();
  });

  it("uses Escape to dismiss confirmation and restores focus without losing the draft", async () => {
    await mount();
    const image = await choose();
    await act(async () => image.onload?.());
    const preview = container.querySelector<HTMLElement>(
      '[aria-label="Circular avatar crop preview"]',
    )!;
    await pressKey("+", preview);
    const src = localPreview().src;
    const framing = localPreview().style.transform;
    preview.focus();
    await pressKey("Escape", preview);
    expect(container.textContent).toContain("Discard this photo?");
    await pressKey("Escape", button("Keep editing"));
    expect(container.textContent).not.toContain("Discard this photo?");
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();
    expect(document.activeElement).toBe(preview);
    expect(localPreview().src).toBe(src);
    expect(localPreview().style.transform).toBe(framing);
    expect(onClose).not.toHaveBeenCalled();
    expect(adapter.upload).not.toHaveBeenCalled();
  });

  it("restores focus to Close when the close request has no editor focus origin", async () => {
    await mount();
    const image = await choose();
    await act(async () => image.onload?.());
    closeButton().blur();
    expect(container.contains(document.activeElement)).toBe(false);
    await requestClose("backdrop");
    await act(async () => button("Keep editing").click());
    expect(document.activeElement).toBe(closeButton());
    expect(onClose).not.toHaveBeenCalled();
  });

  it("traps focus through both confirmation actions and excludes disabled upload controls", async () => {
    const upload = holdUpload();
    await mount();
    const image = await choose();
    await act(async () => image.onload?.());
    await requestClose("Cancel");
    button("Discard photo").focus();
    expect(
      (await pressKey("Tab", button("Discard photo"))).defaultPrevented,
    ).toBe(true);
    const draftFirst = document.activeElement;
    expect(
      draftFirst === closeButton() || draftFirst === button("Keep editing"),
    ).toBe(true);
    await pressKey("Tab", draftFirst!, true);
    expect(document.activeElement).toBe(button("Discard photo"));
    await act(async () => button("Keep editing").click());

    await act(async () => button("Save photo").click());
    expect(button("Saving photo…").disabled).toBe(true);
    expect(
      container.querySelector<HTMLInputElement>('input[type="file"]')!.disabled,
    ).toBe(true);
    expect(
      container.querySelector<HTMLInputElement>('[aria-label="Photo zoom"]')!
        .disabled,
    ).toBe(true);
    button("Cancel").focus();
    expect((await pressKey("Tab", button("Cancel"))).defaultPrevented).toBe(
      true,
    );
    expect(document.activeElement).toBe(closeButton());
    await pressKey("Tab", closeButton(), true);
    expect(document.activeElement).toBe(button("Cancel"));

    await requestClose("Cancel");
    expect(document.activeElement).toBe(button("Keep editing"));
    button("Close editor").focus();
    expect(
      (await pressKey("Tab", button("Close editor"))).defaultPrevented,
    ).toBe(true);
    const first = document.activeElement;
    expect(first === closeButton() || first === button("Keep editing")).toBe(
      true,
    );
    await pressKey("Tab", first!, true);
    expect(document.activeElement).toBe(button("Close editor"));
    expect(upload.signal?.aborted).toBe(false);
    expect(adapter.upload).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("keeps an in-flight save alive and handles its success once after dismissing confirmation", async () => {
    const upload = holdUpload();
    await mount();
    const image = await choose();
    await act(async () => image.onload?.());
    const src = localPreview().src;
    const framing = localPreview().style.transform;
    await act(async () => button("Save photo").click());
    await requestClose("X");
    expect(container.textContent).toContain("Leave photo editor?");
    expect(container.textContent).toMatch(
      /may (already )?have reached.*service/i,
    );
    expect(container.textContent).not.toContain("Discard this photo?");
    expect(upload.signal?.aborted).toBe(false);
    await act(async () => button("Keep editing").click());
    expect(document.activeElement).toBe(closeButton());
    expect(localPreview().src).toBe(src);
    expect(localPreview().style.transform).toBe(framing);
    expect(button("Saving photo…").disabled).toBe(true);
    await act(async () => button("Saving photo…").click());
    expect(adapter.upload).toHaveBeenCalledTimes(1);
    expect(upload.signal?.aborted).toBe(false);
    expect(onClose).not.toHaveBeenCalled();

    await pressKey("Escape");
    expect(container.textContent).toContain("Leave photo editor?");
    await pressKey("Escape", button("Keep editing"));
    expect(container.textContent).not.toContain("Leave photo editor?");
    expect(upload.signal?.aborted).toBe(false);
    expect(adapter.upload).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();

    const avatar = {
      deliveryUrl: "https://avatar.example.invalid/confirmed.png",
      alt: "Confirmed fixture",
      revision: "2",
    };
    await act(async () => upload.finish({ status: "success", avatar }));
    expect(onSuccess).toHaveBeenCalledExactlyOnceWith(avatar);
    expect(container.textContent).toContain("Avatar updated.");
    expect(adapter.upload).toHaveBeenCalledTimes(1);
  });

  it("retains the service warning after a failed save and Escape returns to the retry state", async () => {
    await mount();
    const image = await choose();
    await act(async () => image.onload?.());
    await act(async () => button("Save photo").click());
    expect(container.textContent).toContain("Synthetic provider unavailable");
    await requestClose("Escape");
    expect(container.textContent).toContain("Leave photo editor?");
    expect(container.textContent).toMatch(
      /may (already )?have reached.*service/i,
    );
    expect(container.textContent).not.toContain("Discard this photo?");
    await pressKey("Escape", button("Keep editing"));
    expect(container.textContent).not.toContain("Leave photo editor?");
    expect(onClose).not.toHaveBeenCalled();
    expect(adapter.upload).toHaveBeenCalledTimes(1);
    expect(button("Save photo").disabled).toBe(false);
  });
});

it("offers bounded zoom controls and matching live identity previews without uploading", async () => {
  await mount();
  expect(container.querySelector('[aria-label="Photo zoom"]')).toBeNull();
  const image = await choose();
  await act(async () => image.onload?.());
  const zoom = container.querySelector<HTMLInputElement>(
    '[aria-label="Photo zoom"]',
  )!;
  expect(zoom.min).toBe("1");
  expect(zoom.max).toBe("2");
  const plus = container.querySelector<HTMLButtonElement>(
    '[aria-label="Zoom in"]',
  )!;
  await act(async () => plus.click());
  expect(Number(zoom.value)).toBeCloseTo(1.1);
  const main = container.querySelector<HTMLImageElement>(
    'img[alt="Local avatar preview"]',
  )!;
  const mini = container.querySelector(
    '[aria-label="How your photo will appear"]',
  )!;
  expect(mini.querySelectorAll("img").length).toBe(2);
  for (const img of mini.querySelectorAll("img"))
    expect(img.style.transform).toBe(main.style.transform);
  expect(main.style.transform).toContain("scale(1.1)");
  await act(async () => button("Reset framing").click());
  expect(zoom.value).toBe("1");
  expect(
    container.querySelector<HTMLButtonElement>('[aria-label="Zoom out"]')!
      .disabled,
  ).toBe(true);
  expect(adapter.upload).not.toHaveBeenCalled();
  expect(
    container.querySelector("footer")?.contains(button("Save photo")),
  ).toBe(true);
});
