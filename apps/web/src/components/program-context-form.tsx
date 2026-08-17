"use client";

import { FormEvent, useState } from "react";

import { ApiClientError, apiFetch } from "@/lib/api/client";
import type { ApplicationDetail } from "@/types/api";

interface ProgramContextFormProps {
  application: ApplicationDetail;
  onSaved: (application: ApplicationDetail) => void;
}

export default function ProgramContextForm({ application, onSaved }: ProgramContextFormProps) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaving(true);
    setError(null);
    try {
      const updated = await apiFetch<ApplicationDetail>(
        `/api/v1/applications/${application.id}/program-context`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            program_url: String(form.get("program_url") ?? "").trim() || null,
            program_description: String(form.get("program_description") ?? "").trim() || null,
          }),
        },
      );
      onSaved(updated);
    } catch (caught) {
      setError(caught instanceof ApiClientError ? caught.message : "Could not save program context.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-lg border p-5" aria-labelledby="program-context-heading">
      <h2 className="text-lg font-semibold" id="program-context-heading">Program context</h2>
      <p className="mt-1 text-sm text-gray-600">
        Paste official program information so analysis can prioritize risks for this application. This is not candidate evidence.
      </p>
      <form className="mt-4 space-y-3" onSubmit={save}>
        <div>
          <label className="block text-sm font-medium" htmlFor="program-url">Official program URL</label>
          <input className="mt-1 w-full rounded border px-3 py-2" defaultValue={application.program_url ?? ""} id="program-url" maxLength={500} name="program_url" type="url" />
        </div>
        <div>
          <label className="block text-sm font-medium" htmlFor="program-description">Official program description</label>
          <textarea className="mt-1 min-h-32 w-full rounded border px-3 py-2" defaultValue={application.program_description ?? ""} id="program-description" maxLength={6000} name="program_description" placeholder="Paste the official overview, curriculum, or research directions." />
        </div>
        {error ? <p className="text-sm text-red-700" role="alert">{error}</p> : null}
        <button className="rounded border px-4 py-2 disabled:opacity-60" disabled={saving} type="submit">{saving ? "Saving…" : "Save program context"}</button>
      </form>
    </section>
  );
}
