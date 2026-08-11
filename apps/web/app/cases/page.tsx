import type { CaseSummary } from "@fip/contracts";
import Link from "next/link";
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth/server";
import { getCases } from "@/lib/cases/server";

import { WorkspaceShell } from "../components/workspace-shell";

export default async function CaseDossiersPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");

  const cases = await getCases();
  const activeCases = cases.filter((item) => item.status !== "classified");

  return (
    <WorkspaceShell
      activeNavigation="case_dossiers"
      eyebrow="Investigation archive"
      reviewCount={activeCases.length}
      title="Case dossiers"
      user={user}
    >
      <section className="dossier-archive">
        <header>
          <div>
            <p className="eyebrow">Traceable case records</p>
            <h2>Every investigation, retained.</h2>
          </div>
          <dl>
            <div>
              <dt>Open</dt>
              <dd>{activeCases.length}</dd>
            </div>
            <div>
              <dt>Classified</dt>
              <dd>{cases.length - activeCases.length}</dd>
            </div>
          </dl>
        </header>
        {cases.length ? (
          <ol>
            {cases.map((item, index) => (
              <DossierArchiveRow caseRecord={item} index={index + 1} key={item.id} />
            ))}
          </ol>
        ) : (
          <div className="dossier-archive-empty">
            No case dossier has been opened. Medium and high deterministic assessments will be
            retained here when they enter human review.
          </div>
        )}
      </section>
    </WorkspaceShell>
  );
}

function DossierArchiveRow({
  caseRecord,
  index,
}: {
  caseRecord: CaseSummary;
  index: number;
}) {
  return (
    <li>
      <Link href={`/cases/${caseRecord.id}`}>
        <span className="dossier-archive-index">{String(index).padStart(3, "0")}</span>
        <span className="dossier-archive-reference">
          <strong>{caseRecord.display_id}</strong>
          <small>{formatDate(caseRecord.created_at)}</small>
        </span>
        <span className="dossier-archive-transaction">
          <strong>{caseRecord.transaction.external_transaction_id}</strong>
          <small>{formatAmount(caseRecord.transaction.amount, caseRecord.transaction.currency)}</small>
        </span>
        <span className={`dossier-archive-risk risk-${caseRecord.risk_level}`}>
          <strong>{caseRecord.risk_score}</strong>
          <small>{caseRecord.risk_level} risk</small>
        </span>
        <span className={`case-status status-${caseRecord.status}`}>
          {statusLabel(caseRecord.status)}
        </span>
        <span className={caseRecord.integrity_verified ? "archive-verified" : "archive-damaged"}>
          {caseRecord.integrity_verified ? "Verified" : "Integrity failed"}
        </span>
        <span aria-hidden="true" className="case-row-arrow">↗</span>
      </Link>
    </li>
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
