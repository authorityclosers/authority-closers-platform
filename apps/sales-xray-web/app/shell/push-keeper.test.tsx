import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  forgetSentPushAddresses,
  keepPushAddress,
  PushKeeper,
} from "./push-keeper";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const phone = vi.hoisted(() => ({
  inApp: true,
  status: {
    supported: true,
    allowed: true,
    token: "fictional-phone-address-0001" as string | null,
  },
  enable: vi.fn(),
}));
const server = vi.hoisted(() => ({
  config: {
    enabled: true,
    project_id: "fictional-project",
    app_id: "1:000:android:fictional",
    api_key: "fictional-client-key",
    sender_id: "000",
  } as Record<string, unknown>,
  register: vi.fn(),
}));

vi.mock("../leads/native-phone", () => ({
  inPhoneApp: () => phone.inApp,
  pushStatus: async () => (phone.inApp ? phone.status : null),
  pushEnable: async (config: unknown) => {
    phone.enable(config);
    return { ...phone.status, token: "fictional-phone-address-0002" };
  },
  phoneStatus: async () => ({ version: "1.0.test" }),
}));
vi.mock("../leads/leads-client", () => ({
  readPushConfig: async () => server.config,
  registerDevice: async (token: string, version?: string) => {
    server.register(token, version);
    return { registered: true };
  },
}));

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  forgetSentPushAddresses();
  phone.inApp = true;
  phone.status = {
    supported: true,
    allowed: true,
    token: "fictional-phone-address-0001",
  };
  phone.enable.mockReset();
  server.register.mockReset();
  server.config = { ...server.config, enabled: true };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function settle() {
  await act(async () => {
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
  });
}

it("sends the address once the app starts signed in, with no ask", async () => {
  act(() => root.render(<PushKeeper accountKey="person:tenant-a" />));
  await settle();
  expect(server.register).toHaveBeenCalledWith(
    "fictional-phone-address-0001",
    "1.0.test",
  );
  expect(phone.enable).not.toHaveBeenCalled();
});

it("sends again when the app comes back with a renewed address, not otherwise", async () => {
  act(() => root.render(<PushKeeper accountKey="person:tenant-a" />));
  await settle();
  document.dispatchEvent(new Event("visibilitychange"));
  await settle();
  expect(server.register).toHaveBeenCalledTimes(1);
  phone.status = { ...phone.status, token: "fictional-phone-address-0003" };
  document.dispatchEvent(new Event("visibilitychange"));
  await settle();
  expect(server.register).toHaveBeenLastCalledWith(
    "fictional-phone-address-0003",
    "1.0.test",
  );
});

it("starts Firebase for an allowed phone with no address yet", async () => {
  phone.status = { ...phone.status, token: null };
  expect(await keepPushAddress("person:tenant-b")).toBe("sent");
  expect(phone.enable).toHaveBeenCalledOnce();
  expect(server.register).toHaveBeenCalledWith(
    "fictional-phone-address-0002",
    "1.0.test",
  );
});

it("each workspace gets the address", async () => {
  expect(await keepPushAddress("person:tenant-a")).toBe("sent");
  expect(await keepPushAddress("person:tenant-a")).toBe("same");
  expect(await keepPushAddress("person:tenant-b")).toBe("sent");
});

it("never asks or sends where notifications aren't allowed, or outside the app", async () => {
  phone.status = { supported: true, allowed: false, token: null };
  expect(await keepPushAddress("person:tenant-a")).toBe("off");
  expect(phone.enable).not.toHaveBeenCalled();
  phone.inApp = false;
  expect(await keepPushAddress("person:tenant-a")).toBe("none");
  server.config = { ...server.config, enabled: false };
  phone.inApp = true;
  phone.status = { supported: true, allowed: true, token: "x" };
  expect(await keepPushAddress("person:tenant-a")).toBe("off");
  expect(server.register).not.toHaveBeenCalled();
});

it("waits for sign-in", async () => {
  act(() => root.render(<PushKeeper accountKey={null} />));
  await settle();
  expect(server.register).not.toHaveBeenCalled();
});
