"use client";

import type { ApiErrorResponse, DatasetSnapshotCreateResponse } from "@fip/contracts";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

export function DatasetSnapshotAction({
  canCreate,
  eligibleLabelCount,
}: {
  canCreate: boolean;
  eligibleLabelCount: number;
}) {
  const router = useRouter();
  const [reason, setReason] = useState(
    "Freeze the current independently approved label evidence for operational ML review.",
  );
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<{ error: boolean; text: string } | null>(null);

  if (!canCreate) {
    return (
      <p className="dataset-curation-note">
        Dataset snapshots are created by administrators. All authenticated roles can inspect the
        readiness evidence and immutable manifests.
      </p>
    );
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setMessage(null);
    try {
      const response = await fetch("/api/ml-datasets/snapshots", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      });
      const payload = (await response.json()) as DatasetSnapshotCreateResponse | ApiErrorResponse;
      if (!response.ok) {
        setMessage({ error: true, text: "detail" in payload ? payload.detail : "Snapshot failed." });
        return;
      }
      const result = payload as DatasetSnapshotCreateResponse;
      setMessage({
        error: false,
        text: result.created
          ? `${result.dataset.display_id} was sealed with ${result.dataset.row_count} reviewed labels.`
          : `${result.dataset.display_id} already represents this exact approved source manifest.`,
      });
      router.refresh();
    } catch {
      setMessage({ error: true, text: "The dataset service is temporarily unavailable." });
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="dataset-snapshot-form" onSubmit={submit}>
      <label htmlFor="dataset-reason">Curation record</label>
      <textarea
        id="dataset-reason"
        maxLength={500}
        minLength={12}
        onChange={(event) => setReason(event.target.value)}
        rows={4}
        value={reason}
      />
      <button
        className="dossier-button dossier-button-primary"
        disabled={pending || eligibleLabelCount === 0}
        type="submit"
      >
        {pending ? "Sealing snapshot…" : "Seal dataset snapshot"}
      </button>
      {eligibleLabelCount === 0 ? (
        <p className="dataset-form-hint">At least one approved, verified binary label is required.</p>
      ) : null}
      {message ? (
        <p className={`case-action-message ${message.error ? "is-error" : "is-success"}`}>
          {message.text}
        </p>
      ) : null}
    </form>
  );
}
