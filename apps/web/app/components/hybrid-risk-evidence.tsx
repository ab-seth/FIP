"use client";

import type {
  ApiErrorResponse,
  HybridAssessmentCreationResponse,
  HybridRiskAssessment,
  ShadowPrediction,
  UserRole,
} from "@fip/contracts";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

export function HybridRiskEvidence({
  assessments,
  predictions,
  role,
  ruleScore,
  transactionId,
}: {
  assessments: HybridRiskAssessment[];
  predictions: ShadowPrediction[];
  role: UserRole;
  ruleScore: number;
  transactionId: string;
}) {
  const router = useRouter();
  const supervised = useMemo(
    () => predictions.filter((prediction) => prediction.model_kind === "supervised"),
    [predictions],
  );
  const anomaly = useMemo(
    () => predictions.filter((prediction) => prediction.model_kind === "anomaly"),
    [predictions],
  );
  const verifiedSupervised = supervised.filter((prediction) => prediction.integrity_verified);
  const verifiedAnomaly = anomaly.filter((prediction) => prediction.integrity_verified);
  const [supervisedId, setSupervisedId] = useState(verifiedSupervised.at(-1)?.id ?? "");
  const [anomalyId, setAnomalyId] = useState(verifiedAnomaly.at(-1)?.id ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const latest = assessments.at(-1) ?? null;
  const canAssemble = role === "administrator" || role === "evaluator";
  const canSubmit = canAssemble && supervisedId !== "" && anomalyId !== "" && !busy;

  async function assembleEvidence(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(`/api/transactions/${transactionId}/hybrid-assessments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          supervised_prediction_id: supervisedId,
          anomaly_prediction_id: anomalyId,
        }),
      });
      if (!response.ok) {
        const error = (await response.json()) as ApiErrorResponse;
        setMessage({ kind: "error", text: error.detail ?? "The evidence set could not be assembled." });
        return;
      }
      const result = (await response.json()) as HybridAssessmentCreationResponse;
      setMessage({
        kind: "success",
        text: result.created
          ? "A verified hybrid assessment was added to this dossier."
          : "This exact evidence combination is already recorded.",
      });
      router.refresh();
    } catch {
      setMessage({ kind: "error", text: "The hybrid evidence service could not be reached." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="evidence-section hybrid-evidence" id="hybrid-evidence">
      <div className="dossier-section-heading hybrid-evidence-heading">
        <div>
          <p className="eyebrow">Machine-learning evidence</p>
          <h3>Hybrid risk evidence</h3>
        </div>
        <span className={latest?.integrity_verified ? "hybrid-verified" : ""}>
          {latest ? (latest.integrity_verified ? "Integrity verified" : "Integrity failed") : "Awaiting assembly"}
        </span>
      </div>

      <div className="hybrid-boundary">
        <span>Operational boundary</span>
        <p>
          The rules-only score remains <strong>{ruleScore}</strong>. ML evidence supports human review;
          it cannot reprioritize this case or act on the transaction.
        </p>
      </div>

      {latest ? (
        <LatestAssessment assessment={latest} predictions={predictions} />
      ) : (
        <div className="hybrid-empty">
          <strong>No hybrid assessment recorded</strong>
          <p>Select one verified supervised prediction and one verified anomaly prediction below.</p>
        </div>
      )}

      <div className="hybrid-prediction-register">
        <header>
          <div>
            <p className="eyebrow">Candidate evidence</p>
            <h4>Model prediction register</h4>
          </div>
          <Link href="/ml/models">Open model operations →</Link>
        </header>
        {predictions.length ? (
          <div className="hybrid-prediction-list">
            {predictions.map((prediction) => (
              <PredictionRow key={prediction.id} prediction={prediction} />
            ))}
          </div>
        ) : (
          <p className="hybrid-register-empty">
            No model predictions exist for this transaction. Run eligible models from Model Operations first.
          </p>
        )}
      </div>

      {canAssemble ? (
        <form className="hybrid-assembly" onSubmit={assembleEvidence}>
          <header>
            <p className="eyebrow">Governed composition</p>
            <h4>Assemble a 20 / 60 / 20 assessment</h4>
            <p>Choose evidence explicitly. The API verifies model type, snapshot lineage, authorization, and checksums.</p>
          </header>
          <PredictionSelect
            label="Supervised · 60%"
            onChange={setSupervisedId}
            predictions={verifiedSupervised}
            value={supervisedId}
          />
          <PredictionSelect
            label="Anomaly · 20%"
            onChange={setAnomalyId}
            predictions={verifiedAnomaly}
            value={anomalyId}
          />
          <button className="dossier-button dossier-button-primary" disabled={!canSubmit} type="submit">
            {busy ? "Verifying evidence…" : "Record hybrid assessment"}
          </button>
          {message ? (
            <p className={`case-action-message is-${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>
              {message.text}
            </p>
          ) : null}
        </form>
      ) : (
        <p className="hybrid-readonly-note">
          Hybrid assessments are readable by all case reviewers; only an administrator or evaluator may assemble one.
        </p>
      )}

      {assessments.length ? (
        <details className="hybrid-archive">
          <summary>{assessments.length} immutable assessment {assessments.length === 1 ? "record" : "records"}</summary>
          <ol>
            {[...assessments].reverse().map((assessment) => (
              <li key={assessment.id}>
                <div>
                  <strong>{formatScore(assessment.combined_score)} · {humanize(assessment.risk_level)}</strong>
                  <span>{assessment.policy_version} · {formatTimestamp(assessment.created_at)}</span>
                </div>
                <code>{shortChecksum(assessment.assessment_checksum)}</code>
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </section>
  );
}

function LatestAssessment({
  assessment,
  predictions,
}: {
  assessment: HybridRiskAssessment;
  predictions: ShadowPrediction[];
}) {
  const supervised = predictions.find((item) => item.id === assessment.supervised_prediction_id);
  const anomaly = predictions.find((item) => item.id === assessment.anomaly_prediction_id);
  const components = [
    { key: "rules", label: "Rules", detail: "Deterministic", value: assessment.components.rules },
    { key: "supervised", label: "Supervised", detail: supervised ? modelLabel(supervised) : "Recorded prediction", value: assessment.components.supervised },
    { key: "anomaly", label: "Anomaly", detail: anomaly ? modelLabel(anomaly) : "Recorded prediction", value: assessment.components.anomaly },
  ] as const;

  return (
    <div className="hybrid-assessment">
      <div className={`hybrid-score risk-${assessment.risk_level}`}>
        <span>Decision-support score</span>
        <strong>{formatScore(assessment.combined_score)}</strong>
        <em>{humanize(assessment.risk_level)} evidence</em>
      </div>
      <div className="hybrid-components">
        {components.map((component) => (
          <div key={component.key}>
            <header>
              <span>{component.label}</span>
              <strong>{formatPercent(component.value.weight)}</strong>
            </header>
            <p>{component.detail}</p>
            <div className="hybrid-meter" aria-hidden="true">
              <i
                style={{
                  width: `${Math.min(Number(component.value.normalized_score) * 100, 100)}%`,
                }}
              />
            </div>
            <footer>
              <span>Signal {formatScore(Number(component.value.normalized_score) * 100)}</span>
              <strong>+{formatScore(component.value.contribution_points)}</strong>
            </footer>
          </div>
        ))}
      </div>
      <div className="hybrid-proof">
        <p><span>Policy</span><code>{assessment.policy_version}</code></p>
        <p><span>Assessment proof</span><code>{shortChecksum(assessment.assessment_checksum)}</code></p>
        <p><span>Recorded by</span><strong>{assessment.created_by} · {formatTimestamp(assessment.created_at)}</strong></p>
      </div>
    </div>
  );
}

function PredictionRow({ prediction }: { prediction: ShadowPrediction }) {
  return (
    <article className={!prediction.integrity_verified ? "is-invalid" : ""}>
      <div className="hybrid-kind-mark" aria-hidden="true">
        {prediction.model_kind === "supervised" ? "S" : "A"}
      </div>
      <div>
        <strong>{modelLabel(prediction)}</strong>
        <span>{humanize(prediction.model_kind)} · {prediction.runtime_contract}</span>
      </div>
      <div className="hybrid-factor-preview">
        {(prediction.factors ?? []).slice(0, 2).map((factor) => (
          <span key={`${prediction.id}-${factor.feature}`}>{humanize(factor.feature)} {factor.contribution}</span>
        ))}
      </div>
      <div className="hybrid-prediction-score">
        <strong>{formatScore(Number(prediction.score) * 100)}</strong>
        <span>{prediction.integrity_verified ? "verified" : "failed"}</span>
      </div>
    </article>
  );
}

function PredictionSelect({
  label,
  onChange,
  predictions,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  predictions: ShadowPrediction[];
  value: string;
}) {
  return (
    <label>
      <span>{label}</span>
      <select onChange={(event) => onChange(event.target.value)} value={value}>
        <option value="">Select verified prediction</option>
        {predictions.map((prediction) => (
          <option key={prediction.id} value={prediction.id}>
            {modelLabel(prediction)} · {formatScore(Number(prediction.score) * 100)}
          </option>
        ))}
      </select>
    </label>
  );
}

function modelLabel(prediction: ShadowPrediction) {
  return `${prediction.model_key} v${prediction.model_version}`;
}

function formatScore(value: string | number) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(1).replace(/\.0$/, "") : String(value);
}

function formatPercent(value: string) {
  return `${formatScore(Number(value) * 100)}%`;
}

function shortChecksum(value: string) {
  return `${value.slice(0, 12)}…${value.slice(-6)}`;
}

function humanize(value: string) {
  const text = value.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function formatTimestamp(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}
