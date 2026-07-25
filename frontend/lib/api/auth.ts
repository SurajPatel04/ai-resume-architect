import type { SignInRequest, SignUpRequest, UserResponse } from "@/types/auth";
import { apiFetch } from "./client";

/**
 * POST /api/v1/auth/signup
 * Register a new user account.
 */
export async function signUp(data: SignUpRequest): Promise<UserResponse> {
  return apiFetch<UserResponse>("/api/v1/auth/signup", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

/**
 * POST /api/v1/auth/signin
 * Authenticate user — backend sets HttpOnly cookies on success.
 */
export async function signIn(data: SignInRequest): Promise<UserResponse> {
  return apiFetch<UserResponse>("/api/v1/auth/signin", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

/**
 * POST /api/v1/auth/logout
 * Revoke refresh token and clear session cookies.
 */
export async function logout(): Promise<{ message: string }> {
  return apiFetch<{ message: string }>("/api/v1/auth/logout", {
    method: "POST",
  });
}

/**
 * GET /api/v1/auth/me
 * Get the current authenticated user's profile.
 */
export async function getMe(): Promise<UserResponse> {
  return apiFetch<UserResponse>("/api/v1/auth/me");
}
