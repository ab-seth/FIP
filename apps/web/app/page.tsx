import { DateStamp } from "./components/date-stamp";

const navigation = [
  { label: "Case register", marker: "01", active: true },
  { label: "Case dossiers", marker: "02", active: false },
  { label: "Audit ledger", marker: "03", active: false },
  { label: "Evaluation record", marker: "04", active: false },
];

function RegisterMark() {
  return (
    <svg aria-hidden="true" className="register-mark" viewBox="0 0 40 40">
      <path d="M8 7.5h24v25H8z" />
      <path d="M13 14h14M13 20h9M13 26h14" />
    </svg>
  );
}

function ImportMark() {
  return (
    <svg aria-hidden="true" className="import-mark" viewBox="0 0 48 48">
      <path d="M24 8v22M16.5 22.5 24 30l7.5-7.5M10 35v5h28v-5" />
    </svg>
  );
}

export default function Home() {
  return (
    <div className="app-frame">
      <aside className="sidebar">
        <div className="identity">
          <span className="monogram">FIP</span>
          <span className="identity-name">Financial Integrity Platform</span>
        </div>

        <nav aria-label="Primary navigation" className="primary-navigation">
          <p className="navigation-label">Workspace</p>
          <ol>
            {navigation.map((item) => (
              <li key={item.label}>
                <a aria-current={item.active ? "page" : undefined} href={item.active ? "#register" : "#"}>
                  <span className="navigation-marker">{item.marker}</span>
                  <span>{item.label}</span>
                </a>
              </li>
            ))}
          </ol>
        </nav>

        <div className="sidebar-foot">
          <span className="availability-dot" />
          <span>Systems available</span>
        </div>
      </aside>

      <main className="workspace" id="register">
        <header className="workspace-header">
          <div>
            <p className="eyebrow">Investigation workspace</p>
            <h1>Case register</h1>
          </div>
          <div className="header-context">
            <DateStamp />
            <span aria-label="Zero cases awaiting review" className="review-count">
              <strong>0</strong> awaiting review
            </span>
            <button aria-label="Open account menu" className="account-button" type="button">
              SA
            </button>
          </div>
        </header>

        <section aria-labelledby="register-title" className="register-panel">
          <div className="register-caption">
            <div>
              <p className="eyebrow">Active register</p>
              <h2 id="register-title">Investigations requiring judgment</h2>
            </div>
            <span className="record-count">0 records</span>
          </div>

          <div className="empty-register">
            <div className="empty-illustration">
              <RegisterMark />
              <span className="illustration-index">001</span>
            </div>
            <p className="empty-kicker">The register is clear</p>
            <h3>Nothing needs your judgment yet.</h3>
            <p className="empty-copy">
              Import a transaction file to begin a traceable review. Every score, explanation, and
              analyst decision will be preserved in the evidence record.
            </p>
            <div className="empty-actions">
              <button className="primary-action" type="button">
                <ImportMark />
                Import transaction file
              </button>
              <a className="text-action" href="#preparation-note">
                Read the preparation guide <span aria-hidden="true">→</span>
              </a>
            </div>
          </div>

          <footer className="register-footer" id="preparation-note">
            <span>Accepted format: CSV</span>
            <span>All imports receive a checksum</span>
            <span>Source files remain immutable</span>
          </footer>
        </section>
      </main>
    </div>
  );
}
