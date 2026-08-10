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

export type CasePriority = "standard" | "urgent";
export type CaseStatus = "open" | "in_review" | "classified";
export type CaseClassification = "confirmed_fraud" | "legitimate" | "inconclusive";
export type OutcomeReviewStatus = "approved" | "rejected";
export type CaseEventType =
  | "opened"
  | "review_started"
  | "note_added"
  | "classified"
  | "outcome_reviewed";

export interface CaseTransaction {
  id: string;
  external_transaction_id: string;
  occurred_at: string;
  amount: string;
  currency: string;
  account_reference: string;
  merchant_reference: string | null;
  channel: string | null;
}

export interface CaseOutcomeReview {
  status: OutcomeReviewStatus;
  reason: string;
  reviewed_by: string;
  review_checksum: string;
  created_at: string;
}

export interface CaseOutcome {
  id: string;
  classification: CaseClassification;
  rationale: string;
  determined_by: string;
  outcome_checksum: string;
  review: CaseOutcomeReview | null;
  training_eligible: boolean;
  created_at: string;
}

export interface CaseSummary {
  id: string;
  display_id: string;
  status: CaseStatus;
  priority: CasePriority;
  transaction: CaseTransaction;
  risk_score: number;
  risk_level: "low" | "medium" | "high";
  triggered_rule_count: number;
  outcome: CaseOutcome | null;
  opening_checksum: string;
  integrity_verified: boolean;
  created_at: string;
  last_activity_at: string;
}

export interface CaseRuleEvidence {
  rule_score: number;
  risk_level: "low" | "medium" | "high";
  ruleset_version: string;
  assessment_checksum: string;
  feature_set_version: string;
  feature_snapshot_checksum: string;
  triggered_rules: Array<{
    rule_id?: string;
    title?: string;
    contribution_points?: number;
    evidence?: Record<string, unknown>;
    [key: string]: unknown;
  }>;
  feature_values: Record<string, unknown>;
}

export interface CaseEvent {
  sequence_number: number;
  event_type: CaseEventType;
  payload: Record<string, unknown>;
  actor_username: string;
  previous_event_checksum: string | null;
  event_checksum: string;
  created_at: string;
}

export interface CaseDetail extends CaseSummary {
  opening_reason: string;
  evidence: CaseRuleEvidence;
  events: CaseEvent[];
}

export type DatasetReadinessStatus = "blocked" | "ready";
export type DatasetSplit = "train" | "validation" | "test";

export interface DatasetReadinessGate {
  gate: string;
  passed: boolean;
  observed: unknown;
  required: string;
  detail: string;
}

export interface DatasetReadiness {
  cutoff_at: string;
  eligible_label_count: number;
  positive_label_count: number;
  negative_label_count: number;
  excluded_integrity_failures: number;
  excluded_feature_contract_mismatches: number;
  excluded_temporal_leakage: number;
  feature_set_version: string;
  label_contract_version: string;
  readiness_status: DatasetReadinessStatus;
  gates: DatasetReadinessGate[];
}

export interface DatasetSplitCounts {
  train: number;
  validation: number;
  test: number;
}

export interface OperationalDatasetSummary {
  id: string;
  display_id: string;
  feature_set_version: string;
  label_contract_version: string;
  split_contract_version: string;
  feature_names: string[];
  row_count: number;
  positive_count: number;
  negative_count: number;
  split_counts: DatasetSplitCounts;
  readiness_status: DatasetReadinessStatus;
  readiness_gates: DatasetReadinessGate[];
  creation_reason: string;
  cutoff_at: string;
  created_by: string;
  source_manifest_checksum: string;
  dataset_checksum: string;
  integrity_verified: boolean;
  created_at: string;
}

export interface OperationalDatasetRow {
  row_index: number;
  occurred_at: string;
  split: DatasetSplit;
  label: 0 | 1;
  feature_values: Record<string, unknown>;
  feature_snapshot_checksum: string;
  outcome_checksum: string;
  review_checksum: string;
  row_checksum: string;
}

export interface OperationalDatasetDetail extends OperationalDatasetSummary {
  rows: OperationalDatasetRow[];
  rows_truncated: boolean;
}

export interface DatasetSnapshotCreateResponse {
  created: boolean;
  dataset: OperationalDatasetDetail;
}
