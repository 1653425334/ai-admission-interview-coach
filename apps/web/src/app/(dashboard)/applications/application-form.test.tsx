import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, apiFetch } from "@/lib/api/client";

import ApplicationForm from "./application-form";

const { push, replace } = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
}));

vi.mock("@/lib/api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...original, apiFetch: vi.fn() };
});

const mockApiFetch = vi.mocked(apiFetch);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ApplicationForm", () => {
  it("requires school and program before creating", async () => {
    render(<ApplicationForm />);
    await userEvent.click(screen.getByRole("button", { name: "Create application" }));
    expect(mockApiFetch).not.toHaveBeenCalled();
  });

  it("creates an application and navigates to its detail page", async () => {
    mockApiFetch.mockResolvedValue({ id: "app-1" } as never);
    render(<ApplicationForm />);
    await userEvent.type(screen.getByLabelText("Target school"), " CUHK-Shenzhen ");
    await userEvent.type(screen.getByLabelText("Target program"), " MSc AI ");
    await userEvent.click(screen.getByRole("button", { name: "Create application" }));

    expect(mockApiFetch).toHaveBeenCalledWith("/api/v1/applications", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target_school: "CUHK-Shenzhen",
        target_program: "MSc AI",
      }),
    });
    expect(push).toHaveBeenCalledWith("/applications/app-1");
  });

  it("shows a safe API error and request ID", async () => {
    mockApiFetch.mockRejectedValue(
      new ApiClientError("VALIDATION_ERROR", "Check the application details.", "req-1", 422),
    );
    render(<ApplicationForm />);
    await userEvent.type(screen.getByLabelText("Target school"), "School");
    await userEvent.type(screen.getByLabelText("Target program"), "Program");
    await userEvent.click(screen.getByRole("button", { name: "Create application" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Check the application details. Request ID: req-1",
    );
  });

  it("prevents rapid duplicate submissions", async () => {
    let resolve!: (value: unknown) => void;
    mockApiFetch.mockReturnValue(new Promise((done) => { resolve = done; }) as never);
    render(<ApplicationForm />);
    await userEvent.type(screen.getByLabelText("Target school"), "School");
    await userEvent.type(screen.getByLabelText("Target program"), "Program");
    const button = screen.getByRole("button", { name: "Create application" });
    await userEvent.dblClick(button);

    expect(mockApiFetch).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Creating…" })).toBeDisabled();
    resolve({ id: "app-1" });
  });
});
