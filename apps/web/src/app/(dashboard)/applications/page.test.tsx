import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { ApiClientError, apiFetch } from "@/lib/api/client";

import ApplicationsPage from "./page";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace }) }));
vi.mock("@/lib/api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...original, apiFetch: vi.fn() };
});
const mockApiFetch = vi.mocked(apiFetch);

beforeEach(() => vi.clearAllMocks());

it("shows loading then an empty state", async () => {
  let resolve!: (value: unknown) => void;
  mockApiFetch.mockReturnValue(new Promise((done) => { resolve = done; }) as never);
  render(<ApplicationsPage />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading applications…");
  resolve({ items: [] });
  expect(await screen.findByText(/No applications yet/)).toBeInTheDocument();
});

it("shows populated applications", async () => {
  mockApiFetch.mockResolvedValue({
    items: [{
      id: "app-1", target_school: "CUHK-Shenzhen", target_program: "MSc AI",
      degree_type: null, status: "DRAFT", created_at: "2026-01-01", updated_at: "2026-01-01",
    }],
  });
  render(<ApplicationsPage />);
  const link = await screen.findByRole("link", { name: "CUHK-Shenzhen — MSc AI" });
  expect(link).toHaveAttribute("href", "/applications/app-1");
});

it("shows a load error with its request ID", async () => {
  mockApiFetch.mockRejectedValue(new ApiClientError("API_ERROR", "Could not load.", "req-list", 500));
  render(<ApplicationsPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load. Request ID: req-list");
});

it("redirects to sign-in when authentication is required", async () => {
  mockApiFetch.mockRejectedValue(new ApiClientError("AUTH_REQUIRED", "Sign in.", null, 401));
  render(<ApplicationsPage />);
  await vi.waitFor(() => expect(replace).toHaveBeenCalledWith("/sign-in"));
});
