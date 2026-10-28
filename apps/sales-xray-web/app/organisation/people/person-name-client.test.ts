import { afterEach, expect, it, vi } from "vitest";
import { saveOwnDisplayName } from "./person-name-client";
afterEach(() => vi.unstubAllGlobals());
it("caps display names before writing and preserves the existing phone and revision", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          name: "Mira Example",
          email: "mira@example.test",
          phone_number_e164: null,
          phone_verified: false,
          profile_complete: false,
          revision: 7,
        }),
      ),
    )
    .mockResolvedValueOnce(new Response("{}"));
  vi.stubGlobal("fetch", fetch);
  await expect(saveOwnDisplayName("x".repeat(41))).rejects.toThrow("1–40");
  expect(fetch).not.toHaveBeenCalled();
  await saveOwnDisplayName("  Mira Fictional  ");
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({
    full_name: "Mira Fictional",
    phone_number_e164: null,
    expected_revision: 7,
  });
  expect(fetch.mock.calls[1][0]).toBe("/v1/me/sales-xray-profile");
});
