import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { ApiClientError, apiFetch } from "@/lib/api/client";

import ApplicationDetailPage from "./page";

const { router } = vi.hoisted(() => {
  const replace = vi.fn();
  return { replace, router: { replace } };
});
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "app-1" }),
  useRouter: () => router,
}));
vi.mock("@/lib/api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...original, apiFetch: vi.fn() };
});
vi.mock("@/components/document-upload-form", () => ({
  default: ({
    documentType,
    document,
    onChanged,
  }: {
    documentType: "CV" | "PS";
    document?: { original_filename: string };
    onChanged?: () => void | Promise<void>;
  }) => (
    <section>
      <h2>{documentType}</h2>
      <p>{document?.original_filename ?? `${documentType} empty`}</p>
      <button type="button" onClick={() => { void onChanged?.(); }}>
        Refresh {documentType}
      </button>
    </section>
  ),
}));
const mockApiFetch = vi.mocked(apiFetch);

beforeEach(() => {
  vi.clearAllMocks();
  mockApiFetch.mockReset();
});

function application(targetSchool: string) {
  return {
    id: "app-1",
    target_school: targetSchool,
    target_program: "MSc AI",
    degree_type: null,
    status: "DRAFT",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    documents: [{
      id: "doc-1",
      application_id: "app-1",
      document_type: "CV",
      original_filename: "cv.pdf",
      mime_type: "application/pdf",
      size_bytes: 1024,
      parse_status: "UPLOADED",
      created_at: "2026-01-01T00:00:00Z",
    }],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

it("shows loading then application details and separate document slots", async () => {
  let resolve!: (value: unknown) => void;
  mockApiFetch.mockReturnValue(new Promise((done) => { resolve = done; }) as never);
  render(<ApplicationDetailPage />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading application…");

  resolve(application("CUHK-Shenzhen"));

  expect(await screen.findByRole("heading", { name: "CUHK-Shenzhen" })).toBeInTheDocument();
  expect(screen.getByText("cv.pdf")).toBeInTheDocument();
  expect(screen.getByText("PS empty")).toBeInTheDocument();
});

it("shows a not-found state for a missing or unowned application", async () => {
  mockApiFetch.mockRejectedValue(
    new ApiClientError("APPLICATION_NOT_FOUND", "Application not found.", "req-404", 404),
  );
  render(<ApplicationDetailPage />);
  expect(await screen.findByRole("heading", { name: "Application not found" })).toBeInTheDocument();
  expect(screen.queryByText("req-404")).not.toBeInTheDocument();
});

it("shows a safe non-404 load error and request ID", async () => {
  mockApiFetch.mockRejectedValue(
    new ApiClientError("API_ERROR", "Could not load application.", "req-detail", 500),
  );
  render(<ApplicationDetailPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Could not load application. Request ID: req-detail",
  );
  expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
});

it("does not let an older refresh success overwrite the newest response", async () => {
  mockApiFetch.mockResolvedValueOnce(application("Initial") as never);
  render(<ApplicationDetailPage />);
  expect(await screen.findByRole("heading", { name: "Initial" })).toBeInTheDocument();

  const older = deferred<ReturnType<typeof application>>();
  const newest = deferred<ReturnType<typeof application>>();
  mockApiFetch.mockReturnValueOnce(older.promise as never).mockReturnValueOnce(newest.promise as never);
  fireEvent.click(screen.getByRole("button", { name: "Refresh CV" }));
  fireEvent.click(screen.getByRole("button", { name: "Refresh PS" }));

  act(() => newest.resolve(application("Newest")));
  expect(await screen.findByRole("heading", { name: "Newest" })).toBeInTheDocument();
  act(() => older.resolve(application("Stale")));
  await vi.waitFor(() => {
    expect(screen.getByRole("heading", { name: "Newest" })).toBeInTheDocument();
  });
  expect(screen.getByRole("heading", { name: "Newest" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Stale" })).not.toBeInTheDocument();
});

it("does not let an older refresh rejection or finally overwrite the newest response", async () => {
  mockApiFetch.mockResolvedValueOnce(application("Initial") as never);
  render(<ApplicationDetailPage />);
  expect(await screen.findByRole("heading", { name: "Initial" })).toBeInTheDocument();

  const older = deferred<ReturnType<typeof application>>();
  const newest = deferred<ReturnType<typeof application>>();
  mockApiFetch.mockReturnValueOnce(older.promise as never).mockReturnValueOnce(newest.promise as never);
  fireEvent.click(screen.getByRole("button", { name: "Refresh CV" }));
  fireEvent.click(screen.getByRole("button", { name: "Refresh PS" }));

  act(() => newest.resolve(application("Newest")));
  expect(await screen.findByRole("heading", { name: "Newest" })).toBeInTheDocument();
  act(() => older.reject(new ApiClientError("API_ERROR", "Stale failure.", "req-old", 500)));
  await vi.waitFor(() => {
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
  expect(screen.getByRole("heading", { name: "Newest" })).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("does not commit a pending response after unmount", async () => {
  const pending = deferred<ReturnType<typeof application>>();
  mockApiFetch.mockReturnValue(pending.promise as never);
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
  const view = render(<ApplicationDetailPage />);
  view.unmount();

  act(() => pending.resolve(application("Too late")));
  await Promise.resolve();
  expect(consoleError).not.toHaveBeenCalled();
  consoleError.mockRestore();
});
