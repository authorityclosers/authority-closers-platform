import { describe, expect, it, vi } from "vitest";

import { fixtureOffer } from "./offer-fixture-data";
import { blankOffer, normalizeStudio, type Studio } from "./offer-model";
import { listShared, saveShared, sharedBody, versionOf } from "./offer-server";
import { openShared } from "./shared-panel";

const ID = "3f1c2a7e-9b4d-4c1e-8a2f-0d5e6f7a8b9c";

const reply = (status: number, body: unknown) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status }));

describe("reads", () => {
  it("keeps only well-formed versions", async () => {
    const fetcher = reply(200, {
      offers: [
        {
          offer_id: ID,
          version: 2,
          name: "A",
          author: "",
          created_at: "x",
          body: {},
        },
        { offer_id: "not-a-uuid", version: 1 },
        { offer_id: ID },
      ],
    });
    const result = await listShared(fetcher as unknown as typeof fetch);
    expect(result).toEqual({
      ok: true,
      data: [
        {
          offerId: ID,
          version: 2,
          name: "A",
          archived: false,
          author: null,
          createdAt: "x",
          body: {},
        },
      ],
    });
  });

  it("says why it failed without throwing", async () => {
    const missing = await versionOf(
      ID,
      1,
      reply(404, {}) as unknown as typeof fetch,
    );
    expect(missing).toMatchObject({ ok: false, status: 404 });
    const denied = await listShared(
      reply(403, {
        detail: "Use the AC operations workspace.",
      }) as unknown as typeof fetch,
    );
    expect(denied).toMatchObject({
      ok: false,
      message: "Use the AC operations workspace.",
    });
    const offline = await listShared(
      vi.fn(async () => {
        throw new TypeError("offline");
      }) as unknown as typeof fetch,
    );
    expect(offline).toMatchObject({ ok: false, status: 0 });
  });
});

describe("saves", () => {
  it("send the offer without its link, on top of the version it came from", async () => {
    vi.stubGlobal("window", {
      location: { origin: "https://admin-dev.example" },
    });
    const offer = { ...fixtureOffer(), shared: { id: ID, version: 4 } };
    const fetcher = reply(201, {
      offer_id: ID,
      version: 5,
      name: "n",
      created_at: "t",
    });
    const result = await saveShared(
      offer,
      ID,
      fetcher as unknown as typeof fetch,
    );
    expect(result).toMatchObject({ ok: true, data: { version: 5 } });
    const [path, init] = fetcher.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(path).toBe(`/v1/admin/offers/${ID}/versions`);
    const sent = JSON.parse(String(init.body));
    expect(sent.base_version).toBe(4);
    expect("shared" in sent.body).toBe(false);
    expect(sent.body.name).toBe(offer.name);
    expect(sharedBody(blankOffer())).not.toHaveProperty("shared");
    vi.unstubAllGlobals();
  });
});

describe("opening a shared version", () => {
  const shared = (version: number, name: string) => ({
    offerId: ID,
    version,
    name,
    archived: false,
    author: null,
    createdAt: "",
    body: { ...fixtureOffer(), id: "offer-remote", name },
  });

  it("adds it once, then replaces that copy; a restore opens on top of the newest", () => {
    const empty: Studio = normalizeStudio({ offers: [] });
    const once = openShared(empty, shared(2, "Two"));
    expect(once.offers).toHaveLength(1);
    expect(once.offers[0]?.shared).toEqual({ id: ID, version: 2 });
    expect(once.activeId).toBe(once.offers[0]?.id);

    const again = openShared(once, shared(3, "Three"));
    expect(again.offers).toHaveLength(1);
    expect(again.offers[0]).toMatchObject({
      name: "Three",
      shared: { version: 3 },
    });

    const restored = openShared(again, shared(1, "One"), 3);
    expect(restored.offers[0]).toMatchObject({
      name: "One",
      shared: { version: 3 },
    });
  });

  it("never takes the id of a different local offer", () => {
    const local = { ...blankOffer("Mine"), id: "offer-remote" };
    const studio: Studio = { version: 1, offers: [local], activeId: local.id };
    const opened = openShared(studio, shared(1, "Theirs"));
    expect(opened.offers).toHaveLength(2);
    expect(opened.offers[1]?.id).not.toBe("offer-remote");
    expect(opened.offers[0]?.name).toBe("Mine");
  });

  it("drops a malformed link on import", () => {
    const studio = normalizeStudio({
      offers: [
        { id: "a", shared: { id: ID, version: 2 } },
        { id: "b", shared: { id: "x", version: 2 } },
        { id: "c", shared: { id: ID, version: 0 } },
      ],
    });
    expect(studio.offers.map((o) => o.shared)).toEqual([
      { id: ID, version: 2 },
      null,
      null,
    ]);
  });
});
