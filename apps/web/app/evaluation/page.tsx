import type {
  EvaluationGate,
  EvaluationGateStatus,
  IntegritySummary,
  ShadowEvaluationReport,
  SystemEvaluationRecord,
  VersionLineage,
} from "@fip/contracts";
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth/server";
import { getCases } from "@/lib/cases/server";
import { getSystemEvaluationRecord } from "@/lib/evaluation/server";

import { WorkspaceShell } from "../components/workspace-shell";

export default async function EvaluationPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");

  const [record, cases] = await Promise.all([getSystemEvaluationRecord(), getCases()]);
  const activeCases = cases.filter((item) => item.status !== "classified");

  return (
    <WorkspaceShell
      activeNavigation="evaluation_record"
      eyebrow="System assurance"
      reviewCount={activeCases.length}
      title="Evaluation record"
      user={user}
    >
      {record ? (
        <EvaluationWorkspace record={record} />
      ) : (
        <section className="evaluation-unavailable">
          <p className="eyebrow">Evidence unavailable</p>
          <h2>The evaluation record could not be reached.</h2>
          <p>No operational score, case or model state was changed.</p>
        </section>
      )}
    </WorkspaceShell>
  );
}

function EvaluationWorkspace({ record }: { record: SystemEvaluationRecord }) {
  const passedGates = record.gates.filter((gate) => gate.status === "passed").length;
  return (
    <div className="evaluation-workspace">
      <section className="evaluation-cover">
        <div className="evaluation-cover-copy">
          <div className="evaluation-folio">
            <span>Record {record.schema_version}</span>
            <span>{record.evidence_as_of ? `Evidence through ${formatDateTime(record.evidence_as_of)}` : "No evidence recorded"}</span>
          </div>
          <p className="eyebrow">Reproducible system evidence</p>
          <h2>Claims require a traceable observation.</h2>
          <p>
            This read-only record measures what this environment has actually processed. It does
            not infer production capacity, rewrite a score or authorize an operational action.
          </p>
        </div>
        <div className={`evaluation-seal evaluation-${record.overall_status}`}>
          <span>{overallLabel(record.overall_status)}</span>
          <strong>
            {passedGates}<small>/{record.gates.length}</small>
          </strong>
          <p>evaluation gates passed</p>
        </div>
      </section>

      <section aria-label="Evaluation evidence summary" className="evaluation-metrics">
        <EvaluationMetric
          detail={`${record.volume.rule_assessments.toLocaleString("en-US")} rules assessments`}
          label="Observed transactions"
          value={record.volume.transactions.toLocaleString("en-US")}
        />
        <EvaluationMetric
          detail={`${record.scoring_latency.observation_count.toLocaleString("en-US")} verified observations`}
          label="Scoring p95"
          value={formatLatency(record.scoring_latency.p95_milliseconds)}
        />
        <EvaluationMetric
          detail={`${record.explanations.deterministic_fallbacks.toLocaleString("en-US")} safe fallbacks`}
          label="Validated LLM briefs"
          value={record.explanations.validated_llm_briefs.toLocaleString("en-US")}
        />
        <EvaluationMetric
          detail={`${record.model_evidence.shadow_evaluation_reports.toLocaleString("en-US")} sealed total`}
          label="Verified model reports"
          value={record.model_evidence.verified_shadow_evaluation_reports.toLocaleString("en-US")}
        />
      </section>

      <section className="evaluation-gates">
        <header className="evaluation-section-header">
          <div>
            <p className="eyebrow">Decision ledger</p>
            <h3>Evaluation gates</h3>
          </div>
          <p>Pending evidence is recorded separately from control failure.</p>
        </header>
        <ol>
          {record.gates.map((gate, index) => (
            <EvaluationGateRow gate={gate} index={index + 1} key={gate.gate} />
          ))}
        </ol>
      </section>

      <OperationalEvidence record={record} />

      <div className="evaluation-columns">
        <ExplanationEvidence record={record} />
        <ModelEvidence record={record} />
      </div>

      <IntegrityLedger integrity={record.integrity} />
      <VersionLedger versions={record.versions} />
      <ModelEvaluationArchive reports={record.latest_model_evaluations} />

      <footer className="evaluation-footnote">
        <span>Snapshot {shortChecksum(record.snapshot_checksum)}</span>
        <span>Read only</span>
        <span>No operational state changed</span>
      </footer>
    </div>
  );
}

function OperationalEvidence({ record }: { record: SystemEvaluationRecord }) {
  const volume = record.volume;
  return (
    <section className="evaluation-volume-ledger">
      <header className="evaluation-section-header">
        <div>
          <p className="eyebrow">Observed workload</p>
          <h3>Volume and outcomes</h3>
        </div>
        <p>Counts describe this environment only; they are not extrapolated capacity.</p>
      </header>
      <div className="volume-ledger-columns">
        <article>
          <h4>Scoring register</h4>
          <dl>
            <VolumeRow label="Transactions received" value={volume.transactions} />
            <VolumeRow label="Rules assessments" value={volume.rule_assessments} />
            <VolumeRow label="Low risk" value={volume.low_risk} />
            <VolumeRow label="Medium risk" value={volume.medium_risk} />
            <VolumeRow label="High risk" value={volume.high_risk} />
          </dl>
        </article>
        <article>
          <h4>Human review register</h4>
          <dl>
            <VolumeRow label="All cases" value={volume.cases} />
            <VolumeRow label="Open / in review" value={volume.open_cases + volume.in_review_cases} />
            <VolumeRow label="Confirmed fraud" value={volume.confirmed_fraud} />
            <VolumeRow label="Legitimate" value={volume.legitimate} />
            <VolumeRow label="Inconclusive" value={volume.inconclusive} />
          </dl>
        </article>
      </div>
    </section>
  );
}

