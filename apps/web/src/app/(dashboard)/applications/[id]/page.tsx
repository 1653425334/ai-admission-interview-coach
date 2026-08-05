"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import DocumentUploadForm from "@/components/document-upload-form";
import { ApiClientError, apiFetch } from "@/lib/api/client";
import type { ApplicationDetail, DocumentType } from "@/types/api";

function errorText(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.requestId
      ? `${error.message} Request ID: ${error.requestId}`
      : error.message;
  }
  return "The application could not be loaded. Please try again.";
}

export default function ApplicationDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [application, setApplication] = useState<ApplicationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const mounted = useRef(false);
  const requestSequence = useRef(0);

  const loadApplication = useCallback(async (showLoading = false) => {
    const sequence = ++requestSequence.current;
    if (mounted.current && showLoading) {
      setLoading(true);
      setError(null);
      setNotFound(false);
    }

    try {
      const value = await apiFetch<ApplicationDetail>(
        `/api/v1/applications/${params.id}`,
      );
      if (!mounted.current || sequence !== requestSequence.current) return;
      setApplication(value);
      setNotFound(false);
      setError(null);
    } catch (caught) {
      if (!mounted.current || sequence !== requestSequence.current) return;
      if (caught instanceof ApiClientError && caught.code === "AUTH_REQUIRED") {
        router.replace("/sign-in");
        return;
      }
      if (caught instanceof ApiClientError && caught.status === 404) {
        setNotFound(true);
        setApplication(null);
        return;
      }
      setError(errorText(caught));
    } finally {
      if (mounted.current && sequence === requestSequence.current) {
        setLoading(false);
      }
    }
  }, [params.id, router]);

  useEffect(() => {
    mounted.current = true;
    // The request only commits state asynchronously after the sequence guard.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadApplication(true);
    return () => {
      mounted.current = false;
      requestSequence.current += 1;
    };
  }, [loadApplication]);

  if (loading) {
    return <main className="mx-auto max-w-4xl px-6 py-10" role="status">Loading application…</main>;
  }

  if (notFound) {
    return (
      <main className="mx-auto max-w-4xl space-y-3 px-6 py-10">
        <h1 className="text-2xl font-semibold">Application not found</h1>
        <p>This application does not exist or is not available to you.</p>
        <Link className="underline" href="/applications">Back to applications</Link>
      </main>
    );
  }

  if (error || !application) {
    return (
      <main className="mx-auto max-w-4xl space-y-3 px-6 py-10">
        <h1 className="text-2xl font-semibold">Application</h1>
        <p className="text-red-700" role="alert">{error ?? "The application could not be loaded."}</p>
        <button className="rounded border px-3 py-2" type="button" onClick={() => { void loadApplication(true); }}>
          Try again
        </button>
      </main>
    );
  }

  const documentFor = (type: DocumentType) =>
    application.documents.find((document) => document.document_type === type);

  return (
    <main className="mx-auto w-full max-w-4xl space-y-8 px-6 py-10">
      <Link className="text-sm underline" href="/applications">Back to applications</Link>
      <div>
        <h1 className="text-2xl font-semibold">{application.target_school}</h1>
        <p className="mt-1">{application.target_program}</p>
        {application.degree_type ? <p className="text-sm text-gray-600">{application.degree_type}</p> : null}
      </div>
      <div className="grid gap-5 md:grid-cols-2">
        {(["CV", "PS"] as const).map((type) => (
          <DocumentUploadForm
            applicationId={application.id}
            document={documentFor(type)}
            documentType={type}
            key={type}
            onChanged={() => loadApplication()}
          />
        ))}
      </div>
    </main>
  );
}
