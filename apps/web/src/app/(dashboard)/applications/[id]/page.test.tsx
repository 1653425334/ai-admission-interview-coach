import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { ApiClientError, apiFetch } from "@/lib/api/client";

import ApplicationDetailPage from "./page";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "app-1" }),
  useRouter: () => ({ replace }),
}));
vi.mock("@/lib/api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...original, apiFetch: vi.fn() };
});
const mockApiFetch = vi.mocked(apiFetch);

beforeEach(() => vi.clearAllMocks());

it("shows loading then application details and separate document slots", async () => {
  let resolve!: (value: unknown) => void;
  mockApiFetch.mockReturnValue(new Promise((done) => { resolve = done; }) as never);
  render(<ApplicationDetailPage />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading application…");

  resolve({
    id: "app-1",
    target_school: "CUHK-Shenzhen",
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
  });

  expect(await screen.findByRole("heading", { name: "CUHK-Shenzhen" })).toBeInTheDocument();
  expect(screen.getByText("cv.pdf")).toBeInTheDocument();
  expect(screen.getByLabelText("Personal statement PDF")).toBeEnabled();
  expect(screen.queryByLabelText("CV PDF")).not.toBeInTheDocument();
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
