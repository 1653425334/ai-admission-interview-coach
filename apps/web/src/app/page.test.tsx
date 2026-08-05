import { beforeEach, expect, it, vi } from "vitest";

const { redirect, getUser } = vi.hoisted(() => ({
  redirect: vi.fn(),
  getUser: vi.fn(),
}));

vi.mock("next/navigation", () => ({ redirect }));
vi.mock("@/lib/supabase/server", () => ({
  createServerSupabaseClient: async () => ({ auth: { getUser } }),
}));

import Home from "./page";

beforeEach(() => {
  redirect.mockReset();
  getUser.mockReset();
});

it("redirects an authenticated user to applications", async () => {
  getUser.mockResolvedValue({ data: { user: { id: "user-1" } } });

  await Home();

  expect(redirect).toHaveBeenCalledWith("/applications");
});

it("redirects a guest to sign-in", async () => {
  getUser.mockResolvedValue({ data: { user: null } });

  await Home();

  expect(redirect).toHaveBeenCalledWith("/sign-in");
});
