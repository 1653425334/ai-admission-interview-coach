"use client";

import { FormEvent, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { createBrowserSupabaseClient } from "@/lib/supabase/client";

const SIGN_IN_ERROR = "邮箱或密码不正确，请重试。";

export default function SignInPage() {
  const router = useRouter();
  const submitting = useRef(false);
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current) return;
    submitting.current = true;
    setPending(true);
    setErrorMessage(null);

    const formData = new FormData(event.currentTarget);
    const email = String(formData.get("email") ?? "");
    const password = String(formData.get("password") ?? "");

    try {
      const { error } = await createBrowserSupabaseClient().auth.signInWithPassword({
        email,
        password,
      });
      if (error) {
        setErrorMessage(SIGN_IN_ERROR);
        return;
      }

      router.replace("/applications");
      router.refresh();
    } catch {
      setErrorMessage(SIGN_IN_ERROR);
    } finally {
      submitting.current = false;
      setPending(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <section className="w-full max-w-sm space-y-6">
        <div>
          <h1 className="text-2xl font-semibold">登录</h1>
          <p className="mt-2 text-sm text-gray-600">
            AI Admission Interview Coach
          </p>
        </div>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div>
            <label className="block text-sm font-medium" htmlFor="email">
              邮箱
            </label>
            <input
              className="mt-1 w-full rounded border px-3 py-2"
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              disabled={pending}
            />
          </div>
          <div>
            <label className="block text-sm font-medium" htmlFor="password">
              密码
            </label>
            <input
              className="mt-1 w-full rounded border px-3 py-2"
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              disabled={pending}
            />
          </div>
          {errorMessage ? (
            <p role="alert" className="text-sm text-red-700">
              {errorMessage}
            </p>
          ) : null}
          <button
            className="w-full rounded bg-black px-4 py-2 text-white disabled:opacity-60"
            type="submit"
            disabled={pending}
          >
            {pending ? "登录中…" : "登录"}
          </button>
        </form>
      </section>
    </main>
  );
}
