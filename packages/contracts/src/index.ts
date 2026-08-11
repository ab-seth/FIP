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
  | "outcome_reviewed"
  | "brief_generated";

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

export interface HybridRiskWeights {
  rules: string;
  supervised: string;
  anomaly: string;
}

export interface HybridRiskComponent {
  source_score: string;
  normalized_score: string;
  weight: string;
  contribution_points: string;
}

export interface HybridRiskAssessment {
  id: string;
  transaction_id: string;
  feature_snapshot_id: string;
  rule_assessment_id: string;
  supervised_prediction_id: string;
  anomaly_prediction_id: string;
  policy_version: string;
  evidence_schema_version: string;
  weights: HybridRiskWeights;
  components: {
    rules: HybridRiskComponent;
    supervised: HybridRiskComponent;
    anomaly: HybridRiskComponent;
  };
  combined_score: string;
  risk_level: "low" | "medium" | "high";
  evidence: Record<string, unknown>;
  created_by: string;
  assessment_checksum: string;
  integrity_verified: boolean;
  decision_support_only: true;
  shadow_inputs_only: true;
  affects_case_priority: false;
  affects_transaction_action: false;
  llm_influenced_score: false;
  created_at: string;
}

export interface CaseBriefClaim {
  text: string;
  evidence_refs: string[];
}

export interface CaseBriefOutput {
  summary: string;
  summary_evidence_refs: string[];
  primary_risk_factors: CaseBriefClaim[];
  supporting_evidence: CaseBriefClaim[];
  uncertainties: CaseBriefClaim[];
  recommended_review_steps: CaseBriefClaim[];
}

export interface GroundingFailure {
  code: string;
  location: string;
  detail: string;
}

export interface GroundingValidation {
  schema_valid: boolean;
  citations_valid: boolean;
  numerical_claims_valid: boolean;
  prohibited_actions_absent: boolean;
  grounding_passed: boolean;
  failures: GroundingFailure[];
}

export interface CaseBriefValidation {
  provider_candidate: GroundingValidation;
  display_output: GroundingValidation;
  fallback_used: boolean;
  fallback_reason: string | null;
}

export interface CaseBrief {
  id: string;
  case_id: string;
  transaction_id: string;
  rule_assessment_id: string;
  hybrid_assessment_id: string | null;
  prompt_version: string;
  output_schema_version: string;
  provider_name: string;
  provider_model: string;
  generation_mode: "llm" | "deterministic_fallback";
  output: CaseBriefOutput | null;
  validation: CaseBriefValidation | null;
  evidence_checksum: string;
  explanation_checksum: string;
  integrity_verified: boolean;
  generation_milliseconds: number;
  requested_by: string;
  llm_changed_score: false;
  llm_classified_case: false;
  financial_action_taken: false;
  created_at: string;
}

