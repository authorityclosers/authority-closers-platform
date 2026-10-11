import { afterEach, expect, it, vi } from "vitest";
import { readCompanies, readCompany } from "./prospect-company-client";
import {
  companyBinding,
  companyId,
  fictionalCompaniesPage,
  fictionalCompanyPayload,
} from "./prospect-company.fixture";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
const detail = () => ({
  schema: "ac.sales-xray.company/1",
  person_id: companyBinding.personId,
  tenant_id: companyBinding.tenantId,
  session_id: companyBinding.sessionId,
  company: fictionalCompanyPayload(),
});

it("returns a source/scope-checked server preload with no browser read", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  const reader = vi.fn().mockResolvedValue(fictionalCompaniesPage());
  const result = await readCompanies(companyBinding, { reader });
  expect(result.status).toBe("ready");
  expect(reader.mock.calls[0][0]).toBe(
    "/v1/conversation/companies?limit=20&offset=0",
  );
  expect(fetcher).not.toHaveBeenCalled();
});

it("reads one exact Company identity, without a name lookup or write", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(detail()), { status: 200 }));
  vi.stubGlobal("fetch", fetcher);
  const result = await readCompany(companyBinding, companyId);
  expect(result.status).toBe("ready");
  expect(fetcher).toHaveBeenCalledWith(
    `/v1/conversation/companies/${companyId}`,
    expect.objectContaining({
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    }),
  );
});

it.each(["person_id", "tenant_id", "session_id"])(
  "rejects a foreign %s without exposing the response",
  async (field) => {
    const result = await readCompanies(companyBinding, {
      reader: async () => ({ ...fictionalCompaniesPage(), [field]: companyId }),
    });
    expect(result).toEqual({
      status: "unavailable",
      message: "Companies are unavailable. Try again.",
    });
  },
);

it.each([401, 403, 404, 500])(
  "treats HTTP %s as unavailable, never a false empty list",
  async (status) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("private response", { status })),
    );
    expect(await readCompanies(companyBinding)).toEqual({
      status: "unavailable",
      message: "Companies are unavailable. Try again.",
    });
  },
);

it("rejects a different company in a successful detail response", async () => {
  expect(
    (
      await readCompany(companyBinding, companyId, {
        reader: async () => ({
          ...detail(),
          company: {
            ...fictionalCompanyPayload(),
            company_id: companyBinding.personId,
          },
        }),
      })
    ).status,
  ).toBe("unavailable");
});

it.each([
  { offset: -1 },
  { offset: 0.5 },
  { search: "x".repeat(161) },
  { deadlineMs: 0 },
  { deadlineMs: 15001 },
])("does not read for invalid query/deadline %j", async (options) => {
  const reader = vi.fn();
  expect(
    (await readCompanies(companyBinding, { ...options, reader })).status,
  ).toBe("unavailable");
  expect(reader).not.toHaveBeenCalled();
});

it("rejects an invalid actor or Company id before reading", async () => {
  const reader = vi.fn();
  expect(
    (await readCompanies({ ...companyBinding, tenantId: "no" }, { reader }))
      .status,
  ).toBe("unavailable");
  expect(
    (await readCompany(companyBinding, "../other", { reader })).status,
  ).toBe("unavailable");
  expect(reader).not.toHaveBeenCalled();
});

it("encodes human search without changing the endpoint", async () => {
  const reader = vi.fn().mockResolvedValue(fictionalCompaniesPage());
  await readCompanies(companyBinding, {
    search: "Fictional & ग्राहक",
    offset: 20,
    reader,
  });
  const url = new URL(reader.mock.calls[0][0], "https://example.invalid");
  expect(url.pathname).toBe("/v1/conversation/companies");
  expect(url.searchParams.get("search")).toBe("Fictional & ग्राहक");
  expect(url.searchParams.get("offset")).toBe("20");
});

it("pins actor/session input before an asynchronous read", async () => {
  const binding = { ...companyBinding };
  let finish!: (value: unknown) => void;
  const result = readCompanies(binding, {
    reader: () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  });
  await Promise.resolve();
  binding.sessionId = companyId;
  finish({ ...fictionalCompaniesPage(), session_id: companyId });
  expect((await result).status).toBe("unavailable");
});

it("cancels even a reader that ignores abort and never resolves", async () => {
  const controller = new AbortController();
  const result = readCompanies(companyBinding, {
    signal: controller.signal,
    reader: () => new Promise(() => {}),
  });
  controller.abort();
  expect((await result).status).toBe("unavailable");
});

it("bounds a stalled server preload and aborts the underlying reader", async () => {
  vi.useFakeTimers();
  let observed!: AbortSignal;
  const result = readCompanies(companyBinding, {
    reader: (_, signal) => {
      observed = signal;
      return new Promise(() => {});
    },
  });
  await vi.advanceTimersByTimeAsync(2500);
  expect((await result).status).toBe("unavailable");
  expect(observed.aborted).toBe(true);
});

it("does not read an already cancelled request", async () => {
  const controller = new AbortController();
  controller.abort();
  const reader = vi.fn();
  expect(
    (await readCompanies(companyBinding, { signal: controller.signal, reader }))
      .status,
  ).toBe("unavailable");
  expect(reader).not.toHaveBeenCalled();
});

it.each(["length", "stream"])(
  "bounds %s bytes before parsing a private body",
  async (kind) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("x".repeat(131073), {
          status: 200,
          headers: kind === "length" ? { "content-length": "131073" } : {},
        }),
      ),
    );
    expect((await readCompanies(companyBinding)).status).toBe("unavailable");
  },
);

it("hides transport errors, malformed JSON and redirects", async () => {
  for (const response of [
    () => Promise.reject(new Error("private detail")),
    () => Promise.resolve(new Response("not-json")),
    () => Promise.resolve(new Response(null, { status: 302 })),
  ]) {
    vi.stubGlobal("fetch", vi.fn(response));
    expect(await readCompanies(companyBinding)).toEqual({
      status: "unavailable",
      message: "Companies are unavailable. Try again.",
    });
  }
});

it("returns unavailable for a synchronous reader failure without an unhandled cancellation", async () => {
  expect(
    await readCompanies(companyBinding, {
      reader: () => {
        throw new Error("private detail");
      },
    }),
  ).toEqual({
    status: "unavailable",
    message: "Companies are unavailable. Try again.",
  });
});

it.each([0, 20])(
  "rejects a non-advancing page at offset %s",
  async (offset) => {
    expect(
      (
        await readCompanies(companyBinding, {
          offset,
          reader: async () => ({
            ...fictionalCompaniesPage(),
            next_offset: offset,
          }),
        })
      ).status,
    ).toBe("unavailable");
  },
);

it("rejects an empty page that promises more rows", async () => {
  expect(
    (
      await readCompanies(companyBinding, {
        reader: async () => ({
          ...fictionalCompaniesPage(),
          companies: [],
          total: 21,
          next_offset: 20,
        }),
      })
    ).status,
  ).toBe("unavailable");
});
