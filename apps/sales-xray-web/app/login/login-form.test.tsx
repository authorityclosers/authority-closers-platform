// @vitest-environment happy-dom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { LoginForm, learnerAuthLinksForHost } from "./login-form";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

let root: Root;
let container: HTMLDivElement;
let fetchMock: ReturnType<typeof vi.fn>;
let navigate: ReturnType<typeof vi.spyOn>;

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function mount() {
  await act(async () => root.render(<LoginForm />));
  await flush();
}

async function submit(
  email = "learner@example.test",
  password = "synthetic-password",
) {
  const emailInput = container.querySelector<HTMLInputElement>(
    'input[name="email"]',
  );
  const passwordInput = container.querySelector<HTMLInputElement>(
    'input[name="password"]',
  );
  if (!emailInput || !passwordInput) throw new Error("Missing login fields");
  emailInput.value = email;
  passwordInput.value = password;
  await act(async () => {
    container
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  navigate = vi.spyOn(window.location, "assign").mockImplementation(() => {});
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("keeps canonical learner links bound to the two owned source hosts", () => {
  expect(
    learnerAuthLinksForHost("salesxray-staging.authorityclosers.com"),
  ).toEqual({
    registerHref: "https://learner-staging.authorityclosers.com/register",
    forgotPasswordHref:
      "https://learner-staging.authorityclosers.com/forgot-password",
  });
  expect(learnerAuthLinksForHost("salesxray.authorityclosers.com")).toEqual({
    registerHref: "https://learner.authorityclosers.com/register",
    forgotPasswordHref: "https://learner.authorityclosers.com/forgot-password",
  });
  expect(learnerAuthLinksForHost("localhost")).toEqual({
    registerHref: null,
    forgotPasswordHref: null,
  });
  expect(learnerAuthLinksForHost("untrusted.example")).toEqual({
    registerHref: null,
    forgotPasswordHref: null,
  });
});

it("posts only email and password with same-origin credentials, then opens home", async () => {
  fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
  await mount();
  expect(container.querySelector("a")?.getAttribute("href")).toBe("/");
  expect(
    container
      .querySelector<HTMLAnchorElement>('a[href^="/v1/auth/google/start"]')
      ?.getAttribute("href"),
  ).toBe(
    "/v1/auth/google/start?action=authenticate&surface=sales_xray&return_path=%2F",
  );

  await submit(" learner@example.test ", "synthetic-password");
  await flush();

  expect(fetchMock).toHaveBeenCalledOnce();
  const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(path).toBe("/v1/auth/password/login");
  expect(init.method).toBe("POST");
  expect(init.credentials).toBe("same-origin");
  expect(init.redirect).toBe("error");
  expect(JSON.parse(String(init.body))).toEqual({
    email: "learner@example.test",
    password: "synthetic-password",
  });
  expect(Object.keys(JSON.parse(String(init.body)))).toEqual([
    "email",
    "password",
  ]);
  expect(navigate).toHaveBeenCalledWith("/");
  expect(
    container.querySelector<HTMLInputElement>('input[name="password"]')?.value,
  ).toBe("");
});

it("shows a friendly existence-neutral error and clears the password after rejection", async () => {
  fetchMock.mockResolvedValue(
    new Response(
      JSON.stringify({ detail: "synthetic server credential detail" }),
      {
        status: 401,
        headers: { "content-type": "application/json" },
      },
    ),
  );
  await mount();
  await submit();
  await flush();

  const alert = container.querySelector('[role="alert"]');
  expect(alert?.textContent).toContain("We couldn’t sign you in");
  expect(alert?.textContent).not.toContain(
    "synthetic server credential detail",
  );
  expect(container.innerHTML).not.toContain("synthetic-password");
  expect(
    container.querySelector<HTMLButtonElement>('button[type="submit"]')
      ?.disabled,
  ).toBe(false);
  expect(navigate).not.toHaveBeenCalled();
});

it("disables and deduplicates the submit while login is pending", async () => {
  const request = deferred<Response>();
  fetchMock.mockReturnValue(request.promise);
  await mount();
  await submit();
  expect(
    container.querySelector<HTMLButtonElement>('button[type="submit"]')
      ?.disabled,
  ).toBe(true);
  expect(
    container.querySelector<HTMLFormElement>("form")?.getAttribute("aria-busy"),
  ).toBe("true");

  await submit("second@example.test", "second-password");
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(navigate).not.toHaveBeenCalled();

  await act(async () => request.resolve(new Response("{}", { status: 200 })));
  await flush();
  expect(navigate).toHaveBeenCalledOnce();
  expect(
    container.querySelector<HTMLButtonElement>('button[type="submit"]')
      ?.disabled,
  ).toBe(false);
});

it("submits successfully after React StrictMode replays the lifecycle effect", async () => {
  fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
  await act(async () =>
    root.render(
      <StrictMode>
        <LoginForm />
      </StrictMode>,
    ),
  );
  await flush();
  await submit();
  await flush();

  expect(fetchMock).toHaveBeenCalledOnce();
  expect(navigate).toHaveBeenCalledWith("/");
});
