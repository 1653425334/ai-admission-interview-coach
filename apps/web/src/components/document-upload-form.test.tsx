import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, apiFetch } from "@/lib/api/client";
import type { DocumentResponse } from "@/types/api";

import DocumentUploadForm, { MAX_PDF_BYTES } from "./document-upload-form";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("@/lib/api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...original, apiFetch: vi.fn() };
});
const mockApiFetch = vi.mocked(apiFetch);

const document: DocumentResponse = {
  id: "doc-1",
  application_id: "app-1",
  document_type: "CV",
  original_filename: "cv.pdf",
  mime_type: "application/pdf",
  size_bytes: 1024,
  parse_status: "UPLOADED",
  created_at: "2026-01-01T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("DocumentUploadForm", () => {
  it("rejects a non-PDF before calling the API", async () => {
    const user = userEvent.setup({ applyAccept: false });
    render(<DocumentUploadForm applicationId="app-1" documentType="CV" />);
    await user.upload(screen.getByLabelText("CV PDF"), new File(["x"], "cv.txt", { type: "text/plain" }));
    await user.click(screen.getByRole("button", { name: "Upload CV" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a PDF file.");
    expect(mockApiFetch).not.toHaveBeenCalled();
  });

  it("accepts a .pdf when the browser provides an empty MIME type", async () => {
    mockApiFetch.mockResolvedValue(document);
    const changed = vi.fn();
    render(<DocumentUploadForm applicationId="app-1" documentType="CV" onChanged={changed} />);
    await userEvent.upload(screen.getByLabelText("CV PDF"), new File(["%PDF"], "cv.PDF", { type: "" }));
    await userEvent.click(screen.getByRole("button", { name: "Upload CV" }));
    await vi.waitFor(() => expect(changed).toHaveBeenCalled());
  });

  it("rejects a PDF over 10 MB", async () => {
    render(<DocumentUploadForm applicationId="app-1" documentType="CV" />);
    const large = new File([new Uint8Array(MAX_PDF_BYTES + 1)], "large.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("CV PDF"), large);
    await userEvent.click(screen.getByRole("button", { name: "Upload CV" }));
    expect(screen.getByRole("alert")).toHaveTextContent("The PDF must be 10 MB or smaller.");
    expect(mockApiFetch).not.toHaveBeenCalled();
  });

  it("uploads multipart data without setting Content-Type and refreshes", async () => {
    mockApiFetch.mockResolvedValue(document);
    const changed = vi.fn();
    const file = new File(["%PDF"], "cv.pdf", { type: "application/pdf" });
    render(<DocumentUploadForm applicationId="app-1" documentType="CV" onChanged={changed} />);
    await userEvent.upload(screen.getByLabelText("CV PDF"), file);
    await userEvent.click(screen.getByRole("button", { name: "Upload CV" }));

    await vi.waitFor(() => expect(mockApiFetch).toHaveBeenCalledTimes(1));
    const [path, init] = mockApiFetch.mock.calls[0];
    expect(path).toBe("/api/v1/applications/app-1/documents");
    expect(init?.method).toBe("POST");
    expect(init?.headers).toBeUndefined();
    expect(init?.body).toBeInstanceOf(FormData);
    const body = init?.body as FormData;
    expect(body.get("document_type")).toBe("CV");
    expect(body.get("file")).toBe(file);
    expect(changed).toHaveBeenCalled();
  });

  it("shows server validation errors with the request ID", async () => {
    mockApiFetch.mockRejectedValue(new ApiClientError("INVALID_PDF", "This PDF is invalid.", "req-pdf", 422));
    render(<DocumentUploadForm applicationId="app-1" documentType="CV" />);
    await userEvent.upload(screen.getByLabelText("CV PDF"), new File(["%PDF"], "cv.pdf", { type: "application/pdf" }));
    await userEvent.click(screen.getByRole("button", { name: "Upload CV" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This PDF is invalid. Request ID: req-pdf");
  });

  it("shows an existing slot and disables replacement upload", () => {
    render(<DocumentUploadForm applicationId="app-1" documentType="CV" document={document} />);
    expect(screen.getByText("cv.pdf")).toBeInTheDocument();
    expect(screen.queryByLabelText("CV PDF")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete CV" })).toBeEnabled();
  });

  it("does not delete when confirmation is cancelled", async () => {
    vi.mocked(window.confirm).mockReturnValue(false);
    render(<DocumentUploadForm applicationId="app-1" documentType="CV" document={document} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete CV" }));
    expect(window.confirm).toHaveBeenCalledWith("Delete CV?");
    expect(mockApiFetch).not.toHaveBeenCalled();
  });

  it("deletes after confirmation and refreshes", async () => {
    mockApiFetch.mockResolvedValue(undefined);
    const changed = vi.fn();
    render(<DocumentUploadForm applicationId="app-1" documentType="CV" document={document} onChanged={changed} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete CV" }));
    expect(mockApiFetch).toHaveBeenCalledWith("/api/v1/documents/doc-1", { method: "DELETE" });
    await vi.waitFor(() => expect(changed).toHaveBeenCalled());
  });

  it("keeps the document visible when deletion fails", async () => {
    mockApiFetch.mockRejectedValue(new ApiClientError("STORAGE_DELETE_FAILED", "Could not delete.", "req-del", 502));
    render(<DocumentUploadForm applicationId="app-1" documentType="CV" document={document} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete CV" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not delete. Request ID: req-del");
    expect(screen.getByText("cv.pdf")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete CV" })).toBeEnabled();
  });

  it("prevents rapid duplicate uploads", async () => {
    let resolve!: (value: unknown) => void;
    mockApiFetch.mockReturnValue(new Promise((done) => { resolve = done; }) as never);
    render(<DocumentUploadForm applicationId="app-1" documentType="CV" />);
    await userEvent.upload(screen.getByLabelText("CV PDF"), new File(["%PDF"], "cv.pdf", { type: "application/pdf" }));
    await userEvent.dblClick(screen.getByRole("button", { name: "Upload CV" }));
    expect(mockApiFetch).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Uploading…" })).toBeDisabled();
    resolve(document);
  });
});
