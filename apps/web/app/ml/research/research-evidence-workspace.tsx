import type {
  ResearchCandidateEvidence,
  ResearchModelEvidence,
  ResearchPartitionEvidence,
} from "@fip/contracts";

export function ResearchEvidenceWorkspace({ evidence }: { evidence: ResearchModelEvidence }) {
  const selected = evidence.candidates.find((candidate) => candidate.selected);
  const maximumImportance = Math.max(
    ...evidence.explainability.features.map((feature) => Number(feature.mean_pr_auc_decrease)),
  );

  return (
    <div className="research-workspace">
      <section className="research-cover">
        <div className="research-cover-copy">
          <div className="research-folio">
            <span>{evidence.run_id}</span>
            <span>{formatDate(evidence.created_at)}</span>
          </div>
          <p className="eyebrow">Real-data model study · sealed result</p>
          <h2>A measured experiment, with its limits left visible.</h2>
          <p>
            Two candidates were trained on public transaction data with temporal isolation,
            probability calibration and a one-time held-out test. This record preserves both the
            result and the boundary that prevents research evidence becoming an operational claim.
          </p>
        </div>
        <div className="research-seal" aria-label="Research-only evidence">
          <span>{evidence.integrity_verified ? "Integrity verified" : "Integrity exception"}</span>
          <strong>R</strong>
          <p>Research only</p>
          <small>Not eligible for promotion</small>
        </div>
      </section>

      <section aria-label="Research run summary" className="research-summary">
        <SummaryMetric
          detail={`${evidence.dataset.positive_count.toLocaleString("en-US")} fraud labels`}
          label="Real transactions"
          value={evidence.dataset.row_count.toLocaleString("en-US")}
        />
        <SummaryMetric
          detail="time-ordered, no random leakage"
          label="Isolated windows"
          value={String(evidence.partitions.length)}
        />
        <SummaryMetric
          detail={`${selected?.display_name ?? "No candidate selected"}`}
          label="Candidates compared"
          value={String(evidence.candidates.length)}
        />
        <SummaryMetric
          detail={`${evidence.held_out_test.positive_count} fraud labels`}
          label="Untouched test rows"
          value={evidence.held_out_test.row_count.toLocaleString("en-US")}
        />
      </section>

      <section className="research-dataset">
        <div className="research-section-heading">
          <div>
            <p className="eyebrow">01 · Source dossier</p>
            <h3>{evidence.dataset.display_name}</h3>
          </div>
          <a href={evidence.dataset.source_page} rel="noreferrer" target="_blank">
            Inspect OpenML source ↗
          </a>
        </div>
        <div className="research-dataset-grid">
          <div className="research-source-note">
            <p>{evidence.dataset.provenance}</p>
            <span>{evidence.dataset.observation_period}</span>
          </div>
          <dl>
            <EvidenceRow label="Dataset ID" value={evidence.dataset.dataset_id} />
            <EvidenceRow label="Provider license" value={evidence.dataset.provider_license} />
            <EvidenceRow label="Features" value={String(evidence.dataset.feature_count)} />
            <EvidenceRow
              label="Class prevalence"
              value={percentage(evidence.dataset.prevalence, 3)}
            />
          </dl>
        </div>
      </section>

      <section className="research-partitions">
        <div className="research-section-heading">
          <div>
            <p className="eyebrow">02 · Temporal protocol</p>
            <h3>Every decision sees only the past.</h3>
          </div>
          <p>60 / 15 / 10 / 15 split</p>
        </div>
        <div className="research-timeline" aria-label="Temporal dataset partitions">
          {evidence.partitions.map((partition) => (
            <PartitionBand key={partition.name} partition={partition} />
          ))}
        </div>
        <ol className="research-partition-notes">
          {evidence.partitions.map((partition, index) => (
            <li key={partition.name}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div>
                <strong>{partition.name}</strong>
                <p>{partition.purpose}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="research-candidates">
        <div className="research-section-heading">
          <div>
            <p className="eyebrow">03 · Candidate decision</p>
            <h3>Selected under a constrained false-positive rate.</h3>
          </div>
          <p>Validation FPR ceiling ≤ 1.00%</p>
        </div>
        <div className="research-candidate-grid">
          {evidence.candidates.map((candidate) => (
            <CandidateCard candidate={candidate} key={candidate.model_key} />
          ))}
        </div>
      </section>

      <section className="research-test">
        <div className="research-test-title">
          <div>
            <p className="eyebrow">04 · Held-out result</p>
            <h3>One final measurement on later, untouched transactions.</h3>
          </div>
          <span>Test opened after selection</span>
        </div>
        <div className="research-test-layout">
          <div className="research-test-metrics">
            <TestMetric label="PR–AUC" value={percentage(evidence.held_out_test.average_precision)} />
            <TestMetric label="ROC–AUC" value={percentage(evidence.held_out_test.roc_auc)} />
            <TestMetric label="Recall" value={percentage(evidence.held_out_test.recall)} />
            <TestMetric
              label="False-positive rate"
              value={percentage(evidence.held_out_test.false_positive_rate, 2)}
            />
          </div>
          <div className="research-confusion">
            <p>Observed decisions at the selected threshold</p>
            <div className="research-confusion-grid">
              <ConfusionCell label="True positive" value={evidence.held_out_test.true_positives} />
              <ConfusionCell label="False negative" value={evidence.held_out_test.false_negatives} />
              <ConfusionCell label="False positive" value={evidence.held_out_test.false_positives} />
              <ConfusionCell label="True negative" value={evidence.held_out_test.true_negatives} />
            </div>
            <small>
              {percentage(evidence.held_out_test.alert_rate, 2)} alert rate · threshold {" "}
              {Number(evidence.held_out_test.threshold).toFixed(6)}
            </small>
          </div>
        </div>
      </section>

      <div className="research-evidence-columns">
        <section className="research-importance">
          <div className="research-section-heading">
            <div>
              <p className="eyebrow">05 · Diagnostic importance</p>
              <h3>Permutation evidence</h3>
            </div>
          </div>
          <ol>
            {evidence.explainability.features.map((feature, index) => (
              <li key={feature.feature}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{feature.feature}</strong>
                <div className="research-importance-track">
                  <i
                    style={{
                      width: `${(Number(feature.mean_pr_auc_decrease) / maximumImportance) * 100}%`,
                    }}
                  />
                </div>
                <code>{Number(feature.mean_pr_auc_decrease).toFixed(4)}</code>
              </li>
            ))}
          </ol>
          <p className="research-limit-note">{evidence.explainability.semantic_limit}</p>
        </section>

        <section className="research-reproducibility">
          <div className="research-section-heading">
            <div>
              <p className="eyebrow">06 · Reproduction register</p>
              <h3>Run identity</h3>
            </div>
          </div>
          <dl>
            <EvidenceRow label="Pipeline" value={evidence.reproducibility.pipeline_version} />
            <EvidenceRow label="Random seed" value={String(evidence.reproducibility.random_seed)} />
            <EvidenceRow label="Split contract" value={evidence.reproducibility.split_contract} />
            <EvidenceRow
              label="Runtime"
              value={`Python ${evidence.reproducibility.runtime.python} · sklearn ${evidence.reproducibility.runtime.scikit_learn}`}
            />
          </dl>
          <div className="research-checksums">
            <Checksum label="Evidence record" value={evidence.evidence_checksum} />
            <Checksum label="Source file" value={evidence.dataset.source_file_sha256} />
            <Checksum
              label="Model artifact"
              value={evidence.reproducibility.artifacts.model_artifact_sha256}
            />
            <Checksum
              label="Run manifest"
              value={evidence.reproducibility.artifacts.run_manifest_sha256}
            />
          </div>
        </section>
      </div>

      <section className="research-boundary">
        <div className="research-boundary-marker">Boundary</div>
        <div>
          <p className="eyebrow">Claims control</p>
          <h3>Real data does not make this an operational model.</h3>
          <p>{evidence.claims.statement}</p>
          <p>{evidence.dataset.operational_block_reason}</p>
        </div>
        <ul>
          <li>Cannot be promoted</li>
          <li>Does not alter a score</li>
          <li>Cannot trigger an action</li>
          <li>Does not claim institution efficacy</li>
        </ul>
      </section>

      <footer className="research-footnote">
        <span>{evidence.schema_version}</span>
        <span>{evidence.integrity_verified ? "Checksum verified" : "Checksum mismatch"}</span>
        <span>Read only · no operational state changed</span>
      </footer>
    </div>
  );
}

function SummaryMetric({ detail, label, value }: { detail: string; label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function PartitionBand({ partition }: { partition: ResearchPartitionEvidence }) {
  return (
    <div className={`research-partition research-partition-${partition.name}`}>
      <strong>{partition.name}</strong>
      <span>{partition.row_count.toLocaleString("en-US")}</span>
      <small>{partition.positive_count} positive</small>
    </div>
  );
}

function CandidateCard({ candidate }: { candidate: ResearchCandidateEvidence }) {
  return (
    <article className={candidate.selected ? "selected" : undefined}>
      <header>
        <div>
          <span>{candidate.model_key}</span>
          <h4>{candidate.display_name}</h4>
        </div>
        <strong>{candidate.selected ? "Selected" : "Compared"}</strong>
      </header>
      <dl>
        <EvidenceRow label="PR–AUC" value={percentage(candidate.validation.average_precision)} />
        <EvidenceRow label="Recall" value={percentage(candidate.validation.recall)} />
        <EvidenceRow
          label="False-positive rate"
          value={percentage(candidate.validation.false_positive_rate, 2)}
        />
        <EvidenceRow label="Brier score" value={candidate.validation.brier_score} />
      </dl>
    </article>
  );
}

function TestMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ConfusionCell({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value.toLocaleString("en-US")}</strong>
    </div>
  );
}

function EvidenceRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function Checksum({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <code title={value}>{value}</code>
    </div>
  );
}

function percentage(value: string, fractionDigits = 1) {
  return `${(Number(value) * 100).toFixed(fractionDigits)}%`;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(value));
}
