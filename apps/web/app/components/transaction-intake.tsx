"use client";

import type {
  ApiErrorResponse,
  CsvValidationError,
  UploadImportResponse,
  UploadValidationResponse,
} from "@fip/contracts";
import { useEffect, useRef, useState } from "react";

type IntakeState = "closed" | "select" | "validating" | "ready" | "error" | "importing" | "success";

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

function ImportMark() {
  return (
    <svg aria-hidden="true" className="import-mark" viewBox="0 0 48 48">
      <path d="M24 8v22M16.5 22.5 24 30l7.5-7.5M10 35v5h28v-5" />
    </svg>
  );
}

function CloseMark() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  );
}

function ArrowMark() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M5 12h14M14 7l5 5-5 5" />
    </svg>
  );
}

export function TransactionIntake() {
  const [state, setState] = useState<IntakeState>("closed");
  const [file, setFile] = useState<File | null>(null);
  const [validation, setValidation] = useState<UploadValidationResponse | null>(null);
  const [result, setResult] = useState<UploadImportResponse | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLElement>(null);
  const triggerButton = useRef<HTMLButtonElement>(null);

  const busy = state === "validating" || state === "importing";
  const isOpen = state !== "closed";

  useEffect(() => {
    if (!isOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) {
        setFile(null);
        setValidation(null);
        setResult(null);
        setRequestError(null);
        setState("closed");
        requestAnimationFrame(() => triggerButton.current?.focus());
        return;
      }
      if (event.key === "Tab") {
        const focusable = dialog.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
        );
        const first = focusable?.[0];
        const last = focusable?.[focusable.length - 1];
        if (!first || !last) return;
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, isOpen]);

  function reset(nextState: IntakeState = "select") {
    setFile(null);
    setValidation(null);
    setResult(null);
    setRequestError(null);
    setState(nextState);
  }

  function close() {
    if (!busy) {
      reset("closed");
      requestAnimationFrame(() => triggerButton.current?.focus());
    }
  }

  async function validateFile() {
    if (!file) return;
    if (file.size > MAX_UPLOAD_BYTES) {
      setRequestError("The CSV file cannot exceed 10 MB.");
      return;
    }

    setRequestError(null);
    setState("validating");
    try {
      const response = await sendFile("/api/transactions/upload/validate", file);
      if (!response.ok) {
        setRequestError(await readApiError(response));
        setState("select");
        return;
      }
      const responseBody = (await response.json()) as UploadValidationResponse;
      setValidation(responseBody);
      setState(responseBody.valid ? "ready" : "error");
    } catch {
      setRequestError("The file could not be validated. Try again.");
      setState("select");
    }
  }

  async function importFile() {
    if (!file || !validation) return;
    setRequestError(null);
    setState("importing");
    try {
      const response = await sendFile("/api/transactions/upload", file);
      if (response.status === 422) {
        const responseBody = (await response.json()) as UploadValidationResponse;
        setValidation(responseBody);
        setState("error");
        return;
      }
      if (!response.ok) {
        setRequestError(await readApiError(response));
        setState("ready");
        return;
      }
      setResult((await response.json()) as UploadImportResponse);
      setState("success");
    } catch {
      setRequestError("The import could not be completed. No new data was stored.");
      setState("ready");
    }
  }

  function downloadErrors() {
    if (!validation) return;
    const rows = [
      ["row_number", "field", "code", "message"],
      ...validation.errors.map((error) => [
        error.row_number?.toString() ?? "",
        error.field ?? "",
        error.code,
        error.message,
      ]),
    ];
    const csv = rows.map((row) => row.map(csvValue).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${withoutExtension(validation.filename)}-errors.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <>
      <button className="primary-action" onClick={() => reset()} ref={triggerButton} type="button">
        <ImportMark />
        Import transaction file
      </button>

      {isOpen ? (
        <div className="intake-overlay" onMouseDown={(event) => event.target === event.currentTarget && close()}>
          <section
            aria-describedby="intake-description"
            aria-labelledby="intake-title"
            aria-modal="true"
            className="intake-dialog"
            ref={dialog}
            role="dialog"
          >
            <div className="intake-index"><span>CSV</span><span>Transaction intake</span></div>
            <div className="intake-sheet">
              <header className="intake-heading">
                <div>
                  <p className="eyebrow">Source file</p>
                  <h2 id="intake-title">Import transaction file</h2>
                  <p id="intake-description">Validate the file before any transaction is stored.</p>
                </div>
                <button
                  aria-label="Close transaction import"
                  className="intake-icon-button"
                  disabled={busy}
                  onClick={close}
                  ref={closeButton}
                  type="button"
                >
                  <CloseMark />
                </button>
              </header>

              <ol aria-label="Import progress" className="intake-steps">
                <li className={state === "select" || state === "validating" ? "is-active" : ""}>
                  <span>01</span> Select
                </li>
                <li className={["ready", "error", "importing"].includes(state) ? "is-active" : ""}>
                  <span>02</span> Validate
                </li>
                <li className={state === "success" ? "is-active" : ""}>
                  <span>03</span> Import
                </li>
              </ol>

              {(state === "select" || state === "validating") && (
                <SelectState
                  busy={busy}
                  file={file}
                  onCancel={close}
                  onFile={(selected) => {
                    setFile(selected);
                    setRequestError(null);
                  }}
                  onValidate={validateFile}
                  requestError={requestError}
                />
              )}

              {(state === "ready" || state === "importing") && validation && (
                <ReadyState
                  busy={busy}
                  onImport={importFile}
                  onReplace={() => reset()}
                  requestError={requestError}
                  validation={validation}
                />
              )}

              {state === "error" && validation && (
                <ErrorState
                  errors={validation.errors}
                  onDownload={downloadErrors}
                  onReplace={() => reset()}
                  rejectedRows={validation.rejected_rows}
                />
              )}

              {state === "success" && result && (
                <SuccessState
                  onClose={close}
                  onReset={() => reset()}
                  result={result}
                />
              )}
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}

function SelectState({
  busy,
  file,
  onCancel,
  onFile,
  onValidate,
  requestError,
}: {
  busy: boolean;
  file: File | null;
  onCancel: () => void;
  onFile: (file: File | null) => void;
  onValidate: () => void;
  requestError: string | null;
}) {
  return (
    <div className="intake-state">
      <div className="intake-file-control">
        <label htmlFor="transaction-file">Transaction file</label>
        <input
          accept=".csv,text/csv"
          disabled={busy}
          id="transaction-file"
          onChange={(event) => onFile(event.target.files?.[0] ?? null)}
          type="file"
        />
        <p>CSV only · maximum 10,000 rows · 10 MB</p>
      </div>
      {file ? <p className="intake-selected-file">Selected · {file.name}</p> : null}
      <div className="intake-required">
        <p>Required fields</p>
        <p><code>external_transaction_id</code>, <code>occurred_at</code>, <code>amount</code>, <code>currency</code>, <code>account_reference</code></p>
      </div>
      {requestError ? <p className="intake-alert" role="alert">{requestError}</p> : null}
      <footer className="intake-actions">
        <button className="intake-button intake-button-quiet" disabled={busy} onClick={onCancel} type="button">Cancel</button>
        <button className="intake-button intake-button-primary" disabled={!file || busy} onClick={onValidate} type="button">
          {busy ? "Validating…" : "Validate file"} {!busy ? <ArrowMark /> : null}
        </button>
      </footer>
    </div>
  );
}

function ReadyState({
  busy,
  onImport,
  onReplace,
  requestError,
  validation,
}: {
  busy: boolean;
  onImport: () => void;
  onReplace: () => void;
  requestError: string | null;
  validation: UploadValidationResponse;
}) {
  const replay = validation.existing_batch !== null;
  return (
    <div className="intake-state">
      <div className="intake-file-line">
        <span aria-hidden="true" className="intake-file-mark">✓</span>
        <div><p>{validation.filename}</p><p>SHA-256 · {shortChecksum(validation.checksum)}</p></div>
        <span className="intake-badge">{replay ? "Recorded" : "Validated"}</span>
      </div>
      <dl className="intake-summary">
        <div><dt>Rows detected</dt><dd>{formatCount(validation.row_count)}</dd></div>
        <div><dt>Valid</dt><dd>{formatCount(validation.valid_rows)}</dd></div>
        <div><dt>Rejected</dt><dd>{formatCount(validation.rejected_rows)}</dd></div>
      </dl>
      <div className="intake-preview">
        <div className="intake-table-heading"><h3>Transaction preview</h3><span>First 3 rows</span></div>
        <div className="intake-table-scroll">
          <table>
            <thead><tr><th>Transaction ID</th><th>Occurred at</th><th>Amount</th><th>Currency</th></tr></thead>
            <tbody>{validation.preview.map((row) => (
              <tr key={row.external_transaction_id}>
                <td>{row.external_transaction_id}</td>
                <td>{formatDate(row.occurred_at)}</td>
                <td>{formatAmount(row.amount)}</td>
                <td>{row.currency}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </div>
      <p className="intake-note">
        {replay
          ? `This exact source is already recorded as ${validation.existing_batch?.display_id}.`
          : "No data has been stored. Import commits this validated batch atomically."}
      </p>
      {requestError ? <p className="intake-alert" role="alert">{requestError}</p> : null}
      <footer className="intake-actions">
        <button className="intake-button intake-button-quiet" disabled={busy} onClick={onReplace} type="button">Replace file</button>
        <button className="intake-button intake-button-primary" disabled={busy} onClick={onImport} type="button">
          {busy ? "Importing…" : replay ? "View import receipt" : `Import ${formatCount(validation.row_count)} transactions`}
          {!busy ? <ArrowMark /> : null}
        </button>
      </footer>
    </div>
  );
}

function ErrorState({
  errors,
  onDownload,
  onReplace,
  rejectedRows,
}: {
  errors: CsvValidationError[];
  onDownload: () => void;
  onReplace: () => void;
  rejectedRows: number;
}) {
  return (
    <div className="intake-state">
      <div className="intake-result-heading">
        <span aria-hidden="true" className="intake-warning">!</span>
        <div>
          <h3>File needs attention</h3>
          <p>
            {rejectedRows > 0
              ? `${formatCount(rejectedRows)} ${rejectedRows === 1 ? "row" : "rows"} failed validation.`
              : "The file failed validation."} No transactions were stored.
          </p>
        </div>
      </div>
      <div aria-label="Validation errors" className="intake-errors" role="list">
        {errors.map((error, index) => (
          <div key={`${error.row_number}-${error.field}-${error.code}-${index}`} role="listitem">
            <span>{error.row_number ? `Row ${error.row_number}` : "File"}</span>
            <p>{error.field ? <><code>{error.field}</code> · </> : null}{error.message}</p>
          </div>
        ))}
      </div>
      <footer className="intake-actions">
        <button className="intake-button intake-button-quiet" onClick={onDownload} type="button">Download error file</button>
        <button className="intake-button intake-button-primary" onClick={onReplace} type="button">Replace file</button>
      </footer>
    </div>
  );
}

function SuccessState({
  onClose,
  onReset,
  result,
}: {
  onClose: () => void;
  onReset: () => void;
  result: UploadImportResponse;
}) {
  const batch = result.batch;
  return (
    <div className="intake-state">
      <span aria-hidden="true" className="intake-success-mark">✓</span>
      <div className="intake-success-copy">
        <p>Batch {batch.display_id}</p>
        <h3>{result.created ? `${formatCount(batch.row_count)} transactions imported` : "Import already recorded"}</h3>
        <p>{result.created ? "The source checksum and ingestion record are now immutable." : "No duplicate transactions were created."}</p>
      </div>
      <dl className="intake-receipt">
        <div><dt>Source</dt><dd>{batch.source_filename ?? "REST API"}</dd></div>
        <div><dt>Checksum</dt><dd><code>{shortChecksum(batch.source_checksum)}</code></dd></div>
        <div><dt>Imported by</dt><dd>{batch.imported_by}</dd></div>
      </dl>
      <footer className="intake-actions">
        <button className="intake-button intake-button-quiet" onClick={onReset} type="button">Import another file</button>
        <button className="intake-button intake-button-primary" onClick={onClose} type="button">Return to case register</button>
      </footer>
    </div>
  );
}

function sendFile(endpoint: string, file: File) {
  return fetch(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "text/csv",
      "X-FIP-Filename": encodeURIComponent(file.name),
    },
    body: file,
  });
}

async function readApiError(response: Response) {
  try {
    const body = (await response.json()) as Partial<ApiErrorResponse>;
    return typeof body.detail === "string" ? body.detail : "The request could not be completed.";
  } catch {
    return "The request could not be completed.";
  }
}

function shortChecksum(value: string) {
  return value.length > 20 ? `${value.slice(0, 8)}…${value.slice(-8)}` : value;
}

function formatCount(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatAmount(value: string) {
  const amount = Number(value);
  return Number.isFinite(amount)
    ? new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(amount)
    : value;
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
    timeZone: "UTC",
    timeZoneName: "short",
    year: "numeric",
  }).format(date);
}

function csvValue(value: string) {
  return `"${value.replaceAll('"', '""')}"`;
}

function withoutExtension(filename: string) {
  return filename.replace(/\.csv$/i, "") || "transactions";
}
