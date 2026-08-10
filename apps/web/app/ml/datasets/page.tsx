import type {
  DatasetReadiness,
  DatasetReadinessGate,
  OperationalDatasetSummary,
} from "@fip/contracts";
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth/server";
import { getCases } from "@/lib/cases/server";
import { getDatasetReadiness, getOperationalDatasets } from "@/lib/ml-datasets/server";

import { DatasetSnapshotAction } from "../../components/dataset-snapshot-action";
import { WorkspaceShell } from "../../components/workspace-shell";

export default async function MLDatasetsPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");

  const [readiness, datasets, cases] = await Promise.all([
    getDatasetReadiness(),
    getOperationalDatasets(),
    getCases(),
  ]);
  const activeCases = cases.filter((item) => item.status !== "classified");

  return (
    <WorkspaceShell
      activeNavigation="ml_datasets"
      eyebrow="Model evidence"
      reviewCount={activeCases.length}
      title="Operational ML datasets"
      user={user}
    >
      {readiness ? (
        <DatasetWorkbench
          canCreate={user.role === "administrator"}
          datasets={datasets}
          readiness={readiness}
        />
      ) : (
        <section className="dataset-unavailable">
          <p className="eyebrow">Evidence unavailable</p>
          <h2>The dataset ledger could not be reached.</h2>
          <p>Transaction scoring remains available; no training snapshot was created.</p>
        </section>
      )}
    </WorkspaceShell>
  );
}

function DatasetWorkbench({
  canCreate,
  datasets,
  readiness,
}: {
  canCreate: boolean;
  datasets: OperationalDatasetSummary[];
  readiness: DatasetReadiness;
}) {
  const passedGates = readiness.gates.filter((gate) => gate.passed).length;
  return (
    <div className="dataset-workbench">
      <section className="dataset-intro">
        <div className="dataset-intro-copy">
          <p className="eyebrow">Governed training evidence</p>
          <h2>A dataset must earn readiness.</h2>
          <p>
            Only independently approved binary outcomes and pre-decision semantic features enter
            this ledger. A sealed snapshot records evidence; it never starts model training.
          </p>
        </div>
        <div className={`readiness-seal readiness-${readiness.readiness_status}`}>
          <span>{readiness.readiness_status === "ready" ? "Training ready" : "Training blocked"}</span>
          <strong>
            {passedGates}<small>/{readiness.gates.length}</small>
          </strong>
          <p>readiness gates passed</p>
        </div>
      </section>

      <section aria-label="Dataset readiness counts" className="dataset-metrics">
        <DatasetMetric label="Eligible labels" value={readiness.eligible_label_count} />
        <DatasetMetric label="Confirmed fraud" value={readiness.positive_label_count} />
        <DatasetMetric label="Legitimate" value={readiness.negative_label_count} />
        <DatasetMetric label="Excluded evidence" value={excludedCount(readiness)} />
      </section>

      <div className="dataset-grid">
        <section className="gate-ledger">
          <header>
            <div>
              <p className="eyebrow">Readiness ledger</p>
              <h3>Admission gates</h3>
            </div>
            <span>As of {formatDateTime(readiness.cutoff_at)}</span>
          </header>
          <ol>
            {readiness.gates.map((gate, index) => (
              <GateRecord gate={gate} index={index + 1} key={gate.gate} />
            ))}
          </ol>
        </section>

        <aside className="dataset-curation-card">
          <p className="eyebrow">Snapshot control</p>
          <h3>Freeze the evidence, not the model.</h3>
          <p>
            A snapshot pins source reviews, the allow-listed feature schema, chronological splits,
            readiness results and every row checksum.
          </p>
          <dl>
            <div>
              <dt>Feature contract</dt>
              <dd>{readiness.feature_set_version}</dd>
            </div>
            <div>
              <dt>Label contract</dt>
              <dd>{readiness.label_contract_version}</dd>
            </div>
          </dl>
          <DatasetSnapshotAction
            canCreate={canCreate}
            eligibleLabelCount={readiness.eligible_label_count}
          />
        </aside>
      </div>

      <DatasetArchive datasets={datasets} />
    </div>
  );
}

function DatasetMetric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value.toLocaleString("en-US")}</strong>
    </div>
  );
}

function GateRecord({ gate, index }: { gate: DatasetReadinessGate; index: number }) {
  return (
    <li className={gate.passed ? "gate-passed" : "gate-blocked"}>
      <span className="gate-index">{String(index).padStart(2, "0")}</span>
      <span className="gate-state" aria-label={gate.passed ? "Passed" : "Blocked"}>
        {gate.passed ? "✓" : "×"}
      </span>
      <span className="gate-copy">
        <strong>{gateLabel(gate.gate)}</strong>
        <small>{gate.detail}</small>
      </span>
      <span className="gate-measure">
        <strong>{formatObserved(gate.observed)}</strong>
        <small>Required {gate.required}</small>
      </span>
    </li>
  );
}

function DatasetArchive({ datasets }: { datasets: OperationalDatasetSummary[] }) {
  return (
    <section className="dataset-archive">
      <header>
        <div>
          <p className="eyebrow">Immutable archive</p>
          <h3>Dataset snapshots</h3>
        </div>
        <span>{datasets.length} sealed records</span>
      </header>
      {datasets.length ? (
        <ol>
          {datasets.map((dataset) => (
            <li key={dataset.id}>
              <span className="archive-reference">
                <strong>{dataset.display_id}</strong>
                <small>{formatDateTime(dataset.created_at)}</small>
              </span>
              <span className="archive-composition">
                <strong>{dataset.row_count} reviewed labels</strong>
                <small>
                  {dataset.positive_count} fraud · {dataset.negative_count} legitimate
                </small>
              </span>
              <span className="archive-splits">
                <strong>
                  {dataset.split_counts.train}/{dataset.split_counts.validation}/
                  {dataset.split_counts.test}
                </strong>
                <small>train / validation / test</small>
              </span>
              <span className={`archive-status readiness-${dataset.readiness_status}`}>
                {dataset.readiness_status}
              </span>
              <code title={dataset.dataset_checksum}>{dataset.dataset_checksum.slice(0, 12)}…</code>
              <span className={dataset.integrity_verified ? "archive-verified" : "archive-damaged"}>
                {dataset.integrity_verified ? "verified" : "integrity failed"}
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <div className="dataset-archive-empty">
          No manifest has been sealed. Readiness evidence remains live until an administrator
          creates the first snapshot.
        </div>
      )}
    </section>
  );
}

function excludedCount(readiness: DatasetReadiness) {
  return (
    readiness.excluded_integrity_failures +
    readiness.excluded_feature_contract_mismatches +
    readiness.excluded_temporal_leakage
  );
}

function gateLabel(value: string) {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatObserved(value: unknown) {
  if (typeof value === "number" || typeof value === "string") return String(value);
  if (value && typeof value === "object") {
    return Object.entries(value)
      .map(([key, counts]) => {
        if (!counts || typeof counts !== "object") return key;
        const values = counts as Record<string, number>;
        return `${key.slice(0, 3)} ${values.fraud ?? 0}/${values.legitimate ?? 0}`;
      })
      .join(" · ");
  }
  return "—";
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}
