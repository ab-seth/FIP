"use client";

import type {
  ApiErrorResponse,
  ModelKind,
  OperationalDatasetSummary,
  OperationalTrainingRun,
  TrainingCandidate,
  TrainingRunCreationResponse,
  UserRole,
} from "@fip/contracts";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

export function TrainingOperations({
  datasets,
  role,
  runs,
}: {
  datasets: OperationalDatasetSummary[];
  role: UserRole;
  runs: OperationalTrainingRun[];
}) {
  const router = useRouter();
  const readyDatasets = datasets.filter(
    (dataset) => dataset.readiness_status === "ready" && dataset.integrity_verified,
  );
  const active = runs.filter((run) => run.status === "queued" || run.status === "running");
  const successful = runs.filter((run) => run.status === "succeeded");
  const failed = runs.filter((run) => run.status === "failed");

  useEffect(() => {
    if (!active.length) return;
    const timer = window.setInterval(() => router.refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [active.length, router]);

  return (
    <div className="training-workspace">
      <section className="training-cover">
        <div>
          <p className="eyebrow">Reproducible candidate foundry</p>
          <h2>Train behind a hard governance boundary.</h2>
          <p>
            A dedicated worker consumes one verified snapshot and seals two candidates. Training
            cannot register a model, authorize shadow execution, change a score, or take action.
          </p>
        </div>
        <div className="training-boundary-seal">
          <span>Execution plane</span>
          <strong>Offline</strong>
          <small>Human handoff required</small>
        </div>
      </section>

      <section aria-label="Training run counts" className="training-metrics">
        <TrainingMetric label="Ready snapshots" value={readyDatasets.length} />
        <TrainingMetric label="Active runs" value={active.length} />
        <TrainingMetric label="Sealed runs" value={successful.length} />
        <TrainingMetric label="Failed runs" value={failed.length} />
      </section>

      <div className="training-layout">
        <section className="training-run-ledger">
          <header className="training-section-heading">
            <div>
              <p className="eyebrow">Durable execution ledger</p>
              <h3>Candidate training runs</h3>
            </div>
            <span>{runs.length} immutable configurations</span>
          </header>
          {runs.length ? (
            <ol className="training-run-list">
              {runs.map((run, index) => (
                <TrainingRunRecord
                  index={runs.length - index}
                  key={run.id}
                  role={role}
                  run={run}
                />
              ))}
            </ol>
          ) : (
            <div className="training-empty">
              <span>∅</span>
              <h4>No training run has been requested.</h4>
              <p>A ready snapshot and an administrator are required to create the first run.</p>
            </div>
          )}
        </section>

        <TrainingRequestPanel datasets={readyDatasets} role={role} runs={runs} />
      </div>
    </div>
  );
}

function TrainingMetric({ label, value }: { label: string; value: number }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function TrainingRunRecord({
  index,
  role,
  run,
}: {
  index: number;
  role: UserRole;
  run: OperationalTrainingRun;
}) {
  const candidates = run.candidates;
  return (
    <li className={`training-run training-run-${run.status}`}>
      <header>
        <span className="training-run-index">{String(index).padStart(2, "0")}</span>
        <div className="training-run-title">
          <span>{run.display_id}</span>
          <h4>Candidate version {run.candidate_version}</h4>
          <small>{run.dataset_display_id} · requested by {run.requested_by}</small>
        </div>
        <div className="training-run-state">
          <span className={`training-status training-status-${run.status}`}>
            {statusLabel(run.status)}
          </span>
          <small>{formatTimestamp(run.completed_at ?? run.started_at ?? run.created_at)}</small>
        </div>
      </header>

      {!run.integrity_verified ? (
        <div className="training-integrity-alert" role="alert">
          This run or its upstream evidence no longer passes integrity verification.
        </div>
      ) : null}

      {run.status === "running" || run.status === "queued" ? (
        <div className="training-progress">
          <span><i /></span>
          <p>
            {run.status === "queued"
              ? "Waiting for the isolated training worker."
              : "Fitting, calibrating, evaluating, and checksumming both candidate families."}
          </p>
        </div>
      ) : null}

      {run.status === "failed" ? (
        <div className="training-failure">
          <div>
            <strong>{humanize(run.error_code ?? "training failed")}</strong>
            <p>{run.error_message ?? "The worker did not complete this run."}</p>
          </div>
          {role === "administrator" ? <TrainingRetry runId={run.id} /> : null}
        </div>
      ) : null}

      {run.status === "succeeded" && candidates ? (
        <div className="training-candidates">
          <CandidateCard candidate={candidates.supervised} role={role} runId={run.id} />
          <CandidateCard candidate={candidates.anomaly} role={role} runId={run.id} />
        </div>
      ) : null}

      <details className="training-run-detail">
        <summary>
          <span>Configuration and chain</span>
          <small>{run.events.length} lifecycle {run.events.length === 1 ? "event" : "events"}</small>
        </summary>
        <div className="training-run-detail-body">
          <dl className="training-config">
            <div><dt>Dataset proof</dt><dd><code>{shortChecksum(run.dataset_checksum)}</code></dd></div>
            <div><dt>Configuration</dt><dd><code>{shortChecksum(run.configuration_checksum)}</code></dd></div>
            <div><dt>Random seed</dt><dd>{run.seed}</dd></div>
            <div><dt>Maximum FPR</dt><dd>{formatPercent(run.maximum_false_positive_rate)}</dd></div>
            <div><dt>Pipeline</dt><dd>{run.pipeline_version}</dd></div>
            <div><dt>Evidence proof</dt><dd><code>{run.evidence_checksum ? shortChecksum(run.evidence_checksum) : "Pending"}</code></dd></div>
            <div><dt>Manifest proof</dt><dd><code>{run.manifest_checksum ? shortChecksum(run.manifest_checksum) : "Pending"}</code></dd></div>
            <div><dt>Bundle proof</dt><dd><code>{run.bundle_checksum ? shortChecksum(run.bundle_checksum) : "Pending"}</code></dd></div>
            {run.status === "succeeded" ? (
              <div className="training-evidence-downloads">
                <dt>Run evidence</dt>
                <dd>
                  <a download href={evidencePath(run.id, "training-evidence")}>Evidence JSON</a>
                  <a download href={evidencePath(run.id, "run-manifest")}>Manifest JSON</a>
                </dd>
              </div>
            ) : null}
          </dl>
          <ol className="training-event-chain">
            {run.events.map((event) => (
              <li key={event.event_checksum}>
                <span>{String(event.sequence_number).padStart(2, "0")}</span>
                <div>
                  <strong>{statusLabel(event.to_status)}</strong>
                  <p>{event.detail}</p>
                  <small>{event.actor_username} · {formatTimestamp(event.created_at)}</small>
                </div>
                <code>{shortChecksum(event.event_checksum)}</code>
              </li>
            ))}
          </ol>
        </div>
      </details>
      <footer>
        <span>Candidate only</span>
        <span>No automatic registration</span>
        <span>No operational score effect</span>
      </footer>
    </li>
  );
}

function TrainingRetry({ runId }: { runId: string }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function retry() {
    setPending(true);
    setError(null);
    try {
      const response = await fetch(`/api/ml-training-runs/${encodeURIComponent(runId)}/retry`, {
        method: "POST",
      });
      if (!response.ok) {
        const result = (await response.json()) as ApiErrorResponse;
        setError(result.detail ?? "The failed run could not be queued again.");
        return;
      }
      router.refresh();
    } catch {
      setError("The training operations service could not be reached.");
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="training-retry-control">
      <button disabled={pending} onClick={retry} type="button">
        {pending ? "Queueing…" : "Retry same configuration"}
      </button>
      {error ? <small role="alert">{error}</small> : null}
    </div>
  );
}

function CandidateCard({
  candidate,
  role,
  runId,
}: {
  candidate: TrainingCandidate;
  role: UserRole;
  runId: string;
}) {
  const metrics = candidate.evaluation_metrics;
  return (
    <article className={`training-candidate candidate-${candidate.kind}`}>
      <header>
        <span className="candidate-kind-mark">{candidate.kind === "supervised" ? "S" : "A"}</span>
        <div>
          <span>{humanize(candidate.kind)} candidate</span>
          <h5>{candidate.selected_model}</h5>
        </div>
      </header>
      <div className="candidate-scorecard">
        <CandidateMetric label="PR-AUC" value={metric(metrics, "average_precision")} />
        <CandidateMetric label="Recall" value={metric(metrics, "recall")} />
        <CandidateMetric label="False positive" value={metric(metrics, "false_positive_rate")} />
        <CandidateMetric label="Threshold" value={candidate.decision_threshold} />
      </div>
      <p className="candidate-proof">
        <span>Artifact proof</span><code>{shortChecksum(candidate.artifact_sha256)}</code>
      </p>
      <div className="candidate-downloads">
        <a download href={artifactPath(runId, candidate.kind, "registration")}>Registration JSON</a>
        <a download href={artifactPath(runId, candidate.kind, "model-card")}>Model card</a>
        {role === "administrator" ? (
          <a download href={artifactPath(runId, candidate.kind, "model")}>Candidate artifact</a>
        ) : null}
      </div>
    </article>
  );
}

function CandidateMetric({ label, value }: { label: string; value: string | null }) {
  return <div><span>{label}</span><strong>{formatMetric(value)}</strong></div>;
}

function TrainingRequestPanel({
  datasets,
  role,
  runs,
}: {
  datasets: OperationalDatasetSummary[];
  role: UserRole;
  runs: OperationalTrainingRun[];
}) {
  const router = useRouter();
  const [datasetId, setDatasetId] = useState(datasets[0]?.id ?? "");
  const [version, setVersion] = useState("");
  const [seed, setSeed] = useState("42");
  const [maximumFpr, setMaximumFpr] = useState("0.05");
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<{ error: boolean; text: string } | null>(null);
  const selected = useMemo(
    () => datasets.find((dataset) => dataset.id === datasetId) ?? null,
    [datasetId, datasets],
  );
  const canCreate = role === "administrator";
  const versionExists = runs.some((run) => run.candidate_version === version.trim());

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setMessage(null);
    try {
      const response = await fetch("/api/ml-training-runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dataset_id: datasetId,
          candidate_version: version,
          seed: Number(seed),
          maximum_false_positive_rate: maximumFpr,
          reason,
        }),
      });
      const result = (await response.json()) as TrainingRunCreationResponse | ApiErrorResponse;
      if (!response.ok) {
        setMessage({ error: true, text: errorDetail(result, "The training run was not queued.") });
        return;
      }
      const creation = result as TrainingRunCreationResponse;
      setMessage({
        error: false,
        text: creation.created
          ? `${creation.run.display_id} was queued for the isolated worker.`
          : "This exact immutable configuration is already recorded.",
      });
      setReason("");
      router.refresh();
    } catch {
      setMessage({ error: true, text: "The training operations service could not be reached." });
    } finally {
      setPending(false);
    }
  }

  return (
    <aside className="training-request-panel">
      <p className="eyebrow">Administrator control</p>
      <h3>Queue a governed run.</h3>
      <p>
        The request records one immutable dataset, version, random seed and capacity constraint.
        A separate worker performs the expensive training.
      </p>
      {canCreate ? (
        <form onSubmit={submit}>
          <label>
            <span>Ready snapshot</span>
            <select onChange={(event) => setDatasetId(event.target.value)} required value={datasetId}>
              <option value="">Select verified snapshot</option>
              {datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.display_id} · {dataset.row_count} rows
                </option>
              ))}
            </select>
          </label>
          {selected ? (
            <div className="training-dataset-proof">
              <span>{selected.positive_count} fraud / {selected.negative_count} legitimate</span>
              <code>{shortChecksum(selected.dataset_checksum)}</code>
            </div>
          ) : null}
          <label>
            <span>Candidate version</span>
            <input
              maxLength={64}
              onChange={(event) => setVersion(event.target.value)}
              pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
              placeholder="2026.08.1"
              required
              value={version}
            />
            {versionExists ? <small>This version already has a training record.</small> : null}
          </label>
          <div className="training-config-fields">
            <label>
              <span>Random seed</span>
              <input min="0" onChange={(event) => setSeed(event.target.value)} required type="number" value={seed} />
            </label>
            <label>
              <span>Maximum FPR</span>
              <input max="0.999999" min="0.000001" onChange={(event) => setMaximumFpr(event.target.value)} required step="0.000001" type="number" value={maximumFpr} />
            </label>
          </div>
          <label>
            <span>Training rationale</span>
            <textarea
              minLength={12}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Why this snapshot and version should be trained now"
              required
              rows={4}
              value={reason}
            />
          </label>
          <button
            className="dossier-button dossier-button-primary"
            disabled={pending || !datasets.length || versionExists}
            type="submit"
          >
            {pending ? "Recording request…" : "Queue offline training"}
          </button>
          {message ? (
            <p className={`training-action-message ${message.error ? "is-error" : "is-success"}`}>
              {message.text}
            </p>
          ) : null}
        </form>
      ) : (
        <p className="training-readonly">Only an administrator may queue training. All roles can inspect the resulting evidence.</p>
      )}
      {!datasets.length ? (
        <div className="training-no-dataset">
          No ready, integrity-verified snapshot is available.
          <Link href="/ml/datasets">Review dataset readiness →</Link>
        </div>
      ) : null}
      <div className="training-handoff-note">
        <span>After training</span>
        <p>Download the sealed payload and artifact, then perform the explicit registry handoff.</p>
        <Link href="/ml/models">Open Model Operations →</Link>
      </div>
    </aside>
  );
}

