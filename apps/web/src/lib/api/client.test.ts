import { beforeEach, describe, expect, it, vi } from "vitest";

const getSession = vi.fn();

vi.mock("@/lib/supabase/client", () => ({
  createBrowserSupabaseClient: () => ({ auth: { getSession } }),
}));

import { ApiClientError, apiFetch } from "./client";

function session(accessToken: string | null = "token-123") {
  getSession.mockResolvedValue({
    data: { session: accessToken ? { access_token: accessToken } : null },
    error: null,
  });
}

describe("apiFetch", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    getSession.mockReset();
    process.env.NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000/";
    session();
  });

  it("injects the current token and safely merges caller headers", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 }));

    await apiFetch("/api/v1/applications", {
      headers: { Authorization: "Bearer forged", "X-Request-ID": "request-1" },
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    const headers = new Headers(init?.headers);
    expect(url).toBe("http://localhost:8000/api/v1/applications");
    expect(headers.get("Authorization")).toBe("Bearer token-123");
    expect(headers.get("X-Request-ID")).toBe("request-1");
  });

  it("rejects a missing session before making a request", async () => {
    session(null);
    const fetchMock = vi.spyOn(globalThis, "fetch");

    await expect(apiFetch("/api/v1/applications")).rejects.toMatchObject({
      code: "AUTH_REQUIRED",
      status: 401,
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("maps the approved API error envelope", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "APPLICATION_NOT_FOUND",
            message: "Application not found",
            request_id: "req-1",
          },
        }),
        { status: 404 },
      ),
    );

    await expect(apiFetch("/api/v1/applications/missing")).rejects.toMatchObject({
      code: "APPLICATION_NOT_FOUND",
      message: "Application not found",
      requestId: "req-1",
      status: 404,
    });
  });

  it.each([
    ["malformed JSON", new Response("{", { status: 502, headers: { "X-Request-ID": "req-2" } })],
    ["an unapproved shape", new Response(JSON.stringify({ detail: "private" }), { status: 500 })],
  ])("returns a safe error for %s", async (_label, response) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response);

    const error = await apiFetch("/api/v1/applications").catch((caught) => caught);
    expect(error).toBeInstanceOf(ApiClientError);
    if (!(error instanceof ApiClientError)) throw error;
    expect(error).toMatchObject({ code: "API_ERROR", status: response.status });
    expect(error.message).not.toContain("private");
  });

  it("maps network failures without exposing the underlying error", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("secret network detail"));

    await expect(apiFetch("/api/v1/applications")).rejects.toMatchObject({
      code: "NETWORK_ERROR",
      status: 0,
      message: "The request could not be completed. Please try again.",
    });
  });

  it("does not set a multipart content type or boundary", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ id: "document-1" }), { status: 201 }));
    const body = new FormData();
    body.set("document_type", "CV");

    await apiFetch("api/v1/applications/app-1/documents", { method: "POST", body });

    const [, init] = fetchMock.mock.calls[0];
    expect(new Headers(init?.headers).has("Content-Type")).toBe(false);
    expect(init?.body).toBe(body);
  });

  it("fails safely when the API base URL is missing", async () => {
    delete process.env.NEXT_PUBLIC_API_BASE_URL;

    await expect(apiFetch("/api/v1/applications")).rejects.toMatchObject({
      code: "CONFIGURATION_ERROR",
      status: 0,
    });
  });
});
