import { createBrowserSupabaseClient } from "@/lib/supabase/client";

const GENERIC_API_ERROR = "The request could not be completed. Please try again.";

export class ApiClientError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly requestId: string | null,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiClientError";
  }
}

function apiUrl(path: string): string {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/+$/, "");
  if (!baseUrl) {
    throw new ApiClientError(
      "CONFIGURATION_ERROR",
      "The application is not configured correctly.",
      null,
      0,
    );
  }

  const normalizedPath = path.replace(/^\/+/, "");
  return `${baseUrl}/${normalizedPath}`;
}

function requestIdFrom(response: Response): string | null {
  return response.headers.get("x-request-id");
}

function isErrorEnvelope(
  value: unknown,
): value is { error: { code: string; message: string; request_id: string } } {
  if (!value || typeof value !== "object" || !("error" in value)) return false;
  const error = value.error;
  return (
    !!error &&
    typeof error === "object" &&
    "code" in error &&
    typeof error.code === "string" &&
    "message" in error &&
    typeof error.message === "string" &&
    "request_id" in error &&
    typeof error.request_id === "string"
  );
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const supabase = createBrowserSupabaseClient();
  const { data, error } = await supabase.auth.getSession();
  const accessToken = data.session?.access_token;

  if (error || !accessToken) {
    throw new ApiClientError(
      "AUTH_REQUIRED",
      "Please sign in to continue.",
      null,
      401,
    );
  }

  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${accessToken}`);
  const url = apiUrl(path);

  let response: Response;
  try {
    response = await fetch(url, { ...init, headers });
  } catch {
    throw new ApiClientError("NETWORK_ERROR", GENERIC_API_ERROR, null, 0);
  }

  if (response.ok) {
    if (response.status === 204) return undefined as T;
    try {
      return (await response.json()) as T;
    } catch {
      throw new ApiClientError(
        "INVALID_RESPONSE",
        GENERIC_API_ERROR,
        requestIdFrom(response),
        response.status,
      );
    }
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (isErrorEnvelope(body)) {
    throw new ApiClientError(
      body.error.code,
      body.error.message,
      body.error.request_id,
      response.status,
    );
  }

  throw new ApiClientError(
    "API_ERROR",
    GENERIC_API_ERROR,
    requestIdFrom(response),
    response.status,
  );
}
