import { beforeEach, describe, expect, it, vi } from "vitest";

const phone = vi.hoisted(() => ({
  autoCaptureStatus: vi.fn(),
  autoCaptureSetup: vi.fn(),
}));
vi.mock("../leads/native-phone", () => phone);

import { resumeAfterAgreeing } from "./resume-after-agreeing";

describe("resumeAfterAgreeing (16 Nov terms change stopped every phone)", () => {
  beforeEach(() => {
    phone.autoCaptureStatus.mockReset();
    phone.autoCaptureSetup.mockReset().mockResolvedValue(undefined);
  });

  it.each(["consent", "terms"])(
    "turns this phone's uploads back on when %s stopped them, keeping its network choice",
    async (health) => {
      phone.autoCaptureStatus.mockResolvedValue({
        supported: true,
        on: false,
        health,
        wifiOnly: true,
      });
      await resumeAfterAgreeing();
      expect(phone.autoCaptureSetup).toHaveBeenCalledWith(true, true);
    },
  );

  it("leaves uploads the seller turned off themselves", async () => {
    phone.autoCaptureStatus.mockResolvedValue({
      supported: true,
      on: false,
      health: "off",
      wifiOnly: false,
    });
    await resumeAfterAgreeing();
    expect(phone.autoCaptureSetup).not.toHaveBeenCalled();
  });

  it("does nothing when uploads are on, in a browser, or on an app that can't say", async () => {
    for (const status of [
      { supported: true, on: true, health: "ok" },
      { supported: false, on: false },
      null,
    ]) {
      phone.autoCaptureStatus.mockResolvedValue(status);
      await resumeAfterAgreeing();
    }
    expect(phone.autoCaptureSetup).not.toHaveBeenCalled();
  });

  it("a refused Turn on (Not now) is not an error", async () => {
    phone.autoCaptureStatus.mockResolvedValue({
      supported: true,
      on: false,
      health: "consent",
      wifiOnly: false,
    });
    phone.autoCaptureSetup.mockRejectedValue(new Error("declined"));
    await expect(resumeAfterAgreeing()).resolves.toBeUndefined();
  });
});
