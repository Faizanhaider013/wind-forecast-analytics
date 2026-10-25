import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, getJson } from "../api/client";

function mockFetch(impl: () => Promise<Response> | Response) {
  vi.stubGlobal("fetch", vi.fn(impl));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getJson", () => {
  it("returns parsed JSON on success", async () => {
    mockFetch(() => new Response(JSON.stringify({ ok: 1 }), { status: 200 }));
    const data = await getJson<{ ok: number }>("/x");
    expect(data.ok).toBe(1);
  });

  it("throws ApiError with the backend detail on a 4xx", async () => {
    mockFetch(
      () =>
        new Response(JSON.stringify({ detail: "invalid delivery_date" }), {
          status: 400,
        }),
    );
    await expect(getJson("/x")).rejects.toMatchObject({
      status: 400,
      message: "invalid delivery_date",
    });
  });

  it("throws ApiError(0) when the network is unreachable", async () => {
    mockFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    const err = await getJson("/x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
  });

  it("throws ApiError on malformed JSON", async () => {
    mockFetch(() => new Response("not json{", { status: 200 }));
    await expect(getJson("/x")).rejects.toBeInstanceOf(ApiError);
  });

  it("falls back to a generic message on a non-2xx with a non-JSON body", async () => {
    // A reverse proxy (e.g. Nginx) returns an HTML 502/504, not JSON `detail`.
    mockFetch(
      () =>
        new Response("<html>502 Bad Gateway</html>", {
          status: 502,
          headers: { "Content-Type": "text/html" },
        }),
    );
    const err = await getJson("/x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(502);
    expect(err.message).toBe("Request failed with HTTP 502");
  });
});
