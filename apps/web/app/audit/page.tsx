import type {
  AuditCategory,
  AuditIntegrityFilter,
  AuditLedger,
  AuditLedgerEntry,
} from "@fip/contracts";
import Link from "next/link";
import { redirect } from "next/navigation";

import { getAuditLedger } from "@/lib/audit/server";
import { getCurrentUser } from "@/lib/auth/server";
import { getCases } from "@/lib/cases/server";

import { WorkspaceShell } from "../components/workspace-shell";

const categories: AuditCategory[] = [
  "case",
  "model",
  "scoring",
  "explanation",
  "hybrid",
  "dataset",
  "training",
  "benchmark",
  "evaluation",
];

type SearchParameters = {
  category?: string | string[];
  integrity?: string | string[];
  q?: string | string[];
  page?: string | string[];
};

export default async function AuditLedgerPage({
  searchParams,
}: {
  searchParams: Promise<SearchParameters>;
}) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");

  const parameters = await searchParams;
  const filters = parseFilters(parameters);
  const [ledger, cases] = await Promise.all([getAuditLedger(filters), getCases()]);
  const activeCases = cases.filter((item) => item.status !== "classified");

  return (
    <WorkspaceShell
      activeNavigation="audit_ledger"
      eyebrow="Integrity archive"
      reviewCount={activeCases.length}
      title="Audit ledger"
      user={user}
    >
      {ledger ? (
        <AuditWorkspace ledger={ledger} />
      ) : (
        <section className="audit-unavailable">
          <p className="eyebrow">Ledger unavailable</p>
          <h2>The audit projection could not be reached.</h2>
          <p>No evidence record was created, changed or deleted.</p>
        </section>
      )}
    </WorkspaceShell>
  );
}

function AuditWorkspace({ ledger }: { ledger: AuditLedger }) {
  return (
    <div className="audit-workspace">
      <section className="audit-intro">
        <div>
          <p className="eyebrow">Reverified at read time</p>
          <h2>Every material record leaves a trace.</h2>
          <p>
            One read-only view across human decisions, deterministic scoring, governed model
            evidence and evaluation artifacts. Source records remain in their owning modules.
          </p>
        </div>
        <div className={ledger.summary.failed_records ? "audit-seal failed" : "audit-seal"}>
          <span>Ledger finding</span>
          <strong>{ledger.summary.failed_records}</strong>
          <small>{ledger.summary.failed_records === 1 ? "integrity failure" : "integrity failures"}</small>
        </div>
      </section>

      <section aria-label="Audit ledger summary" className="audit-summary">
        <AuditMetric label="Material records" value={ledger.summary.total_records} />
        <AuditMetric label="Verified" value={ledger.summary.verified_records} />
        <AuditMetric label="Hash-chain events" value={ledger.summary.chained_records} />
        <AuditMetric label="Record families" value={Object.keys(ledger.summary.category_counts).length} />
      </section>

      <AuditFilters ledger={ledger} />

      <section className="audit-register">
        <header>
          <div>
            <p className="eyebrow">Material event register</p>
            <h3>{ledger.total.toLocaleString("en-US")} matching records</h3>
          </div>
          <span>
            Page {ledger.page_count ? ledger.page : 0} of {ledger.page_count}
          </span>
        </header>
        {ledger.entries.length ? (
          <ol>
            {ledger.entries.map((entry, index) => (
              <AuditRecord
                entry={entry}
                index={(ledger.page - 1) * ledger.page_size + index + 1}
                key={entry.id}
              />
            ))}
          </ol>
        ) : (
          <div className="audit-empty">
            No material record matches these filters. Clearing the filters does not change source
            evidence.
          </div>
        )}
      </section>

      <AuditPagination ledger={ledger} />

      <footer className="audit-footnote">
        <span>{ledger.schema_version}</span>
        <span>Read only</span>
        <span>No operational state changed</span>
      </footer>
    </div>
  );
}

function AuditMetric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value.toLocaleString("en-US")}</strong>
    </div>
  );
}

