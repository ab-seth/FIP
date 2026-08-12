"use client";

import type {
  ApiErrorResponse,
  ModelArtifactInstallationResponse,
  ModelLifecycleStatus,
  ModelRegistrationPayload,
  ModelRegistrationResponse,
  RegisteredModel,
  ShadowEvaluationCreationResponse,
  ShadowEvaluationReport,
  ShadowRunResponse,
  UserRole,
} from "@fip/contracts";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useMemo, useState } from "react";

import type { ModelOperationsRecord } from "./page";

type ActionMessage = { error: boolean; text: string } | null;

export function ModelOperations({
  records,
  role,
}: {
  records: ModelOperationsRecord[];
  role: UserRole;
}) {
  const installedCount = records.filter((record) => record.artifact?.integrity_verified).length;
  const shadowCount = records.filter((record) => record.model.current_status === "shadow").length;
  const verifiedCount = records.filter((record) => record.model.lineage_verified).length;

  return (
    <div className="model-ops-workspace">
      <section className="model-ops-cover">
        <div>
          <p className="eyebrow">Governed execution</p>
          <h2>Models enter evidence before they enter trust.</h2>
          <p>
            Candidate metadata, executable bytes and lifecycle authority remain separate. Every
            shadow prediction is advisory and leaves the deterministic risk score unchanged.
          </p>
        </div>
        <div className="model-ops-boundary">
          <span>Control boundary</span>
          <strong>Shadow only</strong>
          <small>No automated action</small>
        </div>
      </section>

      <section aria-label="Model operations summary" className="model-ops-metrics">
        <ModelMetric label="Registered versions" value={records.length} />
        <ModelMetric label="Verified lineages" value={verifiedCount} />
        <ModelMetric label="Installed artifacts" value={installedCount} />
        <ModelMetric label="Shadow models" value={shadowCount} />
      </section>

      <div className="model-ops-layout">
        <section className="model-registry">
          <header className="model-ops-section-header">
            <div>
              <p className="eyebrow">Immutable register</p>
              <h3>Model versions</h3>
            </div>
            <span>{records.length} records</span>
          </header>
          {records.length ? (
            <ol className="model-record-list">
              {records.map((record, index) => (
                <ModelRecord index={index + 1} key={record.model.id} record={record} role={role} />
              ))}
            </ol>
          ) : (
            <div className="model-registry-empty">
              <span>00</span>
              <h4>No candidate has been registered.</h4>
              <p>
                Train from a ready operational dataset, then submit the generated registration
                payload here. Research-only artifacts cannot enter shadow execution.
              </p>
            </div>
          )}
        </section>

        <aside className="model-intake-panel">
          <p className="eyebrow">Administrative handoff</p>
          <h3>Register a candidate bundle.</h3>
          <p>
            Training Operations produces immutable metadata and executable bytes. Registration
            records the metadata only; it does not load or run the artifact.
          </p>
          <Link className="model-training-link" href="/ml/training">
            Open sealed training handoffs →
          </Link>
          <ol className="model-intake-steps">
            <li><span>1</span> Select `registration-payload.json`.</li>
            <li><span>2</span> Install the checksum-matching `.joblib`.</li>
            <li><span>3</span> A different evaluator admits it to shadow.</li>
          </ol>
          <CandidateRegistration canRegister={role === "administrator"} />
        </aside>
      </div>
    </div>
  );
}

function ModelMetric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value.toLocaleString("en-US")}</strong>
    </div>
  );
}

