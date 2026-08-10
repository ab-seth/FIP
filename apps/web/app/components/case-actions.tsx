"use client";

import type {
  ApiErrorResponse,
  CaseClassification,
  CaseOutcome,
  CaseStatus,
  UserRole,
} from "@fip/contracts";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

export function CaseActions({
  caseId,
  outcome,
  role,
  status,
}: {
  caseId: string;
  outcome: CaseOutcome | null;
  role: UserRole;
  status: CaseStatus;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const canInvestigate = role === "administrator" || role === "analyst";
  const canReviewLabel =
    role === "evaluator" &&
    outcome !== null &&
    outcome.classification !== "inconclusive" &&
    outcome.review === null;

  async function mutate(action: string, body: Record<string, string>, success: string) {
    setBusy(action);
    setMessage(null);
    try {
      const response = await fetch(`/api/cases/${caseId}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        const error = (await response.json()) as ApiErrorResponse;
        setMessage({ kind: "error", text: error.detail ?? "The case could not be updated." });
        return false;
      }
      setMessage({ kind: "success", text: success });
      router.refresh();
      return true;
    } catch {
      setMessage({ kind: "error", text: "The case service could not be reached." });
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function submitNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    if (await mutate("notes", { note: String(data.get("note") ?? "") }, "Note added to the ledger.")) {
      form.reset();
    }
  }

  async function submitOutcome(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const classification = String(data.get("classification") ?? "") as CaseClassification;
    await mutate(
      "outcomes",
      { classification, rationale: String(data.get("rationale") ?? "") },
      "Final classification recorded.",
    );
  }

  async function submitLabelReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!outcome) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    await mutate(
      `outcomes/${outcome.id}/review`,
      { status: String(data.get("review_status") ?? ""), reason: String(data.get("reason") ?? "") },
      "Independent label review recorded.",
    );
  }

  if (status === "classified" && canInvestigate) {
    return (
      <div className="case-readonly-note case-sealed-note">
        <p className="eyebrow">Decision sealed</p>
        <h3>{outcome ? humanize(outcome.classification) : "Classification recorded"}</h3>
        <p>
          The analyst record is closed and cannot be replaced through the application.
          {outcome?.classification === "inconclusive"
            ? " Inconclusive outcomes remain outside supervised training data."
            : outcome?.training_eligible
              ? " An independent evaluator approved this outcome for future dataset curation."
              : " A separate evaluator must review it before future dataset curation."}
        </p>
        {message ? (
          <p className={`case-action-message is-${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>
            {message.text}
          </p>
        ) : null}
      </div>
    );
  }

  if (!canInvestigate && !canReviewLabel) {
    return (
      <div className="case-readonly-note">
        <p className="eyebrow">Read-only access</p>
        <p>This role may inspect the complete dossier but cannot change its human decision record.</p>
      </div>
    );
  }

  return (
    <div className="case-action-stack">
      {status === "open" && canInvestigate ? (
        <section className="case-action-card">
          <p className="eyebrow">01 · Custody</p>
          <h3>Begin evidence review</h3>
          <p>Mark the dossier in review before recording investigative judgment.</p>
          <button
            className="dossier-button dossier-button-primary"
            disabled={busy !== null}
            onClick={() =>
              mutate(
                "review",
                { reason: "Analyst began review of the deterministic evidence package." },
                "Review started.",
              )
            }
            type="button"
          >
            {busy === "review" ? "Starting…" : "Begin review"}
          </button>
        </section>
      ) : null}

      {status === "in_review" && canInvestigate ? (
        <section className="case-action-card">
          <p className="eyebrow">02 · Observation</p>
          <h3>Add analyst note</h3>
          <form onSubmit={submitNote}>
            <label htmlFor="case-note">Evidence-based observation</label>
            <textarea id="case-note" minLength={3} name="note" required rows={4} />
            <button className="dossier-button" disabled={busy !== null} type="submit">
              {busy === "notes" ? "Recording…" : "Add to ledger"}
            </button>
          </form>
        </section>
      ) : null}

      {status === "in_review" && canInvestigate ? (
        <section className="case-action-card case-action-decision">
          <p className="eyebrow">03 · Determination</p>
          <h3>Record final classification</h3>
          <p>This closes the investigation. The outcome cannot be replaced through the application.</p>
          <form onSubmit={submitOutcome}>
            <label htmlFor="case-classification">Classification</label>
            <select defaultValue="inconclusive" id="case-classification" name="classification">
              <option value="confirmed_fraud">Confirmed fraud</option>
              <option value="legitimate">Legitimate</option>
              <option value="inconclusive">Inconclusive</option>
            </select>
            <label htmlFor="case-rationale">Decision rationale</label>
            <textarea id="case-rationale" minLength={12} name="rationale" required rows={5} />
            <button className="dossier-button dossier-button-primary" disabled={busy !== null} type="submit">
              {busy === "outcomes" ? "Recording…" : "Record final decision"}
            </button>
          </form>
        </section>
      ) : null}

      {canReviewLabel && outcome ? (
        <section className="case-action-card case-action-label">
          <p className="eyebrow">Independent control</p>
          <h3>Review future-ML label</h3>
          <p>
            This does not alter the analyst decision. Approval only marks the outcome eligible for a
            separately versioned training dataset.
          </p>
          <form onSubmit={submitLabelReview}>
            <label htmlFor="label-review-status">Label review</label>
            <select defaultValue="approved" id="label-review-status" name="review_status">
              <option value="approved">Approve label</option>
              <option value="rejected">Reject label</option>
            </select>
            <label htmlFor="label-review-reason">Independent review rationale</label>
            <textarea id="label-review-reason" minLength={12} name="reason" required rows={5} />
            <button className="dossier-button dossier-button-primary" disabled={busy !== null} type="submit">
              {busy?.includes("/review") ? "Recording…" : "Record label review"}
            </button>
          </form>
        </section>
      ) : null}

      {message ? (
        <p className={`case-action-message is-${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>
          {message.text}
        </p>
      ) : null}
    </div>
  );
}

function humanize(value: string) {
  const text = value.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