function AuditFilters({ ledger }: { ledger: AuditLedger }) {
  return (
    <form action="/audit" className="audit-filters" method="get">
      <label>
        <span>Search trace</span>
        <input
          defaultValue={ledger.query ?? ""}
          maxLength={120}
          name="q"
          placeholder="Reference, actor or checksum"
          type="search"
        />
      </label>
      <label>
        <span>Record family</span>
        <select defaultValue={ledger.category ?? ""} name="category">
          <option value="">All families</option>
          {categories.map((category) => (
            <option key={category} value={category}>
              {categoryLabel(category)}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Integrity</span>
        <select defaultValue={ledger.integrity} name="integrity">
          <option value="all">All findings</option>
          <option value="verified">Verified only</option>
          <option value="failed">Failures only</option>
        </select>
      </label>
      <button type="submit">Apply filters</button>
      {ledger.category || ledger.integrity !== "all" || ledger.query ? (
        <Link href="/audit">Clear</Link>
      ) : null}
    </form>
  );
}

function AuditRecord({ entry, index }: { entry: AuditLedgerEntry; index: number }) {
  return (
    <li className={entry.integrity_verified ? "audit-record" : "audit-record failed"}>
      <span className="audit-record-index">{String(index).padStart(3, "0")}</span>
      <span className={`audit-category audit-category-${entry.category}`}>
        {categoryLabel(entry.category)}
      </span>
      <div className="audit-record-copy">
        <div>
          <strong>{entry.action}</strong>
          <Link href={entry.href}>{entry.subject_label} ↗</Link>
        </div>
        <p>{entry.detail}</p>
        <small>
          {entry.actor_username} · {formatDateTime(entry.occurred_at)}
          {entry.sequence_number ? ` · chain ${String(entry.sequence_number).padStart(2, "0")}` : ""}
        </small>
      </div>
      <div className="audit-record-proof">
        <code title={entry.checksum}>{shortChecksum(entry.checksum)}</code>
        <span className={entry.integrity_verified ? "audit-verified" : "audit-failed"}>
          {entry.integrity_verified ? "Verified" : "Integrity failed"}
        </span>
      </div>
    </li>
  );
}

function AuditPagination({ ledger }: { ledger: AuditLedger }) {
  if (ledger.page_count <= 1) return null;
  return (
    <nav aria-label="Audit ledger pagination" className="audit-pagination">
      {ledger.page > 1 ? (
        <Link href={ledgerHref(ledger, ledger.page - 1)}>← Newer records</Link>
      ) : (
        <span />
      )}
      <span>
        {ledger.page} / {ledger.page_count}
      </span>
      {ledger.page < ledger.page_count ? (
        <Link href={ledgerHref(ledger, ledger.page + 1)}>Older records →</Link>
      ) : (
        <span />
      )}
    </nav>
  );
}

function parseFilters(parameters: SearchParameters) {
  const categoryValue = first(parameters.category);
  const integrityValue = first(parameters.integrity);
  const query = first(parameters.q)?.trim().slice(0, 120);
  const pageValue = Number.parseInt(first(parameters.page) ?? "1", 10);
  return {
    category: categories.includes(categoryValue as AuditCategory)
      ? (categoryValue as AuditCategory)
      : undefined,
    integrity: isIntegrityFilter(integrityValue) ? integrityValue : "all",
    query: query || undefined,
    page: Number.isFinite(pageValue) && pageValue > 0 ? pageValue : 1,
    pageSize: 25,
  };
}

function first(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function isIntegrityFilter(value: string | undefined): value is AuditIntegrityFilter {
  return value === "all" || value === "verified" || value === "failed";
}

function ledgerHref(ledger: AuditLedger, page: number) {
  const parameters = new URLSearchParams();
  if (ledger.category) parameters.set("category", ledger.category);
  if (ledger.integrity !== "all") parameters.set("integrity", ledger.integrity);
  if (ledger.query) parameters.set("q", ledger.query);
  if (page > 1) parameters.set("page", String(page));
  const suffix = parameters.toString();
  return suffix ? `/audit?${suffix}` : "/audit";
}

function categoryLabel(category: AuditCategory) {
  return category === "hybrid"
    ? "Hybrid AI"
    : category.charAt(0).toUpperCase() + category.slice(1);
}

function shortChecksum(value: string) {
  return `${value.slice(0, 8)}…${value.slice(-6)}`;
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
    timeZoneName: "short",
    year: "numeric",
  }).format(new Date(value));
}
