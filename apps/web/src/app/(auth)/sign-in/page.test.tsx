import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

const replace = vi.fn();
const refresh = vi.fn();
const signInWithPassword = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, refresh }),
}));

vi.mock("@/lib/supabase/client", () => ({
  createBrowserSupabaseClient: () => ({ auth: { signInWithPassword } }),
}));

import SignInPage from "./page";

beforeEach(() => {
  replace.mockReset();
  refresh.mockReset();
  signInWithPassword.mockReset();
});

it("has accessible email and password controls", () => {
  render(<SignInPage />);

  expect(screen.getByLabelText("邮箱")).toHaveAttribute("type", "email");
  expect(screen.getByLabelText("密码")).toHaveAttribute("type", "password");
  expect(screen.getByRole("button", { name: "登录" })).toBeEnabled();
});

it("signs in and redirects to applications", async () => {
  signInWithPassword.mockResolvedValue({ error: null });
  const user = userEvent.setup();
  render(<SignInPage />);

  await user.type(screen.getByLabelText("邮箱"), "student@example.com");
  await user.type(screen.getByLabelText("密码"), "not-a-real-password");
  await user.click(screen.getByRole("button", { name: "登录" }));

  expect(signInWithPassword).toHaveBeenCalledWith({
    email: "student@example.com",
    password: "not-a-real-password",
  });
  expect(replace).toHaveBeenCalledWith("/applications");
  expect(refresh).toHaveBeenCalledOnce();
});

it("shows one safe message for invalid credentials", async () => {
  signInWithPassword.mockResolvedValue({ error: { message: "provider details" } });
  const user = userEvent.setup();
  render(<SignInPage />);

  await user.type(screen.getByLabelText("邮箱"), "student@example.com");
  await user.type(screen.getByLabelText("密码"), "wrong-password");
  await user.click(screen.getByRole("button", { name: "登录" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "邮箱或密码不正确，请重试。",
  );
  expect(screen.queryByText("provider details")).not.toBeInTheDocument();
  expect(replace).not.toHaveBeenCalled();
});

it("shows the same safe message when the auth SDK rejects", async () => {
  signInWithPassword.mockRejectedValue(new Error("private SDK network details"));
  const user = userEvent.setup();
  render(<SignInPage />);

  await user.type(screen.getByLabelText("邮箱"), "student@example.com");
  await user.type(screen.getByLabelText("密码"), "password");
  await user.click(screen.getByRole("button", { name: "登录" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "邮箱或密码不正确，请重试。",
  );
  expect(screen.queryByText("private SDK network details")).not.toBeInTheDocument();
});

it("disables the form while sign-in is pending", async () => {
  let finishSignIn!: (value: { error: null }) => void;
  signInWithPassword.mockReturnValue(
    new Promise((resolve) => {
      finishSignIn = resolve;
    }),
  );
  const user = userEvent.setup();
  render(<SignInPage />);

  await user.type(screen.getByLabelText("邮箱"), "student@example.com");
  await user.type(screen.getByLabelText("密码"), "password");
  await user.click(screen.getByRole("button", { name: "登录" }));

  expect(screen.getByRole("button", { name: "登录中…" })).toBeDisabled();
  expect(screen.getByLabelText("邮箱")).toBeDisabled();
  expect(screen.getByLabelText("密码")).toBeDisabled();

  finishSignIn({ error: null });
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/applications"));
});

it("guards against two synchronous submissions", async () => {
  signInWithPassword.mockReturnValue(new Promise(() => undefined));
  render(<SignInPage />);
  const form = screen.getByRole("button", { name: "登录" }).closest("form");
  expect(form).not.toBeNull();

  fireEvent.submit(form!);
  fireEvent.submit(form!);

  expect(signInWithPassword).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: "登录中…" })).toBeDisabled();
});
