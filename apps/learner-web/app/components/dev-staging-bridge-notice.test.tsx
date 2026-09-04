import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/dev-api-proxy", () => ({
  isStagingAuthenticatedBridge: vi.fn(),
}));

import { isStagingAuthenticatedBridge } from "../lib/dev-api-proxy";
import {
  DEV_STAGING_NOTICE_STORAGE_KEY,
  DevStagingBridgeNotice,
  getSessionStorage,
  isDevNoticeToggleShortcut,
  isEditableTarget,
  isNoticeDismissed,
  setNoticeDismissed,
  toggleDevNotice,
} from "./dev-staging-bridge-notice";

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => void values.delete(key),
    setItem: (key, value) => void values.set(key, value),
  };
}

describe("DevStagingBridgeNotice", () => {
  beforeEach(() => {
    vi.mocked(isStagingAuthenticatedBridge).mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("stays out of production when the authenticated bridge is disabled", () => {
    vi.mocked(isStagingAuthenticatedBridge).mockReturnValue(false);

    expect(renderToStaticMarkup(createElement(DevStagingBridgeNotice))).toBe(
      "",
    );
  });

  it("renders a collapsed, non-layout-blocking disclosure in local bridge mode with accessible dismiss and discoverable hint", () => {
    vi.mocked(isStagingAuthenticatedBridge).mockReturnValue(true);

    const html = renderToStaticMarkup(createElement(DevStagingBridgeNotice));

    expect(html).toContain("<details");
    expect(html).toContain('class="dev-staging-bridge-notice"');
    expect(html).toContain('aria-label="Development staging data notice"');
    expect(html).toContain("Dev · staging data");
    expect(html).not.toContain(' open="');
    expect(html).toContain("real staging learner account");

    // Accessible dismiss button
    expect(html).toContain("<button");
    expect(html).toContain('type="button"');
    expect(html).toContain('class="dev-staging-bridge-notice__dismiss"');
    expect(html).toContain(
      'aria-label="Dismiss staging notice (Alt+Shift+D to restore)"',
    );

    // Discoverable keyboard shortcut hint
    expect(html).toContain("Alt+Shift+D");
    expect(html).toContain("Option+Shift+D");
  });

  describe("sessionStorage safe persistence", () => {
    it("defaults to not dismissed when storage is empty", () => {
      const storage = memoryStorage();
      expect(isNoticeDismissed(storage)).toBe(false);
    });

    it("persists dismissal and restoration cleanly in sessionStorage", () => {
      const storage = memoryStorage();
      expect(isNoticeDismissed(storage)).toBe(false);

      const dismissedResult = setNoticeDismissed(true, storage);
      expect(dismissedResult).toBe(true);
      expect(storage.getItem(DEV_STAGING_NOTICE_STORAGE_KEY)).toBe("true");
      expect(isNoticeDismissed(storage)).toBe(true);

      const restoreResult = setNoticeDismissed(false, storage);
      expect(restoreResult).toBe(true);
      expect(storage.getItem(DEV_STAGING_NOTICE_STORAGE_KEY)).toBeNull();
      expect(isNoticeDismissed(storage)).toBe(false);
    });

    it("handles storage access throwing SecurityError gracefully", () => {
      const blockedStorage = {
        getItem: () => {
          throw new Error("SecurityError: storage access denied");
        },
        setItem: () => {
          throw new Error("SecurityError: storage access denied");
        },
        removeItem: () => {
          throw new Error("SecurityError: storage access denied");
        },
        clear: () => {},
        length: 0,
        key: () => null,
      };

      expect(isNoticeDismissed(blockedStorage)).toBe(false);
      expect(setNoticeDismissed(true, blockedStorage)).toBe(false);
      expect(setNoticeDismissed(false, blockedStorage)).toBe(false);
    });

    it("handles storage quota errors gracefully", () => {
      const quotaStorage = {
        getItem: () => null,
        setItem: () => {
          const err = new Error("QuotaExceededError");
          err.name = "QuotaExceededError";
          throw err;
        },
        removeItem: () => {},
        clear: () => {},
        length: 0,
        key: () => null,
      };

      expect(setNoticeDismissed(true, quotaStorage)).toBe(false);
    });

    it("handles null storage without crashing", () => {
      expect(isNoticeDismissed(null)).toBe(false);
      expect(setNoticeDismissed(true, null)).toBe(false);
      expect(setNoticeDismissed(false, null)).toBe(false);
    });

    it("safely resolves getSessionStorage in node / test environment", () => {
      // In node env without window, getSessionStorage returns null gracefully
      const storage = getSessionStorage();
      expect(storage === null || typeof storage === "object").toBe(true);
    });
  });

  describe("keyboard shortcut matching", () => {
    it("restores the persisted hidden notice through the production handler", () => {
      const storage = memoryStorage();
      vi.stubGlobal("sessionStorage", storage);
      setNoticeDismissed(true, storage);
      const preventDefault = vi.fn();

      const handled = toggleDevNotice({
        key: "d",
        code: "KeyD",
        altKey: true,
        shiftKey: true,
        ctrlKey: false,
        metaKey: false,
        repeat: false,
        target: null,
        preventDefault,
      } as unknown as KeyboardEvent);

      expect(handled).toBe(true);
      expect(preventDefault).toHaveBeenCalledOnce();
      expect(storage.getItem(DEV_STAGING_NOTICE_STORAGE_KEY)).toBeNull();
    });

    it("recognizes Alt+Shift+D on Windows/Linux", () => {
      const event = {
        key: "d",
        code: "KeyD",
        altKey: true,
        shiftKey: true,
        ctrlKey: false,
        metaKey: false,
        repeat: false,
        target: null,
      } as unknown as KeyboardEvent;

      expect(isDevNoticeToggleShortcut(event)).toBe(true);
    });

    it("recognizes uppercase D with Alt+Shift", () => {
      const event = {
        key: "D",
        code: "KeyD",
        altKey: true,
        shiftKey: true,
        ctrlKey: false,
        metaKey: false,
        repeat: false,
        target: null,
      } as unknown as KeyboardEvent;

      expect(isDevNoticeToggleShortcut(event)).toBe(true);
    });

    it("recognizes Option+Shift+D character mappings on macOS", () => {
      const eventMac1 = {
        key: "Î",
        code: "KeyD",
        altKey: true,
        shiftKey: true,
        ctrlKey: false,
        metaKey: false,
        repeat: false,
        target: null,
      } as unknown as KeyboardEvent;

      expect(isDevNoticeToggleShortcut(eventMac1)).toBe(true);

      const eventMac2 = {
        key: "∂",
        code: "KeyD",
        altKey: true,
        shiftKey: true,
        ctrlKey: false,
        metaKey: false,
        repeat: false,
        target: null,
      } as unknown as KeyboardEvent;

      expect(isDevNoticeToggleShortcut(eventMac2)).toBe(true);
    });

    it("ignores repeating keydown events", () => {
      const event = {
        key: "d",
        code: "KeyD",
        altKey: true,
        shiftKey: true,
        ctrlKey: false,
        metaKey: false,
        repeat: true,
        target: null,
      } as unknown as KeyboardEvent;

      expect(isDevNoticeToggleShortcut(event)).toBe(false);
    });

    it("ignores keydown events when focus is inside editable targets", () => {
      const inputTarget = {
        tagName: "INPUT",
        isContentEditable: false,
        getAttribute: () => null,
      } as unknown as HTMLElement;

      const textareaTarget = {
        tagName: "TEXTAREA",
        isContentEditable: false,
        getAttribute: () => null,
      } as unknown as HTMLElement;

      const selectTarget = {
        tagName: "SELECT",
        isContentEditable: false,
        getAttribute: () => null,
      } as unknown as HTMLElement;

      const contentEditableTarget = {
        tagName: "DIV",
        isContentEditable: true,
        getAttribute: () => null,
      } as unknown as HTMLElement;

      const roleTextboxTarget = {
        tagName: "DIV",
        isContentEditable: false,
        getAttribute: (attr: string) => (attr === "role" ? "textbox" : null),
      } as unknown as HTMLElement;

      for (const target of [
        inputTarget,
        textareaTarget,
        selectTarget,
        contentEditableTarget,
        roleTextboxTarget,
      ]) {
        const event = {
          key: "d",
          code: "KeyD",
          altKey: true,
          shiftKey: true,
          ctrlKey: false,
          metaKey: false,
          repeat: false,
          target,
        } as unknown as KeyboardEvent;

        expect(isDevNoticeToggleShortcut(event)).toBe(false);
      }
    });

    it("allows non-editable elements like buttons or summary", () => {
      const buttonTarget = {
        tagName: "BUTTON",
        isContentEditable: false,
        getAttribute: () => null,
      } as unknown as HTMLElement;

      const summaryTarget = {
        tagName: "SUMMARY",
        isContentEditable: false,
        getAttribute: () => null,
      } as unknown as HTMLElement;

      for (const target of [buttonTarget, summaryTarget]) {
        const event = {
          key: "d",
          code: "KeyD",
          altKey: true,
          shiftKey: true,
          ctrlKey: false,
          metaKey: false,
          repeat: false,
          target,
        } as unknown as KeyboardEvent;

        expect(isDevNoticeToggleShortcut(event)).toBe(true);
      }
    });

    it("ignores incomplete or conflicting modifier combinations", () => {
      // Missing shift
      expect(
        isDevNoticeToggleShortcut({
          key: "d",
          code: "KeyD",
          altKey: true,
          shiftKey: false,
          ctrlKey: false,
          metaKey: false,
          repeat: false,
          target: null,
        } as unknown as KeyboardEvent),
      ).toBe(false);

      // Missing alt
      expect(
        isDevNoticeToggleShortcut({
          key: "d",
          code: "KeyD",
          altKey: false,
          shiftKey: true,
          ctrlKey: false,
          metaKey: false,
          repeat: false,
          target: null,
        } as unknown as KeyboardEvent),
      ).toBe(false);

      // Conflicting Ctrl
      expect(
        isDevNoticeToggleShortcut({
          key: "d",
          code: "KeyD",
          altKey: true,
          shiftKey: true,
          ctrlKey: true,
          metaKey: false,
          repeat: false,
          target: null,
        } as unknown as KeyboardEvent),
      ).toBe(false);

      // Conflicting Meta (Cmd)
      expect(
        isDevNoticeToggleShortcut({
          key: "d",
          code: "KeyD",
          altKey: true,
          shiftKey: true,
          ctrlKey: false,
          metaKey: true,
          repeat: false,
          target: null,
        } as unknown as KeyboardEvent),
      ).toBe(false);

      // Different key
      expect(
        isDevNoticeToggleShortcut({
          key: "k",
          code: "KeyK",
          altKey: true,
          shiftKey: true,
          ctrlKey: false,
          metaKey: false,
          repeat: false,
          target: null,
        } as unknown as KeyboardEvent),
      ).toBe(false);
    });
  });

  describe("isEditableTarget helper", () => {
    it("returns false for null or undefined target", () => {
      expect(isEditableTarget(null)).toBe(false);
      expect(isEditableTarget(undefined as unknown as EventTarget)).toBe(false);
    });

    it("returns true for various editable input elements", () => {
      expect(
        isEditableTarget({
          tagName: "INPUT",
          isContentEditable: false,
          getAttribute: () => null,
        } as unknown as HTMLElement),
      ).toBe(true);

      expect(
        isEditableTarget({
          tagName: "input",
          isContentEditable: false,
          getAttribute: () => null,
        } as unknown as HTMLElement),
      ).toBe(true);

      expect(
        isEditableTarget({
          tagName: "TEXTAREA",
          isContentEditable: false,
          getAttribute: () => null,
        } as unknown as HTMLElement),
      ).toBe(true);

      expect(
        isEditableTarget({
          tagName: "SELECT",
          isContentEditable: false,
          getAttribute: () => null,
        } as unknown as HTMLElement),
      ).toBe(true);
    });
  });
});