export interface CaseBriefCreationResponse {
  created: boolean;
  brief: CaseBrief;
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
  hybrid_assessments: HybridRiskAssessment[];
  case_briefs: CaseBrief[];
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

export type ModelKind = "supervised" | "anomaly";
export type ModelPurpose = "research" | "operational";
export type ModelRuntimeContract = "binary-probability-v1" | "anomaly-score-v1";
export type ModelLifecycleStatus = "candidate" | "shadow" | "retired" | "rejected";

export interface ModelRegistrationPayload {
  model_key: string;
  version: string;
  kind: ModelKind;
  purpose: ModelPurpose;
  runtime_contract: ModelRuntimeContract;
  artifact_sha256: string;
  feature_set_version: string;
  training_dataset_id: string;
  training_dataset_checksum: string;
  training_data_approved: boolean;
  operational_feature_compatible: boolean;
  decision_threshold: string | number | null;
  evaluation_metrics: Record<string, string | number | boolean>;
  model_card_reference: string;
  model_card_checksum: string;
}

export interface ModelLifecycleEvent {
  sequence_number: number;
  from_status: ModelLifecycleStatus | null;
  to_status: ModelLifecycleStatus;
  reason: string;
  actor_username: string;
  previous_event_checksum: string | null;
  event_checksum: string;
  created_at: string;
}

export interface RegisteredModel {
  id: string;
  model_key: string;
  version: string;
  kind: ModelKind;
  purpose: ModelPurpose;
  runtime_contract: ModelRuntimeContract;
  artifact_sha256: string;
  feature_set_version: string;
  training_dataset_id: string;
  training_dataset_checksum: string;
  training_data_approved: boolean;
  operational_feature_compatible: boolean;
  decision_threshold: string | null;
  evaluation_metrics: Record<string, unknown>;
  model_card_reference: string;
  model_card_checksum: string;
  registered_by: string;
  registration_checksum: string;
  current_status: ModelLifecycleStatus;
  lineage_verified: boolean;
  lifecycle: ModelLifecycleEvent[];
  created_at: string;
}

export interface ModelRegistrationResponse {
  created: boolean;
  model: RegisteredModel;
}

export interface ModelArtifactStatus {
  model_id: string;
  artifact_sha256: string;
  installed: boolean;
  integrity_verified: boolean;
  size_bytes: number | null;
}

export interface ModelArtifactInstallationResponse {
  model_id: string;
  artifact_sha256: string;
  size_bytes: number;
  installed: boolean;
  integrity_verified: boolean;
}

export interface ShadowFactor {
  feature: string;
  contribution: string;
  direction: string;
}

export interface ShadowPrediction {
  id: string;
  transaction_id: string;
  model_id: string;
  model_key: string;
  model_version: string;
  feature_set_version: string;
  feature_snapshot_checksum: string;
  authorization_event_checksum: string;
  output_schema_version: string;
  score: string;
  threshold: string;
  would_exceed_model_threshold: boolean;
  factors: ShadowFactor[];
  runtime_milliseconds: number;
  prediction_checksum: string;
  integrity_verified: boolean;
  shadow_only: true;
  affects_operational_score: false;
  created_at: string;
}

export interface ShadowRunResponse {
  model_id: string;
  selected_count: number;
  created_count: number;
  replayed_count: number;
  shadow_only: true;
  affects_operational_score: false;
  predictions: ShadowPrediction[];
}

export interface ShadowEvaluationCreationResponse {
  created: boolean;
  report: ShadowEvaluationReport;
}

export type EvaluationGateStatus =
  | "passed"
  | "failed"
  | "not_observed"
  | "not_demonstrated";

export interface EvaluationGate {
  gate: string;
  status: EvaluationGateStatus;
  observed: string | number | boolean | null;
  target: string;
  detail: string;
}

export interface LatencySummary {
  observation_count: number;
  mean_milliseconds: string | null;
  p95_milliseconds: string | null;
  maximum_milliseconds: number | null;
  target_milliseconds: number;
  status: EvaluationGateStatus;
}

export interface EvaluationVolume {
  transactions: number;
  rule_assessments: number;
  low_risk: number;
  medium_risk: number;
  high_risk: number;
  cases: number;
  open_cases: number;
  in_review_cases: number;
  classified_cases: number;
  confirmed_fraud: number;
  legitimate: number;
  inconclusive: number;
}

export interface ExplanationEvaluation {
  total_briefs: number;
  validated_llm_briefs: number;
  deterministic_fallbacks: number;
  fallback_rate: string | null;
  provider_candidate_grounding_failures: number;
  displayed_grounding_failures: number;
  fallback_reasons: Record<string, number>;
  llm_latency: LatencySummary;
}

export interface ModelEvidence {
  registered_models: number;
  verified_model_lineages: number;
  shadow_predictions: number;
  hybrid_assessments: number;
  shadow_evaluation_reports: number;
  verified_shadow_evaluation_reports: number;
}

export interface IntegritySummary {
  case_events: number;
  case_records: number;
  case_integrity_failures: number;
  model_records: number;
  model_integrity_failures: number;
  case_brief_records: number;
  case_brief_integrity_failures: number;
  hybrid_records: number;
  hybrid_integrity_failures: number;
  dataset_records: number;
  dataset_integrity_failures: number;
  evaluation_report_records: number;
  evaluation_report_integrity_failures: number;
  scoring_observation_records: number;
  scoring_observation_integrity_failures: number;
}

export interface VersionLineage {
  feature_set: string;
  ruleset: string;
  risk_bands: string;
  scoring_runtime_observation: string;
  shadow_output: string;
  hybrid_policy: string;
  case_brief_prompt: string;
  case_brief_output: string;
  model_evaluation_report: string;
  label_contract: string;
  split_contract: string;
}

export interface ShadowEvaluationReport {
  id: string;
  model_id: string;
  model_key: string;
  model_version: string;
  report_schema_version: string;
  baseline_window_start: string;
  baseline_window_end: string;
  evaluation_window_start: string;
  evaluation_window_end: string;
  baseline_prediction_count: number;
  evaluation_prediction_count: number;
  metrics: Record<string, unknown>;
  input_lineage_checksum: string;
  report_checksum: string;
  requested_by: string;
  integrity_verified: boolean;
  monitoring_only: true;
  affects_operational_score: false;
  triggers_automatic_action: false;
  created_at: string;
}

export interface SystemEvaluationRecord {
  schema_version: string;
  evidence_as_of: string | null;
  overall_status: "passed" | "attention" | "evidence_pending";
  volume: EvaluationVolume;
  scoring_latency: LatencySummary;
  explanations: ExplanationEvaluation;
  model_evidence: ModelEvidence;
  integrity: IntegritySummary;
  versions: VersionLineage;
  gates: EvaluationGate[];
  latest_model_evaluations: ShadowEvaluationReport[];
  snapshot_checksum: string;
  read_only: true;
  changes_operational_state: false;
}

export type AuditCategory =
  | "case"
  | "model"
  | "scoring"
  | "explanation"
  | "hybrid"
  | "dataset"
  | "evaluation";

export type AuditIntegrityFilter = "all" | "verified" | "failed";

export interface AuditLedgerEntry {
  id: string;
  category: AuditCategory;
  action: string;
  subject_id: string;
  subject_label: string;
  actor_username: string;
  detail: string;
  sequence_number: number | null;
  occurred_at: string;
  checksum: string;
  previous_checksum: string | null;
  integrity_verified: boolean;
  href: string;
  metadata: Record<string, unknown>;
}

export interface AuditLedgerSummary {
  total_records: number;
  verified_records: number;
  failed_records: number;
  chained_records: number;
  category_counts: Partial<Record<AuditCategory, number>>;
}

export interface AuditLedger {
  schema_version: string;
  entries: AuditLedgerEntry[];
  summary: AuditLedgerSummary;
  total: number;
  page: number;
  page_size: number;
  page_count: number;
  category: AuditCategory | null;
  integrity: AuditIntegrityFilter;
  query: string | null;
  read_only: true;
  changes_operational_state: false;
}
