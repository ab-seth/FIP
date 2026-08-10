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

export type IngestionSourceType = "csv" | "api";
export type TransactionChannel =
  | "card_present"
  | "card_not_present"
  | "atm"
  | "transfer"
  | "other";

export interface TransactionPreview {
  external_transaction_id: string;
  occurred_at: string;
  amount: string;
  currency: string;
}

export interface CsvValidationError {
  row_number: number | null;
  field: string | null;
  code: string;
  message: string;
}

export interface IngestionBatchReceipt {
  id: string;
  display_id: string;
  source_type: IngestionSourceType;
  source_filename: string | null;
  source_checksum: string;
  byte_count: number;
  row_count: number;
  imported_by: string;
  created_at: string;
}

export interface UploadValidationResponse {
  valid: boolean;
  filename: string;
  checksum: string;
  byte_count: number;
  row_count: number;
  valid_rows: number;
  rejected_rows: number;
  preview: TransactionPreview[];
  errors: CsvValidationError[];
  existing_batch: IngestionBatchReceipt | null;
}

export interface UploadImportResponse {
  created: boolean;
  batch: IngestionBatchReceipt;
}

export interface ApiErrorResponse {
  detail: string;
}
