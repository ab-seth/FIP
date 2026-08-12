"use client";

import type {
  ApiErrorResponse,
  BenchmarkRun,
  BenchmarkRunCreationResponse,
  UserRole,
} from "@fip/contracts";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

export function BenchmarkWorkspace({ role, runs }: { role: UserRole; runs: BenchmarkRun[] }) {
  const router = useRouter();
  const active = runs.filter((run) => run.status === "queued" || run.status === "running");
  const accepted = runs.filter((run) => run.result?.acceptance_met && run.integrity_verified);

  useEffect(() => {
    if (!active.length) return;
    const timer = window.setInterval(() => router.refresh(), 4000);
    return () => window.clearInterval(timer);
  }, [active.length, router]);

  return (
    <div className="benchmark-workspace">
      <section className="benchmark-cover">
        <div>
          <p className="eyebrow">Fixed-seed system exercise</p>
          <h2>Measure the pipeline. Keep the claim narrow.</h2>
          <p>
            Synthetic transactions pass through the real validation, deterministic scoring and
            case-routing path. Results demonstrate measured system behavior—not fraud-model
            efficacy.
          </p>
        </div>
        <div className="benchmark-boundary">
          <span>Evidence boundary</span>
          <strong>Synthetic</strong>
          <small>Never eligible for training</small>
        </div>
      </section>

      <section className="benchmark-metrics" aria-label="Benchmark summary">
        <Metric label="Runs" value={runs.length} />
        <Metric label="In progress" value={active.length} />
        <Metric label="Accepted" value={accepted.length} />
        <Metric
          label="Largest verified run"
          value={Math.max(0, ...runs.filter((run) => run.integrity_verified).map((run) => run.transaction_count))}
        />
      </section>

      <div className="benchmark-layout">
        <section className="benchmark-ledger">
          <header>
            <div><p className="eyebrow">Immutable run ledger</p><h3>Benchmark evidence</h3></div>
            <span>{runs.length} configurations</span>
          </header>
          {runs.length ? (
            <ol>
              {runs.map((run) => <BenchmarkRecord key={run.id} role={role} run={run} />)}
            </ol>
          ) : (
            <div className="benchmark-empty">
              <span>00</span><h4>No benchmark evidence yet.</h4>
              <p>Queue the 10,000-transaction acceptance run to establish the first baseline.</p>
            </div>
          )}
        </section>
        <BenchmarkRequest role={role} />
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div><span>{label}</span><strong>{value.toLocaleString("en-US")}</strong></div>;
}

function BenchmarkRecord({ role, run }: { role: UserRole; run: BenchmarkRun }) {
  const result = run.result;
  return (
    <li className={`benchmark-record benchmark-record-${run.status}`}>
      <header>
        <div>
          <span>{run.display_id}</span>
          <h4>{run.transaction_count.toLocaleString("en-US")} transaction run</h4>
          <small>Seed {run.seed} · requested by {run.requested_by}</small>
        </div>
        <div className="benchmark-state">
          <strong>{statusLabel(run.status)}</strong>
          <small>{formatTimestamp(run.completed_at ?? run.started_at ?? run.created_at)}</small>
        </div>
      </header>

      {!run.integrity_verified ? (
        <p className="benchmark-alert">This run does not currently pass evidence verification.</p>
      ) : null}
      {run.status === "queued" || run.status === "running" ? (
        <div className="benchmark-progress"><i /><span>{run.status === "queued" ? "Waiting for the benchmark worker" : "Scoring and sealing evidence"}</span></div>
      ) : null}
      {run.status === "failed" ? (
        <div className="benchmark-failure">
          <p><strong>{humanize(run.error_code ?? "execution failed")}</strong><br />{run.error_message}</p>
          {role === "administrator" ? <RetryButton runId={run.id} /> : null}
        </div>
      ) : null}
      {result ? (
        <div className="benchmark-result">
          <div className={result.acceptance_met ? "benchmark-verdict-pass" : "benchmark-verdict-pending"}>
            <span>Acceptance</span><strong>{result.acceptance_met ? "Met" : "Not met"}</strong>
          </div>
          <dl>
            <Result label="Processed" value={result.processed_transaction_count.toLocaleString("en-US")} />
            <Result label="Maximum score time" value={formatMilliseconds(result.maximum_scoring_milliseconds)} />
            <Result label="p95 score time" value={formatMilliseconds(result.p95_scoring_milliseconds)} />
            <Result label="Pipeline elapsed" value={formatMilliseconds(result.elapsed_milliseconds)} />
            <Result label="Cases opened" value={result.opened_case_count.toLocaleString("en-US")} />
            <Result label="Throughput / sec" value={result.throughput_per_second ?? "Recovery run"} />
          </dl>
          <a download href={`/api/evaluation/benchmarks/${encodeURIComponent(run.id)}/report`}>
            Download sealed report
          </a>
        </div>
      ) : null}

      <details>
        <summary>Configuration and checksum chain</summary>
        <dl className="benchmark-proofs">
          <Result label="Generator" value={run.generator_version} />
          <Result label="Configuration" value={shortChecksum(run.configuration_checksum)} />
          <Result label="Dataset" value={shortChecksum(run.dataset_checksum)} />
          <Result label="Report" value={run.report_checksum ? shortChecksum(run.report_checksum) : "Pending"} />
        </dl>
        <ol className="benchmark-events">
          {run.events.map((event) => (
            <li key={event.event_checksum}>
              <span>{String(event.sequence_number).padStart(2, "0")}</span>
              <div><strong>{statusLabel(event.to_status)}</strong><p>{event.detail}</p><small>{event.actor_username}</small></div>
              <code>{shortChecksum(event.event_checksum)}</code>
            </li>
          ))}
        </ol>
      </details>
      <footer><span>Synthetic only</span><span>Excluded from training</span><span>No model-efficacy claim</span></footer>
    </li>
  );
}

function Result({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function BenchmarkRequest({ role }: { role: UserRole }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true); setMessage(null);
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch("/api/evaluation/benchmarks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transaction_count: Number(form.get("transaction_count")),
          seed: Number(form.get("seed")),
          reason: String(form.get("reason")),
        }),
      });
      const body = (await response.json()) as BenchmarkRunCreationResponse | ApiErrorResponse;
      if (!response.ok) throw new Error("detail" in body ? body.detail : "Request failed.");
      setMessage("created" in body && body.created ? "Benchmark queued." : "Matching run already exists.");
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Request failed.");
    } finally { setPending(false); }
  }
  return (
    <aside className="benchmark-request">
      <p className="eyebrow">New measurement</p><h3>Queue benchmark</h3>
      <p>The acceptance profile uses all 10,000 permitted transactions and a pinned seed.</p>
      {role === "administrator" ? (
        <form onSubmit={submit}>
          <label>Transactions<input defaultValue="10000" max="10000" min="100" name="transaction_count" type="number" /></label>
          <label>Random seed<input defaultValue="42" min="0" name="seed" type="number" /></label>
          <label>Evidence purpose<textarea defaultValue="Establish reproducible end-to-end system benchmark evidence." minLength={12} name="reason" /></label>
          <button disabled={pending} type="submit">{pending ? "Queuing…" : "Queue measured run"}</button>
          {message ? <p className="benchmark-message" role="status">{message}</p> : null}
        </form>
      ) : <p className="benchmark-role-note">Administrator access is required to queue a run.</p>}
      <div className="benchmark-policy"><strong>Evidence policy</strong><p>Synthetic labels and analyst outcomes from these rows are always rejected by the operational training-data boundary.</p></div>
    </aside>
  );
}

function RetryButton({ runId }: { runId: string }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  return <button disabled={pending} onClick={async () => { setPending(true); await fetch(`/api/evaluation/benchmarks/${encodeURIComponent(runId)}/retry`, { method: "POST" }); router.refresh(); setPending(false); }} type="button">{pending ? "Queuing…" : "Retry"}</button>;
}

function statusLabel(value: string) { return humanize(value); }
function humanize(value: string) { return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase()); }
function shortChecksum(value: string) { return `${value.slice(0, 8)}…${value.slice(-6)}`; }
function formatTimestamp(value: string) { return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
function formatMilliseconds(value: string | number | null) { return value === null ? "Not observed" : `${value} ms`; }
