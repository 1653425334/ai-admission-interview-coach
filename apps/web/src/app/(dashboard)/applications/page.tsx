"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiClientError, apiFetch } from "@/lib/api/client";
import type { ApplicationList } from "@/types/api";

import ApplicationForm from "./application-form";

function errorText(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.requestId
      ? `${error.message} Request ID: ${error.requestId}`
      : error.message;
  }
  return "Applications could not be loaded. Please try again.";
}

export default function ApplicationsPage() {
  const router = useRouter();
  const [result, setResult] = useState<ApplicationList | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    apiFetch<ApplicationList>("/api/v1/applications")
      .then((value) => {
        if (active) setResult(value);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        if (caught instanceof ApiClientError && caught.code === "AUTH_REQUIRED") {
          router.replace("/sign-in");
          return;
        }
        setError(errorText(caught));
      });
    return () => {
      active = false;
    };
  }, [router]);

  return (
    <main className="mx-auto w-full max-w-4xl space-y-8 px-6 py-10">
      <div>
        <h1 className="text-2xl font-semibold">Applications</h1>
        <p className="mt-2 text-sm text-gray-600">
          Create an admission target, then add its CV and personal statement.
        </p>
      </div>

      <ApplicationForm />

      <section aria-labelledby="application-list-heading" className="space-y-3">
        <h2 className="text-lg font-semibold" id="application-list-heading">
          Your applications
        </h2>
        {!result && !error ? <p role="status">Loading applications…</p> : null}
        {error ? (
          <p className="text-sm text-red-700" role="alert">
            {error}
          </p>
        ) : null}
        {result?.items.length === 0 ? (
          <p>No applications yet. Create your first application above.</p>
        ) : null}
        {result?.items.length ? (
          <ul className="space-y-3">
            {result.items.map((application) => (
              <li className="rounded-lg border p-4" key={application.id}>
                <Link
                  className="font-medium underline"
                  href={`/applications/${application.id}`}
                >
                  {application.target_school} — {application.target_program}
                </Link>
                {application.degree_type ? (
                  <p className="mt-1 text-sm text-gray-600">
                    {application.degree_type}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </main>
  );
}
