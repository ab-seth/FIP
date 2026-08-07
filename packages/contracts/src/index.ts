export type UserRole = "administrator" | "analyst" | "manager" | "evaluator";

export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
}

export interface ReadinessResponse {
  status: "ready";
  database: "reachable";
}

export interface UserResponse {
  id: string;
  username: string;
  role: UserRole;
  is_active: boolean;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
}
