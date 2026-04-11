/**
 * Tests for the /health Route Handler proxy.
 */

jest.mock("next/server", () => {
  class MockNextResponse {
    body: string;
    status: number;
    headers: Map<string, string>;

    constructor(body: string, init: { status: number; headers?: Record<string, string> }) {
      this.body = body;
      this.status = init.status;
      this.headers = new Map(Object.entries(init.headers ?? {}));
    }

    async json() {
      return JSON.parse(this.body);
    }

    static json(data: unknown, init?: { status?: number }) {
      return new MockNextResponse(JSON.stringify(data), {
        status: init?.status ?? 200,
        headers: { "content-type": "application/json" },
      });
    }
  }

  return { NextResponse: MockNextResponse };
});

import { GET } from "../route";

const mockFetch = jest.fn();
beforeEach(() => {
  mockFetch.mockReset();
  globalThis.fetch = mockFetch;
});

describe("GET /health (route handler proxy)", () => {
  it("forwards a healthy upstream response", async () => {
    const upstream = { status: "ok" };
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: () => Promise.resolve(JSON.stringify(upstream)),
      headers: new Headers({ "content-type": "application/json" }),
    });

    const res = await GET();
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.status).toBe("ok");
  });

  it("returns 502 when the backend is unreachable", async () => {
    mockFetch.mockRejectedValueOnce(new Error("ECONNREFUSED"));

    const res = await GET();
    expect(res.status).toBe(502);
    const body = await res.json();
    expect(body.status).toBe("proxy_error");
    expect(body.detail).toMatch(/Cannot reach API/);
  });
});
