// ─── Request Types (mirror backend Pydantic schemas) ────────────────────────

export interface SignUpRequest {
  first_name: string;
  last_name: string;
  email: string;
  password: string;
}

export interface SignInRequest {
  email: string;
  password: string;
}

// ─── Response Types ─────────────────────────────────────────────────────────

export interface UserResponse {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
  created_at: string;
}

// ─── Error Types ────────────────────────────────────────────────────────────

export interface ApiError {
  detail: string;
}