function CandidateRegistration({ canRegister }: { canRegister: boolean }) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<ActionMessage>(null);

  if (!canRegister) {
    return (
      <p className="model-control-note">
        Only administrators register immutable candidate metadata. Evaluators retain independent
        lifecycle authority.
      </p>
    );
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    setPending(true);
    setMessage(null);
    try {
      const payload = JSON.parse(await file.text()) as Partial<ModelRegistrationPayload>;
      if (!isRegistrationPayload(payload)) {
        setMessage({ error: true, text: "This file is not an FIP registration payload." });
        return;
      }
      const response = await fetch("/api/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = (await response.json()) as ModelRegistrationResponse | ApiErrorResponse;
      if (!response.ok) {
        setMessage({ error: true, text: errorDetail(result, "Registration was rejected.") });
        return;
      }
      const registration = result as ModelRegistrationResponse;
      setMessage({
        error: false,
        text: registration.created
          ? `${registration.model.model_key} ${registration.model.version} was registered as a candidate.`
          : "This exact candidate registration already exists.",
      });
      setFile(null);
      router.refresh();
    } catch {
      setMessage({ error: true, text: "The registration payload is not valid JSON." });
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="model-registration-form" onSubmit={submit}>
      <label className="model-file-control" htmlFor="registration-payload">
        <span>Registration payload</span>
        <strong>{file?.name ?? "Choose JSON file"}</strong>
        <input
          accept="application/json,.json"
          id="registration-payload"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          type="file"
        />
      </label>
      <button className="dossier-button dossier-button-primary" disabled={!file || pending} type="submit">
        {pending ? "Verifying metadata…" : "Register candidate"}
      </button>
      <ActionNotice message={message} />
    </form>
  );
}

function ModelRecord({
  index,
  record,
  role,
}: {
  index: number;
  record: ModelOperationsRecord;
  role: UserRole;
}) {
  const { artifact, evaluations, model } = record;
  const latestEvent = model.lifecycle.at(-1);
  const isOperator = role === "administrator" || role === "evaluator";
  return (
    <li className="model-record">
      <header className="model-record-header">
        <span className="model-record-index">{String(index).padStart(2, "0")}</span>
        <span className={`model-kind-mark model-kind-${model.kind}`} aria-hidden="true">
          {model.kind === "supervised" ? "S" : "A"}
        </span>
        <div className="model-record-title">
          <span>{model.purpose} · {model.kind}</span>
          <h4>{model.model_key}</h4>
          <small>version {model.version}</small>
        </div>
        <div className="model-record-state">
          <span className={`model-status model-status-${model.current_status}`}>
            {model.current_status}
          </span>
          <small>{model.lineage_verified ? "Lineage verified" : "Integrity failed"}</small>
        </div>
      </header>

      <div className="model-record-facts">
        <ModelFact label="Feature contract" value={model.feature_set_version} />
        <ModelFact label="Training dataset" value={model.training_dataset_id} />
        <ModelFact label="Decision threshold" value={model.decision_threshold ?? "Not declared"} />
        <ModelFact label="Registered by" value={model.registered_by} />
      </div>

      <div className="model-evidence-strip">
        <EvidenceFlag
          label="Artifact"
          passed={Boolean(artifact?.integrity_verified)}
          value={artifactLabel(artifact)}
        />
        <EvidenceFlag
          label="Training approval"
          passed={model.training_data_approved}
          value={model.training_data_approved ? "Approved" : "Not approved"}
        />
        <EvidenceFlag
          label="Feature compatibility"
          passed={model.operational_feature_compatible}
          value={model.operational_feature_compatible ? "Compatible" : "Incompatible"}
        />
        <EvidenceFlag
          label="Monitoring reports"
          passed={evaluations.some((report) => report.integrity_verified)}
          value={`${evaluations.length} sealed`}
        />
      </div>

      <details className="model-record-detail">
        <summary>
          <span>Evidence and controls</span>
          <small>Checksums · lifecycle · operator actions</small>
        </summary>
        <div className="model-record-detail-body">
          <section className="model-lineage">
            <p className="eyebrow">Lifecycle record</p>
            <ol>
              {model.lifecycle.map((event) => (
                <li key={event.event_checksum}>
                  <span>{String(event.sequence_number).padStart(2, "0")}</span>
                  <div>
                    <strong>{humanize(event.to_status)}</strong>
                    <p>{event.reason}</p>
                    <small>{event.actor_username} · {formatDateTime(event.created_at)}</small>
                  </div>
                  <code title={event.event_checksum}>{shortChecksum(event.event_checksum)}</code>
                </li>
              ))}
            </ol>
          </section>

          <section className="model-checksum-ledger">
            <p className="eyebrow">Pinned evidence</p>
            <dl>
              <ChecksumFact label="Registration" value={model.registration_checksum} />
              <ChecksumFact label="Artifact" value={model.artifact_sha256} />
              <ChecksumFact label="Dataset" value={model.training_dataset_checksum} />
              <ChecksumFact label="Model card" value={model.model_card_checksum} />
            </dl>
            <p className="model-card-reference">Model card: {model.model_card_reference}</p>
          </section>

          {isOperator ? (
            <section className="model-control-deck">
              <header>
                <div>
                  <p className="eyebrow">Role-gated controls</p>
                  <h5>Operator actions</h5>
                </div>
                <span>{humanize(role)}</span>
              </header>
              <ArtifactInstallation model={model} role={role} verified={Boolean(artifact?.integrity_verified)} />
              <LifecycleControl
                artifactVerified={Boolean(artifact?.integrity_verified)}
                key={model.current_status}
                model={model}
                role={role}
              />
              <ShadowRunControl
                artifactVerified={Boolean(artifact?.integrity_verified)}
                model={model}
                role={role}
              />
              <EvaluationControl model={model} reports={evaluations} role={role} />
            </section>
          ) : (
            <p className="model-control-note model-control-note-wide">
              This account has read-only access to model evidence. Administrator and evaluator
              controls remain separated by role.
            </p>
          )}
        </div>
      </details>

      <footer className="model-record-footer">
        <span>Registered {formatDateTime(model.created_at)}</span>
        <span>{latestEvent ? `Latest authority: ${latestEvent.actor_username}` : "Lifecycle unavailable"}</span>
        <span>Shadow output cannot change case priority</span>
      </footer>
    </li>
  );
}

function ModelFact({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong title={value}>{value}</strong></div>;
}

function EvidenceFlag({ label, passed, value }: { label: string; passed: boolean; value: string }) {
  return (
    <div className={passed ? "evidence-flag-passed" : "evidence-flag-pending"}>
      <span>{passed ? "✓" : "·"}</span>
      <div><small>{label}</small><strong>{value}</strong></div>
    </div>
  );
}

function ChecksumFact({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd><code title={value}>{shortChecksum(value)}</code></dd></div>;
}

function ArtifactInstallation({
  model,
  role,
  verified,
}: {
  model: RegisteredModel;
  role: UserRole;
  verified: boolean;
}) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<ActionMessage>(null);

  if (role !== "administrator" || model.purpose !== "operational") return null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    setPending(true);
    setMessage(null);
    try {
      const response = await fetch(`/api/models/${encodeURIComponent(model.id)}/artifact`, {
        method: "PUT",
        headers: { "Content-Type": "application/octet-stream" },
        body: await file.arrayBuffer(),
      });
      const result = (await response.json()) as ModelArtifactInstallationResponse | ApiErrorResponse;
      if (!response.ok) {
        setMessage({ error: true, text: errorDetail(result, "Artifact installation failed.") });
        return;
      }
      const installation = result as ModelArtifactInstallationResponse;
      setMessage({
        error: false,
        text: installation.installed
          ? `Artifact installed and SHA-256 verified (${formatBytes(installation.size_bytes)}).`
          : "The exact verified artifact was already installed.",
      });
      setFile(null);
      router.refresh();
    } catch {
      setMessage({ error: true, text: "The artifact service is temporarily unavailable." });
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="model-control-form" onSubmit={submit}>
      <div className="model-control-copy">
        <span>01</span>
        <div><strong>Install executable artifact</strong><small>Administrator · checksum verified before storage</small></div>
      </div>
      <label className="compact-file-control">
        <span>{file?.name ?? (verified ? "Verified artifact installed" : "Choose .joblib")}</span>
        <input
          accept=".joblib,application/octet-stream"
          disabled={verified}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          type="file"
        />
      </label>
      <button className="model-control-button" disabled={!file || pending || verified} type="submit">
        {pending ? "Installing…" : "Install"}
      </button>
      <ActionNotice message={message} />
    </form>
  );
}

function LifecycleControl({
  artifactVerified,
  model,
  role,
}: {
  artifactVerified: boolean;
  model: RegisteredModel;
  role: UserRole;
}) {
  const router = useRouter();
  const options = transitionOptions(model, role);
  const [target, setTarget] = useState<ModelLifecycleStatus | "">(options[0] ?? "");
  const [reason, setReason] = useState(defaultTransitionReason(options[0] ?? ""));
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<ActionMessage>(null);
  const shadowAdmissionReady =
    artifactVerified &&
    model.lineage_verified &&
    model.training_data_approved &&
    model.operational_feature_compatible &&
    model.decision_threshold !== null;
  const shadowBlocked = target === "shadow" && !shadowAdmissionReady;

  if (!options.length) return null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!target) return;
    setPending(true);
    setMessage(null);
    try {
      const response = await fetch(`/api/models/${encodeURIComponent(model.id)}/transitions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_status: target, reason }),
      });
      const result = (await response.json()) as RegisteredModel | ApiErrorResponse;
      if (!response.ok) {
        setMessage({ error: true, text: errorDetail(result, "Lifecycle transition was rejected.") });
        return;
      }
      setMessage({ error: false, text: `Lifecycle advanced to ${humanize(target)}.` });
      router.refresh();
    } catch {
      setMessage({ error: true, text: "The lifecycle service is temporarily unavailable." });
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="model-control-form model-lifecycle-form" onSubmit={submit}>
      <div className="model-control-copy">
        <span>02</span>
        <div><strong>Record lifecycle decision</strong><small>{target === "shadow" ? "Independent evaluator authority" : "Irreversible terminal decision"}</small></div>
      </div>
      <select
        aria-label="Lifecycle target"
        onChange={(event) => {
          const value = event.target.value as ModelLifecycleStatus;
          setTarget(value);
          setReason(defaultTransitionReason(value));
        }}
        value={target}
      >
        {options.map((option) => <option key={option} value={option}>{humanize(option)}</option>)}
      </select>
      <textarea
        aria-label="Lifecycle decision reason"
        maxLength={500}
        minLength={12}
        onChange={(event) => setReason(event.target.value)}
        rows={2}
        value={reason}
      />
      <button className="model-control-button" disabled={pending || shadowBlocked} type="submit">
        {pending ? "Recording…" : `Record ${target}`}
      </button>
      {shadowBlocked ? (
        <p className="model-form-hint">
          A verified artifact, intact lineage, approved training data, compatible features and a
          comparison threshold are required before shadow admission.
        </p>
      ) : null}
      <ActionNotice message={message} />
    </form>
  );
}

function ShadowRunControl({
  artifactVerified,
  model,
  role,
}: {
  artifactVerified: boolean;
  model: RegisteredModel;
  role: UserRole;
}) {
  const router = useRouter();
  const [limit, setLimit] = useState(100);
  const [transactionIds, setTransactionIds] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<ActionMessage>(null);

  if (
    model.current_status !== "shadow" ||
    (role !== "administrator" && role !== "evaluator")
  ) return null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ids = transactionIds.split(/[\n,]+/).map((value) => value.trim()).filter(Boolean);
    if (ids.length > 1000) {
      setMessage({ error: true, text: "A shadow run can name at most 1,000 transactions." });
      return;
    }
    setPending(true);
    setMessage(null);
    try {
      const payload = ids.length ? { transaction_ids: ids } : { limit };
      const response = await fetch(`/api/models/${encodeURIComponent(model.id)}/shadow-runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = (await response.json()) as ShadowRunResponse | ApiErrorResponse;
      if (!response.ok) {
        setMessage({ error: true, text: errorDetail(result, "Shadow execution was rejected.") });
        return;
      }
      const run = result as ShadowRunResponse;
      setMessage({
        error: false,
        text: `${run.created_count} new and ${run.replayed_count} existing shadow predictions returned.`,
      });
      router.refresh();
    } catch {
      setMessage({ error: true, text: "The shadow runtime is temporarily unavailable." });
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="model-control-form model-shadow-form" onSubmit={submit}>
      <div className="model-control-copy">
        <span>03</span>
        <div><strong>Run shadow inference</strong><small>Advisory output · no queue or score changes</small></div>
      </div>
      <label><span>Automatic batch limit</span><input max={1000} min={1} onChange={(event) => setLimit(Number(event.target.value))} type="number" value={limit} /></label>
      <label><span>Or transaction UUIDs</span><textarea onChange={(event) => setTransactionIds(event.target.value)} placeholder="One UUID per line" rows={2} value={transactionIds} /></label>
      <button className="model-control-button" disabled={pending || !artifactVerified} type="submit">
        {pending ? "Running shadow…" : "Run shadow"}
      </button>
      {!artifactVerified ? <p className="model-form-hint">A verified artifact is required for execution.</p> : null}
      <ActionNotice message={message} />
    </form>
  );
}

function EvaluationControl({
  model,
  reports,
  role,
}: {
  model: RegisteredModel;
  reports: ShadowEvaluationReport[];
  role: UserRole;
}) {
  const router = useRouter();
  const [windows, setWindows] = useState({
    baseline_window_start: "",
    baseline_window_end: "",
    evaluation_window_start: "",
    evaluation_window_end: "",
  });
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<ActionMessage>(null);
  const fields = useMemo(() => Object.keys(windows) as Array<keyof typeof windows>, [windows]);

  if (role !== "evaluator" || model.current_status !== "shadow") return null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setMessage(null);
    try {
      const payload = Object.fromEntries(
        fields.map((field) => [field, new Date(windows[field]).toISOString()]),
      );
      const response = await fetch(`/api/models/${encodeURIComponent(model.id)}/evaluations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = (await response.json()) as ShadowEvaluationCreationResponse | ApiErrorResponse;
      if (!response.ok) {
        setMessage({ error: true, text: errorDetail(result, "Evaluation was not sealed.") });
        return;
      }
      const evaluation = result as ShadowEvaluationCreationResponse;
      setMessage({
        error: false,
        text: evaluation.created
          ? `Monitoring report sealed with ${evaluation.report.evaluation_prediction_count} evaluation predictions.`
          : "This exact monitoring window already exists.",
      });
      router.refresh();
    } catch {
      setMessage({ error: true, text: "Enter four valid, non-overlapping date-time values." });
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="model-control-form model-evaluation-form" onSubmit={submit}>
      <div className="model-control-copy">
        <span>04</span>
        <div><strong>Seal monitoring report</strong><small>{reports.length} existing · minimum 20 verified predictions per window</small></div>
      </div>
      <div className="evaluation-window-grid">
        {fields.map((field) => (
          <label key={field}>
            <span>{humanize(field)}</span>
            <input
              onChange={(event) => setWindows((current) => ({ ...current, [field]: event.target.value }))}
              required
              type="datetime-local"
              value={windows[field]}
            />
          </label>
        ))}
      </div>
      <button className="model-control-button" disabled={pending} type="submit">
        {pending ? "Evaluating…" : "Seal evaluation"}
      </button>
      <ActionNotice message={message} />
    </form>
  );
}

function ActionNotice({ message }: { message: ActionMessage }) {
  return message ? (
    <p className={`model-action-message ${message.error ? "is-error" : "is-success"}`}>
      {message.text}
    </p>
  ) : null;
}

function transitionOptions(model: RegisteredModel, role: UserRole): ModelLifecycleStatus[] {
  if (model.current_status === "candidate") {
    return role === "evaluator"
      ? model.purpose === "operational"
        ? ["shadow", "rejected"]
        : ["rejected"]
      : role === "administrator"
        ? ["rejected"]
        : [];
  }
  if (
    model.current_status === "shadow" &&
    (role === "administrator" || role === "evaluator")
  ) {
    return ["retired", "rejected"];
  }
  return [];
}

function defaultTransitionReason(target: ModelLifecycleStatus | "") {
  if (target === "shadow") return "Independent evaluator approved monitoring-only shadow execution.";
  if (target === "retired") return "Model version retired from all future shadow execution.";
  if (target === "rejected") return "Model evidence did not satisfy the required governance review.";
  return "";
}

function isRegistrationPayload(value: Partial<ModelRegistrationPayload>): value is ModelRegistrationPayload {
  return Boolean(
    value &&
    typeof value.model_key === "string" &&
    typeof value.version === "string" &&
    typeof value.artifact_sha256 === "string" &&
    typeof value.training_dataset_checksum === "string" &&
    typeof value.model_card_checksum === "string",
  );
}

function errorDetail(value: object, fallback: string) {
  return "detail" in value && typeof (value as ApiErrorResponse).detail === "string"
    ? (value as ApiErrorResponse).detail
    : fallback;
}

function artifactLabel(artifact: ModelOperationsRecord["artifact"]) {
  if (!artifact) return "Status unavailable";
  if (!artifact.installed) return "Not installed";
  if (!artifact.integrity_verified) return "Integrity failed";
  return artifact.size_bytes === null ? "Verified" : formatBytes(artifact.size_bytes);
}

function humanize(value: string) {
  return value.split("_").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
}

function shortChecksum(value: string) {
  return `${value.slice(0, 12)}…`;
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
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
