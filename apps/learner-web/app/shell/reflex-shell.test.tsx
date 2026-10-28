// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({
  pathname: "/home",
  prefetch: vi.fn(),
  tick: vi.fn(),
  account: {
    me: { display_name: "Test Learner", email: "learner@example.test" },
    workspaceName: "Example Workspace",
    avatarUrl: null,
  },
}));
vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useRouter: () => ({ prefetch: mocks.prefetch }),
}));
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children?: import("react").ReactNode;
    [prop: string]: unknown;
  }) => {
    const anchor = { ...props };
    delete anchor.prefetch;
    delete anchor.onNavigate;
    return (
      <a href={href} {...anchor}>
        {children}
      </a>
    );
  },
}));
vi.mock("./account-store", async (original) => ({
  ...(await original<object>()),
  useAccountStore: () => mocks.account,
}));
vi.mock("@ac/ui/kit/haptics", () => ({ tick: mocks.tick }));
import { ReflexShell } from "./reflex-shell";
import { ScreenTitle } from "./screen-title";
import { salesXrayForHost } from "./places";
(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement, root: Root;
// happy-dom's own handle on the window, for setting the page address.
const setUrl = (url: string) =>
  (
    window as unknown as { happyDOM: { setURL(url: string): void } }
  ).happyDOM.setURL(url);
beforeEach(() => {
  mocks.pathname = "/home";
  mocks.prefetch.mockClear();
  mocks.tick.mockClear();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: () => ({
      matches: false,
      addEventListener() {},
      removeEventListener() {},
    }),
  });
  setUrl("https://learner.authorityclosers.com/home");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
async function mount(practiceEnabled = true, children = <p>Screen content</p>) {
  await act(async () =>
    root.render(
      <ReflexShell practiceEnabled={practiceEnabled}>{children}</ReflexShell>,
    ),
  );
}
const phone = () => host.querySelector('nav[aria-label="Phone places"]')!;
it("offers exactly Today, Learn, Practice and Me with their routes, without More or the embedded studio", async () => {
  await mount();
  expect(
    [...phone().querySelectorAll("a")].map((a) => [
      a.textContent,
      a.getAttribute("href"),
    ]),
  ).toEqual([
    ["Today", "/home"],
    ["Learn", "/learning"],
    ["Practice", "/practice"],
    ["Me", "/profile"],
  ]);
  expect(host.querySelector('a[href="/sales-xray"]')).toBeNull();
  expect(phone().textContent).not.toContain("More");
});
it("hides Practice when the server's existing gate is disabled", async () => {
  await mount(false);
  expect(host.querySelector('a[href="/practice"]')).toBeNull();
  expect(phone().querySelectorAll("a")).toHaveLength(3);
});
it.each([
  ["/learn/course/module/one", "/learning"],
  ["/activity/one", "/learning"],
  ["/learning/saved", "/learning"],
  ["/practice/round", "/practice"],
  ...[
    "progress",
    "settings",
    "certificates/one",
    "notifications",
    "calendar",
    "leaderboard",
    "profile/details",
  ].map((path) => [`/${path}`, "/profile"]),
])("selects the right place for nested %s", async (path, selected) => {
  mocks.pathname = path;
  await mount();
  expect(
    phone().querySelector('[aria-current="page"]')?.getAttribute("href"),
  ).toBe(selected);
  expect(phone().querySelectorAll('[aria-current="page"]')).toHaveLength(1);
});
it("reads a page's declared title into the top bar", async () => {
  await mount(true, <ScreenTitle title="Your next lesson" />);
  expect(host.querySelector("header h1")?.textContent).toBe("Your next lesson");
});
it("opens the shared Account sheet with identity, workspace, account rows and today's sign-out control", async () => {
  await mount();
  expect(host.querySelector("dialog")?.open).toBe(false);
  await act(async () =>
    (
      host.querySelector(
        'button[aria-label="Open Account"]',
      ) as HTMLButtonElement
    ).click(),
  );
  const sheet = host.querySelector("dialog")!;
  expect(sheet.open).toBe(true);
  expect(sheet.textContent).toContain("Test Learner");
  expect(sheet.textContent).toContain("learner@example.test");
  expect(sheet.textContent).toContain("Example Workspace");
  expect(
    [...sheet.querySelectorAll("nav a")].map((a) => a.textContent),
  ).toEqual([
    "Progress",
    "Calendar",
    "Notifications",
    "Settings",
    "Help",
    "Open Sales X-Ray",
  ]);
  expect(sheet.textContent).toContain("Sign out");
  expect(sheet.textContent).not.toContain("Certificates");
  expect(
    sheet.querySelector('a[href^="mailto:"]')?.getAttribute("href"),
  ).toContain("Learner%20Support");
  expect(sheet.querySelector('a[target="_blank"]')?.getAttribute("href")).toBe(
    "https://salesxray.authorityclosers.com",
  );
});
it.each([
  ["learner.authorityclosers.com", "https://salesxray.authorityclosers.com"],
  [
    "learner-staging.authorityclosers.com",
    "https://salesxray-staging.authorityclosers.com",
  ],
  ["localhost", null],
  ["constructor", null],
  ["learner.authorityclosers.com.attacker.test", null],
])(
  "shows the external studio only for known host %s",
  async (hostname, expected) => {
    setUrl(`https://${hostname}/home`);
    await mount();
    await act(async () =>
      (
        host.querySelector(
          'button[aria-label="Open Account"]',
        ) as HTMLButtonElement
      ).click(),
    );
    const studio = [...host.querySelectorAll("dialog a")].find(
      (a) => a.textContent === "Open Sales X-Ray",
    );
    expect(studio?.getAttribute("href") ?? null).toBe(expected);
    expect(salesXrayForHost(hostname)).toBe(expected);
  },
);
it("prefetches on press, shows the destination outline immediately, and gives content back on cancellation", async () => {
  await mount();
  const link = phone().querySelector('a[href="/learning"]')!;
  await act(async () =>
    link.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, button: 0 }),
    ),
  );
  expect(mocks.prefetch).toHaveBeenCalledWith("/learning");
  expect(mocks.tick).toHaveBeenCalled();
  expect(host.querySelector('[aria-label="Loading your page"]')).not.toBeNull();
  expect(
    phone().querySelector('[aria-current="page"]')?.getAttribute("href"),
  ).toBe("/learning");
  await act(async () =>
    link.dispatchEvent(new PointerEvent("pointercancel", { bubbles: true })),
  );
  expect(host.querySelector('[aria-label="Loading your page"]')).toBeNull();
});
it("does not intercept modified presses and removes the outline when the route arrives", async () => {
  await mount();
  const link = phone().querySelector('a[href="/learning"]')!;
  await act(async () =>
    link.dispatchEvent(
      new PointerEvent("pointerdown", {
        bubbles: true,
        button: 0,
        ctrlKey: true,
      }),
    ),
  );
  expect(mocks.prefetch).not.toHaveBeenCalled();
  await act(async () =>
    link.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, button: 0 }),
    ),
  );
  mocks.pathname = "/learning";
  await mount();
  expect(host.querySelector('[aria-label="Loading your page"]')).toBeNull();
});
it("closes Account with the kit's close control", async () => {
  await mount();
  await act(async () =>
    (
      host.querySelector(
        'button[aria-label="Open Account"]',
      ) as HTMLButtonElement
    ).click(),
  );
  const dialog = host.querySelector("dialog")!;
  await act(async () =>
    (
      dialog.querySelector('button[aria-label="Close"]') as HTMLButtonElement
    ).click(),
  );
  expect(
    host
      .querySelector('button[aria-label="Open Account"]')
      ?.getAttribute("aria-expanded"),
  ).toBe("false");
});
