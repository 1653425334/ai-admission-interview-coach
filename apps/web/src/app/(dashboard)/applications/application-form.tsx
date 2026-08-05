"use client";

import { FormEvent, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiClientError, apiFetch } from "@/lib/api/client";
import type { ApplicationResponse } from "@/types/api";

function errorText(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.requestId
      ? `${error.message} Request ID: ${error.requestId}`
      : error.message;
  }
  return "The request could not be completed. Please try again.";
}

export default function ApplicationForm() {
  const router = useRouter();
  const submitting = useRef(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current) return;

    const form = event.currentTarget;
    if (!form.reportValidity()) return;

    submitting.current = true;
    setPending(true);
    setError(null);

    const data = new FormData(form);
    try {
      const application = await apiFetch<ApplicationResponse>(
        "/api/v1/applications",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            target_school: String(data.get("target_school") ?? "").trim(),
            target_program: String(data.get("target_program") ?? "").trim(),
          }),
        },
      );
      router.push(`/applications/${application.id}`);
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

  return (
    <form className="space-y-4 rounded-lg border p-5" onSubmit={handleSubmit}>
      <h2 className="text-lg font-semibold">Create application</h2>
      <div>
        <label className="block text-sm font-medium" htmlFor="target-school">
          Target school
        </label>
        <input
          className="mt-1 w-full rounded border px-3 py-2"
          id="target-school"
          name="target_school"
          maxLength={200}
          required
          disabled={pending}
        />
      </div>
      <div>
        <label className="block text-sm font-medium" htmlFor="target-program">
          Target program
        </label>
        <input
          className="mt-1 w-full rounded border px-3 py-2"
          id="target-program"
          name="target_program"
          maxLength={200}
          required
          disabled={pending}
        />
      </div>
      {error ? (
        <p className="text-sm text-red-700" role="alert">
          {error}
        </p>
      ) : null}
      <button
        className="rounded bg-black px-4 py-2 text-white disabled:opacity-60"
        type="submit"
        disabled={pending}
      >
        {pending ? "Creating…" : "Create application"}
      </button>
    </form>
  );
}
