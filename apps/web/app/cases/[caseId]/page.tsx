import type { CaseDetail, CaseEvent } from "@fip/contracts";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth/server";
import { getCase, getCases, getShadowPredictions } from "@/lib/cases/server";

import { CaseActions } from "../../components/case-actions";
import { GroundedCaseBrief } from "../../components/case-brief";
import { HybridRiskEvidence } from "../../components/hybrid-risk-evidence";
import { WorkspaceShell } from "../../components/workspace-shell";

export default async function CaseDossierPage({
  params,
}: {
  params: Promise<{ caseId: string }>;
}) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const { caseId } = await params;
  const [caseDetail, cases] = await Promise.all([getCase(caseId), getCases()]);
  if (!caseDetail) notFound();
  const shadowPredictions = await getShadowPredictions(caseDetail.transaction.id);
  const reviewCount = cases.filter((item) => item.status !== "classified").length;

  return (
    <WorkspaceShell
      activeNavigation="case_dossiers"
      eyebrow="Evidence dossier"
      reviewCount={reviewCount}
      title={caseDetail.display_id}
      user={user}
    >
      <div className="dossier-nav">
        <Link href="/">← Return to case register</Link>
        <span className={`case-status status-${caseDetail.status}`}>{statusLabel(caseDetail.status)}</span>
      </div>

      <article className="dossier" id="dossier">
        <header className="dossier-heading">
          <div>
            <p className="eyebrow">Transaction under review</p>
            <h2>{caseDetail.transaction.external_transaction_id}</h2>
            <p>{caseDetail.opening_reason}</p>
          </div>
          <div className={`dossier-score risk-${caseDetail.risk_level}`}>
            <strong>{caseDetail.risk_score}</strong>
            <span>rules-only risk</span>
          </div>
        </header>

        {!caseDetail.integrity_verified ? (
          <div className="integrity-warning" role="alert">
            <strong>Evidence integrity warning</strong>
            <span>The hash chain or referenced evidence no longer verifies. New case actions are blocked.</span>
          </div>
        ) : null}

        <section className="dossier-facts" aria-label="Transaction facts">
          <Fact label="Amount" value={formatAmount(caseDetail.transaction.amount, caseDetail.transaction.currency)} />
          <Fact label="Occurred" value={formatTimestamp(caseDetail.transaction.occurred_at)} />
          <Fact label="Account reference" value={caseDetail.transaction.account_reference} />
          <Fact label="Merchant reference" value={caseDetail.transaction.merchant_reference ?? "Not supplied"} />
          <Fact label="Channel" value={humanize(caseDetail.transaction.channel ?? "Not supplied")} />
          <Fact label="Priority" value={humanize(caseDetail.priority)} />
        </section>

        <div className="dossier-grid">
          <div className="dossier-evidence">
            <section className="evidence-section">
              <div className="dossier-section-heading">
                <div>
                  <p className="eyebrow">Deterministic evidence</p>
                  <h3>Triggered review rules</h3>
                </div>
                <span>{caseDetail.triggered_rule_count} of 6</span>
              </div>
              <ol className="rule-ledger">
                {caseDetail.evidence.triggered_rules.map((rule, index) => (
                  <li key={String(rule.rule_id ?? index)}>
                    <span className="rule-index">{String(index + 1).padStart(2, "0")}</span>
                    <div>
                      <h4>{String(rule.title ?? rule.rule_id ?? "Triggered rule")}</h4>
                      <p>{evidenceSummary(rule.evidence)}</p>
                    </div>
                    <strong>+{String(rule.contribution_points ?? 0)}</strong>
                  </li>
                ))}
              </ol>
            </section>

            <HybridRiskEvidence
              assessments={caseDetail.hybrid_assessments}
              predictions={shadowPredictions}
              role={user.role}
              ruleScore={caseDetail.risk_score}
              transactionId={caseDetail.transaction.id}
            />

            <GroundedCaseBrief
              caseBriefs={caseDetail.case_briefs}
              caseId={caseDetail.id}
              hybridAssessments={caseDetail.hybrid_assessments}
              role={user.role}
            />

            {caseDetail.outcome ? <OutcomeRecord caseDetail={caseDetail} /> : null}

            <section className="evidence-section" id="audit-ledger">
              <div className="dossier-section-heading">
                <div>
                  <p className="eyebrow">Append-only record</p>
                  <h3>Decision ledger</h3>
                </div>
                <span>{caseDetail.events.length} {caseDetail.events.length === 1 ? "event" : "events"}</span>
              </div>
              <ol className="event-ledger">
                {caseDetail.events.map((event) => (
                  <li key={event.event_checksum}>
                    <span className="event-sequence">{String(event.sequence_number).padStart(2, "0")}</span>
                    <div>
                      <h4>{eventLabel(event)}</h4>
                      <p>{eventDescription(event)}</p>
                      <small>{event.actor_username} · {formatTimestamp(event.created_at)}</small>
                    </div>
                    <code>{event.event_checksum.slice(0, 10)}</code>
                  </li>
                ))}
              </ol>
            </section>

            <section className="lineage-strip">
              <p><span>Feature set</span><code>{caseDetail.evidence.feature_set_version}</code></p>
              <p><span>Ruleset</span><code>{caseDetail.evidence.ruleset_version}</code></p>
              <p><span>Opening checksum</span><code>{caseDetail.opening_checksum}</code></p>
            </section>
          </div>

          <aside className="dossier-actions" aria-label="Case actions">
            <CaseActions
              caseId={caseDetail.id}
              outcome={caseDetail.outcome}
              role={user.role}
              status={caseDetail.status}
            />
          </aside>
        </div>
      </article>
    </WorkspaceShell>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function OutcomeRecord({ caseDetail }: { caseDetail: CaseDetail }) {
  const outcome = caseDetail.outcome;
  if (!outcome) return null;
  return (
    <section className="outcome-record">
      <p className="eyebrow">Human determination</p>
      <div className="outcome-title">
        <h3>{humanize(outcome.classification)}</h3>
        <span className={outcome.training_eligible ? "label-approved" : "label-pending"}>
          {outcome.training_eligible ? "ML label approved" : "Not training eligible"}
        </span>
      </div>
      <blockquote>{outcome.rationale}</blockquote>
      <p>Determined by {outcome.determined_by} · {formatTimestamp(outcome.created_at)}</p>
      {outcome.review ? (
        <p className="outcome-review">
          Independent review: <strong>{humanize(outcome.review.status)}</strong> by {outcome.review.reviewed_by}
        </p>
      ) : null}
    </section>
  );
}

function eventLabel(event: CaseEvent) {
  const labels: Record<CaseEvent["event_type"], string> = {
    opened: "Case opened",
    review_started: "Evidence review started",
    note_added: "Analyst note added",
    classified: "Final classification recorded",
    outcome_reviewed: "Outcome label reviewed",
    brief_generated: "Grounded case brief generated",
  };
  return labels[event.event_type];
}

function eventDescription(event: CaseEvent) {
  const payload = event.payload;
  if (event.event_type === "note_added") return String(payload.note ?? "Analyst observation recorded.");
  if (event.event_type === "review_started") return String(payload.reason ?? "Review started.");
  if (event.event_type === "classified") return `${humanize(String(payload.classification ?? ""))}: ${String(payload.rationale ?? "")}`;
  if (event.event_type === "outcome_reviewed") return `${humanize(String(payload.status ?? ""))}: ${String(payload.reason ?? "")}`;
  if (event.event_type === "brief_generated") {
    return `${humanize(String(payload.generation_mode ?? ""))} · ${String(payload.provider_name ?? "versioned explanation")}`;
  }
  return String(payload.opening_reason ?? "Risk evidence met the review threshold.");
}

function evidenceSummary(evidence: unknown) {
  if (!evidence || typeof evidence !== "object") return "Versioned evidence recorded.";
  return Object.entries(evidence as Record<string, unknown>)
    .slice(0, 3)
    .map(([key, value]) => `${humanize(key)}: ${String(value)}`)
    .join(" · ");
}

function humanize(value: string) {
  const text = value.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function formatAmount(amount: string, currency: string) {
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(Number(amount));
  } catch {
    return `${currency} ${amount}`;
  }
}

function formatTimestamp(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

function statusLabel(status: CaseDetail["status"]) {
  return status === "in_review" ? "In review" : humanize(status);
}
