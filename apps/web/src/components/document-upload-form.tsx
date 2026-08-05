"use client";

import { ChangeEvent, FormEvent, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiClientError, apiFetch } from "@/lib/api/client";
import type { DocumentResponse, DocumentType } from "@/types/api";

export const MAX_PDF_BYTES = 10 * 1024 * 1024;

interface DocumentUploadFormProps {
  applicationId: string;
  documentType: DocumentType;
  document?: DocumentResponse;
  onChanged?: () => void | Promise<void>;
}

function errorText(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.requestId
      ? `${error.message} Request ID: ${error.requestId}`
      : error.message;
  }
  return "The request could not be completed. Please try again.";
}

function isPdf(file: File): boolean {
  if (file.type && file.type !== "application/pdf") return false;
  return file.name.toLowerCase().endsWith(".pdf");
}

export default function DocumentUploadForm({
  applicationId,
  documentType,
  document,
  onChanged,
}: DocumentUploadFormProps) {
  const router = useRouter();
  const submitting = useRef(false);
  const deleting = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const label = documentType === "CV" ? "CV" : "Personal statement";

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    setError(null);
    const selected = event.target.files?.[0] ?? null;
    setFile(selected);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || document) return;
    if (!file || !isPdf(file)) {
      setError("Choose a PDF file.");
      return;
    }
    if (file.size > MAX_PDF_BYTES) {
      setError("The PDF must be 10 MB or smaller.");
      return;
    }

    submitting.current = true;
    setPending(true);
    setError(null);
    const body = new FormData();
    body.append("document_type", documentType);
    body.append("file", file);

    try {
      await apiFetch<DocumentResponse>(
        `/api/v1/applications/${applicationId}/documents`,
        { method: "POST", body },
      );
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
      await onChanged?.();
    } catch (caught) {
      if (caught instanceof ApiClientError && caught.code === "AUTH_REQUIRED") {
        router.replace("/sign-in");
        return;
      }
      setError(errorText(caught));
    } finally {
      submitting.current = false;
      setPending(false);
    }
  }

  async function handleDelete() {
    if (!document || deleting.current) return;
    if (!window.confirm(`Delete ${label}?`)) return;

    deleting.current = true;
    setPending(true);
    setError(null);
    try {
      await apiFetch<void>(`/api/v1/documents/${document.id}`, {
        method: "DELETE",
      });
      await onChanged?.();
    } catch (caught) {
      if (caught instanceof ApiClientError && caught.code === "AUTH_REQUIRED") {
        router.replace("/sign-in");
        return;
      }
      setError(errorText(caught));
    } finally {
      deleting.current = false;
      setPending(false);
    }
  }

  return (
    <section className="space-y-3 rounded-lg border p-5" aria-labelledby={`${documentType}-heading`}>
      <h2 className="text-lg font-semibold" id={`${documentType}-heading`}>
        {label}
      </h2>
      {document ? (
        <div className="space-y-2">
          <p>
            <span className="font-medium">File:</span> {document.original_filename}
          </p>
          <p className="text-sm text-gray-600">
            {(document.size_bytes / 1024).toFixed(1)} KB · {document.parse_status}
          </p>
          <button
            className="rounded border px-3 py-2 disabled:opacity-60"
            type="button"
            disabled={pending}
            onClick={handleDelete}
          >
            {pending ? "Deleting…" : `Delete ${label}`}
          </button>
        </div>
      ) : (
        <form className="space-y-3" onSubmit={handleSubmit}>
          <div>
            <label className="block text-sm font-medium" htmlFor={`${documentType}-pdf`}>
              {label} PDF
            </label>
            <input
              ref={inputRef}
              className="mt-1 block w-full text-sm"
              id={`${documentType}-pdf`}
              name="file"
              type="file"
              accept="application/pdf,.pdf"
              disabled={pending}
              onChange={handleFileChange}
            />
          </div>
          <button
            className="rounded bg-black px-4 py-2 text-white disabled:opacity-60"
            type="submit"
            disabled={pending}
          >
            {pending ? "Uploading…" : `Upload ${label}`}
          </button>
        </form>
      )}
      {error ? (
        <p className="text-sm text-red-700" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