function VolumeRow({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value.toLocaleString("en-US")}</dd>
    </div>
  );
}

function EvaluationMetric({
  detail,
  label,
  value,
}: {
  detail: string;
  label: string;
  value: string;
}) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function EvaluationGateRow({ gate, index }: { gate: EvaluationGate; index: number }) {
  return (
    <li className={`evaluation-gate evaluation-gate-${gate.status}`}>
      <span className="evaluation-gate-index">{String(index).padStart(2, "0")}</span>
      <span aria-label={statusLabel(gate.status)} className="evaluation-gate-mark">
        {statusMark(gate.status)}
      </span>
      <span className="evaluation-gate-copy">
        <strong>{humanize(gate.gate)}</strong>
        <small>{gate.detail}</small>
      </span>
      <span className="evaluation-gate-observation">
        <em>{statusLabel(gate.status)}</em>
        <strong>{formatObserved(gate.observed)}</strong>
        <small>{gate.target}</small>
      </span>
    </li>
  );
}

function ExplanationEvidence({ record }: { record: SystemEvaluationRecord }) {
  const explanation = record.explanations;
  const fallbacks = Object.entries(explanation.fallback_reasons);
  return (
    <section className="evaluation-evidence-card">
      <header>
        <p className="eyebrow">Grounded explanations</p>
        <h3>LLM evidence</h3>
      </header>
      <dl className="evaluation-statements">
        <EvidenceStatement
          label="Displayed failures"
          value={explanation.displayed_grounding_failures.toLocaleString("en-US")}
        />
        <EvidenceStatement
          label="Provider candidates rejected"
          value={explanation.provider_candidate_grounding_failures.toLocaleString("en-US")}
        />
        <EvidenceStatement
          label="LLM maximum runtime"
          value={formatLatency(explanation.llm_latency.maximum_milliseconds)}
        />
        <EvidenceStatement
          label="Fallback rate"
          value={formatRate(explanation.fallback_rate)}
        />
      </dl>
      <div className="evaluation-card-note">
        <strong>Safety boundary</strong>
        <p>
          Only checksum-verified, grounded LLM outputs enter the validated count. Rejected
          candidates are replaced with deterministic evidence summaries.
        </p>
      </div>
      {fallbacks.length ? (
        <div className="fallback-register">
          <span>Fallback causes</span>
          <ol>
            {fallbacks.map(([reason, count]) => (
              <li key={reason}>
                <span>{humanize(reason)}</span>
                <strong>{count}</strong>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </section>
  );
}

function ModelEvidence({ record }: { record: SystemEvaluationRecord }) {
  const evidence = record.model_evidence;
  return (
    <section className="evaluation-evidence-card model-evidence-card" id="model-evidence">
      <header>
        <p className="eyebrow">Decision support only</p>
        <h3>Model evidence</h3>
      </header>
      <dl className="evaluation-statements">
        <EvidenceStatement
          label="Registered lineages"
          value={`${evidence.verified_model_lineages}/${evidence.registered_models}`}
        />
        <EvidenceStatement
          label="Shadow predictions"
          value={evidence.shadow_predictions.toLocaleString("en-US")}
        />
        <EvidenceStatement
          label="Hybrid assessments"
          value={evidence.hybrid_assessments.toLocaleString("en-US")}
        />
        <EvidenceStatement
          label="Verified evaluations"
          value={`${evidence.verified_shadow_evaluation_reports}/${evidence.shadow_evaluation_reports}`}
        />
      </dl>
      <div className="evaluation-card-note">
        <strong>Operational boundary</strong>
        <p>
          Shadow predictions and hybrid scores remain advisory. Evaluation results do not change
          lifecycle state, case priority, transaction action or the deterministic rules score.
        </p>
      </div>
    </section>
  );
}

function EvidenceStatement({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function IntegrityLedger({ integrity }: { integrity: IntegritySummary }) {
  const rows = [
    ["Case records", integrity.case_records, integrity.case_integrity_failures],
    ["Model lineages", integrity.model_records, integrity.model_integrity_failures],
    ["Case briefs", integrity.case_brief_records, integrity.case_brief_integrity_failures],
    ["Hybrid assessments", integrity.hybrid_records, integrity.hybrid_integrity_failures],
    ["Dataset snapshots", integrity.dataset_records, integrity.dataset_integrity_failures],
    [
      "Evaluation reports",
      integrity.evaluation_report_records,
      integrity.evaluation_report_integrity_failures,
    ],
    [
      "Scoring observations",
      integrity.scoring_observation_records,
      integrity.scoring_observation_integrity_failures,
    ],
  ] as const;
  const totalFailures = rows.reduce((total, row) => total + row[2], 0);

  return (
    <section className="integrity-ledger" id="integrity-ledger">
      <header className="evaluation-section-header">
        <div>
          <p className="eyebrow">Append-only verification</p>
          <h3>Integrity ledger</h3>
        </div>
        <span className={totalFailures === 0 ? "integrity-seal" : "integrity-seal failed"}>
          {totalFailures === 0 ? "No failures found" : `${totalFailures} failures found`}
        </span>
      </header>
      <div className="integrity-table">
        <div aria-hidden="true" className="integrity-table-head">
          <span>Record family</span>
          <span>Records</span>
          <span>Checksum failures</span>
          <span>Finding</span>
        </div>
        {rows.map(([label, records, failures]) => (
          <div className="integrity-table-row" key={label}>
            <strong>{label}</strong>
            <span>{records.toLocaleString("en-US")}</span>
            <span>{failures.toLocaleString("en-US")}</span>
            <em className={failures === 0 ? "finding-verified" : "finding-failed"}>
              {records === 0 ? "Not observed" : failures === 0 ? "Verified" : "Investigate"}
            </em>
          </div>
        ))}
      </div>
      <p className="integrity-event-note">
        {integrity.case_events.toLocaleString("en-US")} case events are included in case-chain
        verification.
      </p>
    </section>
  );
}

function VersionLedger({ versions }: { versions: VersionLineage }) {
  return (
    <section className="version-ledger">
      <header className="evaluation-section-header">
        <div>
          <p className="eyebrow">Reproduction index</p>
          <h3>Active evidence contracts</h3>
        </div>
        <p>Version identifiers required to interpret this snapshot.</p>
      </header>
      <dl>
        {Object.entries(versions).map(([label, value], index) => (
          <div key={label}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <dt>{humanize(label)}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function ModelEvaluationArchive({ reports }: { reports: ShadowEvaluationReport[] }) {
  return (
    <section className="model-evaluation-archive" id="model-evaluation-archive">
      <header className="evaluation-section-header">
        <div>
          <p className="eyebrow">Immutable archive</p>
          <h3>Latest model evaluations</h3>
        </div>
        <p>{reports.length} records shown</p>
      </header>
      {reports.length ? (
        <ol>
          {reports.map((report) => (
            <li key={report.id}>
              <span className="model-report-reference">
                <strong>{report.model_key}</strong>
                <small>version {report.model_version}</small>
              </span>
              <span className="model-report-window">
                <strong>{formatDate(report.evaluation_window_start)} — {formatDate(report.evaluation_window_end)}</strong>
                <small>{report.evaluation_prediction_count.toLocaleString("en-US")} evaluation predictions</small>
              </span>
              <span className="model-report-drift">
                <strong>{humanize(readMetric(report.metrics, "score_drift", "status") ?? "unavailable")}</strong>
                <small>PSI {readMetric(report.metrics, "score_drift", "population_stability_index") ?? "—"}</small>
              </span>
              <code title={report.report_checksum}>{shortChecksum(report.report_checksum)}</code>
              <span className={report.integrity_verified ? "report-verified" : "report-failed"}>
                {report.integrity_verified ? "Verified" : "Integrity failed"}
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <div className="model-evaluation-empty">
          No model evaluation has been sealed. Reproducible model evaluation remains not
          demonstrated until a shadow model has two eligible prediction windows.
        </div>
      )}
    </section>
  );
}

function overallLabel(status: SystemEvaluationRecord["overall_status"]) {
  if (status === "passed") return "Controls passed";
  if (status === "attention") return "Attention required";
  return "Evidence pending";
}

function statusLabel(status: EvaluationGateStatus) {
  if (status === "not_observed") return "Not observed";
  if (status === "not_demonstrated") return "Not demonstrated";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function statusMark(status: EvaluationGateStatus) {
  if (status === "passed") return "✓";
  if (status === "failed") return "×";
  return "·";
}

function formatObserved(value: EvaluationGate["observed"]) {
  if (value === null) return "No observations";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return value.toLocaleString("en-US");
  return value;
}

function formatLatency(value: string | number | null) {
  if (value === null) return "Not observed";
  return `${Number(value).toLocaleString("en-US", { maximumFractionDigits: 2 })} ms`;
}

function formatRate(value: string | null) {
  if (value === null) return "Not observed";
  return `${(Number(value) * 100).toLocaleString("en-US", { maximumFractionDigits: 1 })}%`;
}

function humanize(value: string) {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function shortChecksum(value: string) {
  return `${value.slice(0, 12)}…`;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(value));
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
    timeZoneName: "short",
  }).format(new Date(value));
}

function readMetric(metrics: Record<string, unknown>, group: string, field: string) {
  const candidate = metrics[group];
  if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return null;
  const value = (candidate as Record<string, unknown>)[field];
  return typeof value === "string" || typeof value === "number" ? String(value) : null;
}
