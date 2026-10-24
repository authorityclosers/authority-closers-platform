import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notices = vi.hoisted(() => ({ list: [] as unknown[] }));
vi.mock("../notice-center", () => ({
  notify: (notice: unknown) => notices.list.push(notice),
}));

const { PLAY, PLAY_OPT_IN_URL, playWords } = await import("./play");
const { PlayMoveCard, PLAY_MOVE_AGAIN_MS, PLAY_MOVE_SEEN } = await import(
  "./play-move-card"
);
const { AppsView } = await import("./apps-view");
const { ANDROID_APK_URL, UNKNOWN_RELEASE } = await import("./release");
const { ANDROID_APP, PhoneAppDialog } = await import("../leads/phone-app");

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

type Listener = (event: { data: unknown }) => void;

function fakePhone(status: Record<string, unknown>) {
  const listeners: Listener[] = [];
  vi.stubGlobal("SXPhone", {
    addEventListener: (_: string, listener: Listener) =>
      listeners.push(listener),
    postMessage: (data: string) => {
      const message = JSON.parse(data) as { id: string };
      queueMicrotask(() =>
        listeners.forEach((listener) =>
          listener({
            data: JSON.stringify({ id: message.id, ok: true, result: status }),
          }),
        ),
      );
    },
  });
}

let root: Root;
let host: HTMLDivElement;
const settle = async () => {
  for (let i = 0; i < 8; i++) await act(async () => await Promise.resolve());
};
const render = async (key: string) => {
  await act(async () => root.render(<PlayMoveCard key={key} />));
  await settle();
};

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  localStorage.clear();
  notices.list = [];
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("speaks to Play's testers until the store page is set, then to everyone", () => {
  expect(PLAY).toEqual(playWords(null));
  expect(PLAY.url).toBe(PLAY_OPT_IN_URL);
  expect(PLAY.get).toBe("Testers: install from Google Play");
  expect(PLAY.file).toBe("No Play invite? Download the app");
  const store = playWords("https://play.google.com/store/apps/details?id=x");
  expect(store.url).toBe("https://play.google.com/store/apps/details?id=x");
  expect(store.get).toBe("Get it on Google Play");
  expect(store.cardTitle).toBe("Sales X-Ray is now on Google Play");
});

it("leads the apps page with Google Play, the file under it", async () => {
  await act(async () => root.render(<AppsView android={UNKNOWN_RELEASE} />));
  const first = host.querySelector("a[href^='https://']");
  expect(first?.getAttribute("href")).toBe(PLAY_OPT_IN_URL);
  expect(first?.textContent).toContain("Testers: install from Google Play");
  const file = [...host.querySelectorAll("details")].find(
    (details) =>
      details.querySelector(":scope > summary")?.textContent ===
      "No Play invite? Download the app",
  );
  expect(
    file?.querySelector(`a[href="${ANDROID_APK_URL}"]`)?.textContent,
  ).toContain("Download for Android");
});

it("leads the Get the app dialog with Google Play too", () => {
  const html = renderToStaticMarkup(
    <PhoneAppDialog open onClose={() => undefined} />,
  );
  expect(html).toContain(`href="${PLAY_OPT_IN_URL}"`);
  expect(html.indexOf(PLAY_OPT_IN_URL)).toBeLessThan(html.indexOf(ANDROID_APP));
  expect(html).toContain("No Play invite? Download the app");
});

it("tells everyone on the download-link app, and Later hides it for a week", async () => {
  fakePhone({ platform: "android", store: "direct" });
  await render("first");
  expect(notices.list).toHaveLength(1);
  const card = notices.list[0] as {
    title: string;
    message: string;
    action: { label: string };
    dismissLabel: string;
    onDismiss: () => Promise<void>;
  };
  expect(card.title).toBe("Sales X-Ray is moving to Google Play");
  expect(card.message).toContain("Got a Play testing invite? Switch now");
  expect(card.message).toContain(
    "Before you uninstall, open Calls and make sure every recording shows as sent.",
  );
  expect(card.message).toContain("No invite yet? Keep using this app");
  expect(card.action.label).toBe("Switch to Play");
  expect(card.dismissLabel).toBe("Later");
  await card.onDismiss();
  expect(localStorage.getItem(PLAY_MOVE_SEEN)).not.toBeNull();

  await render("same-week");
  expect(notices.list).toHaveLength(1);

  localStorage.setItem(
    PLAY_MOVE_SEEN,
    new Date(Date.now() - PLAY_MOVE_AGAIN_MS - 60_000).toISOString(),
  );
  await render("a-week-later");
  expect(notices.list).toHaveLength(2);
});

it("counts an app that doesn't say its store as the download-link app", async () => {
  fakePhone({ platform: "android" });
  await render("old-build");
  expect(notices.list).toHaveLength(1);
});

it("says nothing in the Play app or in a browser", async () => {
  fakePhone({ platform: "android", store: "play" });
  await render("play");
  vi.unstubAllGlobals();
  await render("browser");
  expect(notices.list).toEqual([]);
});
