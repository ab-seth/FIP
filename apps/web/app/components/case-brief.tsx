"use client";

import type {
  ApiErrorResponse,
  CaseBrief,
  CaseBriefClaim,
  CaseBriefCreationResponse,
  HybridRiskAssessment,
  UserRole,
} from "@fip/contracts";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function GroundedCaseBrief({
  caseBriefs,
  caseId,
  hybridAssessments,
  role,
}: {
  caseBriefs: CaseBrief[];
  caseId: string;
  hybridAssessments: HybridRiskAssessment[];
  role: UserRole;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const brief = caseBriefs[caseBriefs.length - 1] ?? null;
  const hybrid = hybridAssessments[hybridAssessments.length - 1] ?? null;
  const canGenerate = role === "administrator" || role === "analyst";

  async function generateBrief() {
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(`/api/cases/${caseId}/briefs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hybrid_assessment_id: hybrid?.id ?? null }),
      });
      if (!response.ok) {
        const error = (await response.json()) as ApiErrorResponse;
        setMessage({ kind: "error", text: error.detail ?? "The case brief could not be generated." });
        return;
      }
      const result = (await response.json()) as CaseBriefCreationResponse;
      setMessage({
        kind: "success",
        text: result.created ? "A cited case brief was added to the ledger." : "The verified brief is already current.",
      });
      router.refresh();
    } catch {
      setMessage({ kind: "error", text: "The case brief service could not be reached." });
    } finally {
      setBusy(false);
    }
  }

  if (!brief) {
    return (
      <section className="evidence-section case-brief-empty" id="case-brief">
        <div className="dossier-section-heading">
          <div>
            <p className="eyebrow">Grounded explanation</p>
            <h3>Case brief</h3>
          </div>
          <span>{hybrid ? "Hybrid evidence ready" : "Rules evidence ready"}</span>
        </div>
        <p>
          Generate a structured review brief from the verified evidence already in this dossier.
          It may explain and suggest review steps; it cannot change the score, classify the case,
          or take financial action.
        </p>
        {canGenerate ? (
          <button className="dossier-button case-brief-generate" disabled={busy} onClick={generateBrief} type="button">
            {busy ? "Validating brief…" : hybrid ? "Generate cited AI brief" : "Generate rules-grounded brief"}
          </button>
        ) : (
          <p className="case-brief-readonly">An administrator or analyst may generate this record.</p>
        )}
        {message ? <BriefMessage message={message} /> : null}
      </section>
    );
  }

  if (!brief.output || !brief.validation) {
    return (
      <section className="evidence-section case-brief" id="case-brief">
        <div className="dossier-section-heading case-brief-heading">
          <div>
            <p className="eyebrow">Grounded explanation</p>
            <h3>Case brief</h3>
          </div>
          <span className="brief-mode-fallback">Integrity failed</span>
        </div>
        <div className="case-brief-warning" role="alert">
          This explanation record is malformed or no longer passes integrity verification. Its
          narrative has been withheld.
        </div>
        <p className="case-brief-damaged-reference">
          Explanation checksum <code>{brief.explanation_checksum}</code>
        </p>
        <p className="case-brief-readonly">
          Generation for this evidence version is blocked until the damaged record is investigated.
        </p>
      </section>
    );
  }

  const output = brief.output;
  return (
    <section className="evidence-section case-brief" id="case-brief">
      <div className="dossier-section-heading case-brief-heading">
        <div>
          <p className="eyebrow">Grounded explanation</p>
          <h3>Case brief</h3>
        </div>
        <span className={brief.generation_mode === "llm" ? "brief-mode-ai" : "brief-mode-fallback"}>
          {brief.generation_mode === "llm" ? "Validated AI" : "Deterministic fallback"}
        </span>
      </div>

      {!brief.integrity_verified || !brief.validation.display_output.grounding_passed ? (
        <div className="case-brief-warning" role="alert">
          This explanation no longer passes integrity and grounding verification. Do not rely on it.
        </div>
      ) : null}

      <blockquote className="case-brief-summary">
        {output.summary}
        <Citations references={output.summary_evidence_refs} />
      </blockquote>

      <div className="case-brief-columns">
        <BriefClaimList label="Primary risk factors" claims={output.primary_risk_factors} />
        <BriefClaimList label="Supporting evidence" claims={output.supporting_evidence} />
        <BriefClaimList label="Uncertainties" claims={output.uncertainties} />
        <BriefClaimList label="Recommended review" claims={output.recommended_review_steps} ordered />
      </div>

      <footer className="case-brief-footer">
        <div>
          <span>Evidence contract</span>
          <code>{brief.prompt_version}</code>
        </div>
        <div>
          <span>Evidence checksum</span>
          <code>{brief.evidence_checksum.slice(0, 12)}</code>
        </div>
        <div>
          <span>Generated</span>
          <strong>{brief.requested_by} · {formatTimestamp(brief.created_at)}</strong>
        </div>
      </footer>

      <div className="case-brief-controls">
        <p>
          {caseBriefs.length} immutable {caseBriefs.length === 1 ? "version" : "versions"} ·
          {brief.hybrid_assessment_id ? " cited hybrid + rules evidence" : " cited rules evidence"}
        </p>
        {canGenerate ? (
          <button className="dossier-button" disabled={busy} onClick={generateBrief} type="button">
            {busy ? "Checking evidence…" : "Refresh from current evidence"}
          </button>
        ) : null}
      </div>
      {message ? <BriefMessage message={message} /> : null}
    </section>
  );
}

function BriefClaimList({
  claims,
  label,
  ordered = false,
}: {
  claims: CaseBriefClaim[];
  label: string;
  ordered?: boolean;
}) {
  const List = ordered ? "ol" : "ul";
  return (
    <div className="case-brief-group">
      <h4>{label}</h4>
      <List>
        {claims.map((claim, index) => (
          <li key={`${label}-${index}-${claim.text}`}>
            <p>{claim.text}</p>
            <Citations references={claim.evidence_refs} />
          </li>
        ))}
      </List>
    </div>
  );
}

function Citations({ references }: { references: string[] }) {
  return (
    <span className="case-brief-citations" aria-label="Evidence citations">
      {references.map((reference) => (
        <code key={reference}>{reference}</code>
      ))}
    </span>
  );
}

function BriefMessage({
  message,
}: {
  message: { kind: "error" | "success"; text: string };
}) {
  return (
    <p className={`case-action-message is-${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>
      {message.text}
    </p>
  );
}

function formatTimestamp(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}
