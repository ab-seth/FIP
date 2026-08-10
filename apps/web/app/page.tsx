import type { CaseSummary } from "@fip/contracts";
import Link from "next/link";
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth/server";
import { getCases } from "@/lib/cases/server";

import { TransactionIntake } from "./components/transaction-intake";
import { WorkspaceShell } from "./components/workspace-shell";

function RegisterMark() {
  return (
    <svg aria-hidden="true" className="register-mark" viewBox="0 0 40 40">
      <path d="M8 7.5h24v25H8z" />
      <path d="M13 14h14M13 20h9M13 26h14" />
    </svg>
  );
}

export default async function Home() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");

  const cases = await getCases();
  const activeCases = cases.filter((item) => item.status !== "classified");
  const canImport = user.role === "administrator" || user.role === "analyst";

  return (
    <WorkspaceShell
      activeNavigation="case_register"
      eyebrow="Investigation workspace"
      reviewCount={activeCases.length}
      title="Case register"
      user={user}
    >
      <section aria-labelledby="register-title" className="register-panel" id="register">
        <div className="register-caption">
          <div>
            <p className="eyebrow">Active register</p>
            <h2 id="register-title">Investigations requiring judgment</h2>
          </div>
          <div className="register-tools">
            <span className="record-count">
              {activeCases.length} {activeCases.length === 1 ? "record" : "records"}
            </span>
            {activeCases.length > 0 && canImport ? <TransactionIntake /> : null}
          </div>
        </div>

        {activeCases.length > 0 ? (
          <CaseRegister cases={activeCases} />
        ) : (
          <div className="empty-register">
            <div className="empty-illustration">
              <RegisterMark />
              <span className="illustration-index">001</span>
            </div>
            <p className="empty-kicker">The register is clear</p>
            <h3>Nothing needs your judgment yet.</h3>
            <p className="empty-copy">
              Import a transaction file to begin a traceable review. Medium and high rules-only
              assessments enter this register; every human action remains part of the evidence record.
            </p>
            <div className="empty-actions">
              {canImport ? <TransactionIntake /> : null}
              <a className="text-action" href="#preparation-note">
                Read the preparation guide <span aria-hidden="true">→</span>
              </a>
            </div>
          </div>
        )}

        <footer className="register-footer" id="preparation-note">
          <span>Medium and high risk enter review</span>
          <span>Rules-only score remains unchanged</span>
          <span>Analyst classification is human-owned</span>
        </footer>
      </section>
    </WorkspaceShell>
  );
}

function CaseRegister({ cases }: { cases: CaseSummary[] }) {
  return (
    <div className="case-register-list">
      <div aria-hidden="true" className="case-register-columns">
        <span>Reference</span>
        <span>Transaction</span>
        <span>Risk evidence</span>
        <span>Status</span>
        <span />
      </div>
      <ol>
        {cases.map((item) => (
          <li key={item.id}>
            <Link className="case-register-row" href={`/cases/${item.id}`}>
              <span className="case-reference">
                <strong>{item.display_id}</strong>
                <small>{formatDate(item.created_at)}</small>
              </span>
              <span className="case-transaction">
                <strong>{item.transaction.external_transaction_id}</strong>
                <small>
                  {formatAmount(item.transaction.amount, item.transaction.currency)} · {item.transaction.account_reference}
                </small>
              </span>
              <span className="case-risk">
                <span className={`risk-score risk-${item.risk_level}`}>{item.risk_score}</span>
                <span>
                  <strong>{item.risk_level} risk</strong>
                  <small>{item.triggered_rule_count} contributing rules</small>
                </span>
              </span>
              <span className={`case-status status-${item.status}`}>{statusLabel(item.status)}</span>
              <span aria-hidden="true" className="case-row-arrow">↗</span>
            </Link>
          </li>
        ))}
      </ol>
    </div>
  );
}

function formatAmount(amount: string, currency: string) {
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(Number(amount));
  } catch {
    return `${currency} ${amount}`;
  }
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}

function statusLabel(status: CaseSummary["status"]) {
  return status === "in_review" ? "In review" : status.charAt(0).toUpperCase() + status.slice(1);
}
