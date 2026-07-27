import type { ApiError } from "@/types/auth";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * Shared fetch wrapper for the backend API.
 *
 * - Prepends the API base URL to relative paths.
 * - Sends `credentials: "include"` so HttpOnly cookies are attached.
 * - Parses JSON and throws a structured error on non-OK responses.
 */
export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${path}`;

  // FormData needs the browser to set Content-Type itself — it carries the
  // multipart boundary, which we can't know here.
  const isFormData = options.body instanceof FormData;

  const response = await fetch(url, {
    ...options,
    credentials: "include",
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...options.headers,
    },
  });

  // For 204 No Content responses
  if (response.status === 204) {
    return {} as T;
  }

  const data = await response.json();

  if (!response.ok) {
    const error = data as ApiError;
    throw new Error(error.detail || `Request failed with status ${response.status}`);
  }

  return data as T;
}