function artifactPath(runId: string, kind: ModelKind, artifact: string) {
  return `/api/ml-training-runs/${encodeURIComponent(runId)}/artifacts/${kind}/${artifact}`;
}

function evidencePath(runId: string, evidence: string) {
  return `/api/ml-training-runs/${encodeURIComponent(runId)}/evidence/${evidence}`;
}

function metric(metrics: Record<string, unknown>, key: string) {
  const value = metrics[key];
  return typeof value === "number" || typeof value === "string" ? String(value) : null;
}

function formatMetric(value: string | null) {
  if (value === null) return "—";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return value;
  return parsed <= 1 ? parsed.toFixed(3) : parsed.toLocaleString("en-US");
}

function formatPercent(value: string) {
  return `${(Number(value) * 100).toFixed(2).replace(/\.00$/, "")}%`;
}

function statusLabel(value: string) {
  return value === "succeeded" ? "Candidates sealed" : humanize(value);
}

function humanize(value: string) {
  const text = value.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function shortChecksum(value: string) {
  return `${value.slice(0, 12)}…`;
}

function formatTimestamp(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

function errorDetail(value: object, fallback: string) {
  return "detail" in value && typeof (value as ApiErrorResponse).detail === "string"
    ? (value as ApiErrorResponse).detail
    : fallback;
}
