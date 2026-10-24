import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const play = vi.hoisted(() => ({ link: null as string | null }));
const notices = vi.hoisted(() => ({ list: [] as unknown[] }));
vi.mock("./play", async (load) => ({
  ...(await load<typeof import("./play")>()),
  usePlayLink: () => play.link,
}));
vi.mock("../notice-center", () => ({
  notify: (notice: unknown) => notices.list.push(notice),
}));

const { onPlayTesterList, PLAY_OPT_IN_URL } = await import("./play");
const { PlayMoveCard, PLAY_MOVE_SEEN } = await import("./play-move-card");
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

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  localStorage.clear();
  notices.list = [];
  play.link = PLAY_OPT_IN_URL;
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("offers Play's opt-in only to accounts on its tester list", () => {
  expect(onPlayTesterList("asha@authorityclosers.com")).toBe(true);
  expect(onPlayTesterList("Asha@AuthorityClosers.com")).toBe(true);
  expect(onPlayTesterList("buyer@example.com")).toBe(false);
  expect(onPlayTesterList(null)).toBe(false);
});

it("leads the apps page with Google Play, the file behind its question", async () => {
  await act(async () => root.render(<AppsView android={UNKNOWN_RELEASE} />));
  const first = host.querySelector("a[href^='https://']");
  expect(first?.getAttribute("href")).toBe(PLAY_OPT_IN_URL);
  expect(first?.textContent).toContain("Get it on Google Play");
  const fallback = [...host.querySelectorAll("details")].find(
    (details) =>
      details.querySelector(":scope > summary")?.textContent ===
      "No Play Store on this phone?",
  );
  expect(
    fallback?.querySelector(`a[href="${ANDROID_APK_URL}"]`)?.textContent,
  ).toContain("Download for Android");

  // Where Play can't serve the account yet, the file stays the way in.
  play.link = null;
  await act(async () =>
    root.render(<AppsView key="file" android={UNKNOWN_RELEASE} />),
  );
  expect(host.textContent).not.toContain("Google Play");
  expect(host.querySelector("a[href^='https://']")?.getAttribute("href")).toBe(
    ANDROID_APK_URL,
  );
});

it("leads the Get the app dialog with Google Play too", () => {
  const html = renderToStaticMarkup(
    <PhoneAppDialog open onClose={() => undefined} />,
  );
  expect(html).toContain(`href="${PLAY_OPT_IN_URL}"`);
  expect(html.indexOf(PLAY_OPT_IN_URL)).toBeLessThan(html.indexOf(ANDROID_APP));
  expect(html).toContain("No Play Store on this phone?");
});

it("tells the download-link app once that Sales X-Ray is on Google Play", async () => {
  fakePhone({ platform: "android", store: "direct" });
  await act(async () => root.render(<PlayMoveCard />));
  await settle();
  expect(notices.list).toHaveLength(1);
  const card = notices.list[0] as {
    title: string;
    message: string;
    action: { label: string };
    onDismiss: () => Promise<void>;
  };
  expect(card.title).toBe("Sales X-Ray is now on Google Play");
  expect(card.message).toContain("analyse any conversation you recorded");
  expect(card.action.label).toBe("Open Google Play");
  await card.onDismiss();
  expect(localStorage.getItem(PLAY_MOVE_SEEN)).not.toBeNull();

  // Dismissed once: never again on this phone.
  await act(async () => root.unmount());
  root = createRoot(host);
  await act(async () => root.render(<PlayMoveCard />));
  await settle();
  expect(notices.list).toHaveLength(1);
});

it("counts an app that doesn't say its store as the download-link app", async () => {
  fakePhone({ platform: "android" });
  await act(async () => root.render(<PlayMoveCard />));
  await settle();
  expect(notices.list).toHaveLength(1);
});

it("says nothing in the Play app, in a browser, or to accounts Play can't serve yet", async () => {
  fakePhone({ platform: "android", store: "play" });
  await act(async () => root.render(<PlayMoveCard />));
  await settle();
  vi.unstubAllGlobals();
  await act(async () => root.render(<PlayMoveCard key="browser" />));
  await settle();
  fakePhone({ platform: "android", store: "direct" });
  play.link = null;
  await act(async () => root.render(<PlayMoveCard key="not-a-tester" />));
  await settle();
  expect(notices.list).toEqual([]);
});
