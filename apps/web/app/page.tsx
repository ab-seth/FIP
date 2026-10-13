import type { Metadata } from "next";
import Link from "next/link";

import { getCurrentUser } from "@/lib/auth/server";

export const metadata: Metadata = {
  title: "FIP | Financial intelligence with evidence",
  description:
    "A governed fraud intelligence platform for traceable detection, investigation, model operations, and human review.",
};

const evidenceFlow = [
  {
    index: "01",
    title: "Ingest",
    text: "Validate transaction data and preserve its source before assessment begins.",
  },
  {
    index: "02",
    title: "Assess",
    text: "Combine deterministic rules with governed model evidence without hiding either signal.",
  },
  {
    index: "03",
    title: "Explain",
    text: "Generate cited case briefs that fail safely when evidence cannot support a claim.",
  },
  {
    index: "04",
    title: "Review",
    text: "Keep classification and consequential decisions with an accountable human reviewer.",
  },
  {
    index: "05",
    title: "Prove",
    text: "Retain every material event in an append-only, integrity-checked evidence record.",
  },
] as const;

const capabilities = [
  {
    index: "01",
    title: "Transaction intelligence",
    text: "Schema-controlled intake, deterministic policy rules, feature snapshots, and transparent risk evidence.",
    note: "Rules remain independently inspectable",
  },
  {
    index: "02",
    title: "Hybrid risk analysis",
    text: "Trusted model artifacts can contribute calibrated evidence while shadow models remain isolated from operations.",
    note: "No silent model substitution",
  },
  {
    index: "03",
    title: "Investigation dossiers",
    text: "Analysts work from one traceable record containing transactions, signals, explanations, notes, and outcomes.",
    note: "Human classification is explicit",
  },
  {
    index: "04",
    title: "ML operations",
    text: "Datasets, training runs, model lineage, lifecycle decisions, and evaluation evidence remain reproducible.",
    note: "Artifacts are checksum verified",
  },
  {
    index: "05",
    title: "Governance evidence",
    text: "Audit records and system benchmarks make safety boundaries visible to operators, evaluators, and reviewers.",
    note: "Decision support, never hidden authority",
  },
] as const;

export default async function LandingPage() {
  const user = await getCurrentUser();
  const entryHref = user ? "/workspace" : "/login";
  const entryLabel = user ? "Open workspace" : "Sign in";

  return (
    <main className="landing-page">
      <header className="landing-header">
        <Link aria-label="Financial Integrity Platform home" className="landing-identity" href="/">
          <span>FIP</span>
          <strong>Financial Integrity Platform</strong>
        </Link>
        <nav aria-label="Landing page navigation">
          <a href="#platform">Platform</a>
          <a href="#evidence">Evidence</a>
          <a href="#boundary">Safeguards</a>
        </nav>
        <div className="landing-entry">
          <Link className="landing-text-link" href="/register">Request access</Link>
          <Link className="landing-entry-link" href={entryHref}>{entryLabel}<span aria-hidden="true">↗</span></Link>
        </div>
      </header>

      <section className="landing-hero">
        <div className="landing-hero-copy">
          <p className="landing-kicker"><span>Governed intelligence</span><span>Human authority</span></p>
          <h1>Fraud intelligence you can examine, reproduce, and challenge.</h1>
          <p className="landing-deck">
            FIP joins deterministic screening, governed machine learning, cited AI explanations,
            and human review in one traceable investigation record.
          </p>
          <div className="landing-actions">
            <Link className="landing-primary-action" href="/register">Request controlled access<span aria-hidden="true">→</span></Link>
            <a className="landing-secondary-action" href="#evidence">Follow the evidence path</a>
          </div>
          <p className="landing-hero-note">Built for investigation teams that need more than a score.</p>
        </div>

        <div aria-label="Illustrative FIP evidence record" className="landing-record">
          <header>
            <div>
              <span className="landing-record-mark">FIP</span>
              <p>Illustrative evidence record</p>
            </div>
            <span className="landing-record-state">Review open</span>
          </header>
          <div className="landing-record-title">
            <span>CASE / 00842</span>
            <h2>Signals become evidence before they become decisions.</h2>
          </div>
          <ol>
            <li><span>01</span><div><strong>Rules assessment</strong><small>Deterministic signal preserved</small></div><em>Verified</em></li>
            <li><span>02</span><div><strong>Model evidence</strong><small>Trusted lineage attached</small></div><em>Governed</em></li>
            <li><span>03</span><div><strong>Grounded brief</strong><small>Claims cite exact evidence</small></div><em>Validated</em></li>
            <li><span>04</span><div><strong>Analyst judgment</strong><small>Final classification remains human</small></div><em>Required</em></li>
          </ol>
          <footer><span>Evidence checksum</span><code>4AD.F3D.F79.A94</code><span>Append-only record</span></footer>
        </div>
      </section>

      <section aria-labelledby="evidence-title" className="landing-flow" id="evidence">
        <header>
          <p className="landing-section-index">01 / Evidence path</p>
          <h2 id="evidence-title">From raw transaction to defensible review.</h2>
          <p>Each stage leaves enough evidence for the next person to question it.</p>
        </header>
        <ol>
          {evidenceFlow.map((step) => (
            <li key={step.index}>
              <span>{step.index}</span>
              <h3>{step.title}</h3>
              <p>{step.text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="platform-title" className="landing-platform" id="platform">
        <div className="landing-platform-intro">
          <p className="landing-section-index">02 / Platform</p>
          <h2 id="platform-title">One operating record. Five disciplines.</h2>
          <p>
            Detection, investigation, machine learning, evaluation, and audit evidence live together
            without collapsing their separate responsibilities.
          </p>
        </div>
        <ol className="landing-capability-list">
          {capabilities.map((capability) => (
            <li key={capability.index}>
              <span>{capability.index}</span>
              <div><h3>{capability.title}</h3><p>{capability.text}</p></div>
              <small>{capability.note}</small>
            </li>
          ))}
        </ol>
      </section>

      <section className="landing-model-evidence">
        <div className="landing-model-statement">
          <p className="landing-section-index">03 / Model evidence</p>
          <h2>Machine learning should increase signal—not reduce accountability.</h2>
          <p>
            FIP treats every dataset, training run, artifact, promotion decision, and shadow result
            as evidence with lineage, checksums, and an accountable actor.
          </p>
          <Link href="/register">Evaluate the platform <span aria-hidden="true">→</span></Link>
        </div>
        <div className="landing-lineage" aria-label="Governed model lineage">
          <div className="landing-lineage-head"><span>MODEL / LINEAGE</span><strong>Operational evidence</strong></div>
          <ol>
            <li><span>Dataset snapshot</span><strong>Sealed</strong><small>source + schema + checksum</small></li>
            <li><span>Training run</span><strong>Reproducible</strong><small>parameters + metrics + artifact</small></li>
            <li><span>Candidate model</span><strong>Isolated</strong><small>registration + review + status</small></li>
            <li><span>Shadow evaluation</span><strong>Measured</strong><small>predictions + benchmark evidence</small></li>
          </ol>
          <footer><span>Promotion requires human authorization</span><span>Automatic action prohibited</span></footer>
        </div>
      </section>

      <section aria-labelledby="boundary-title" className="landing-boundary" id="boundary">
        <header>
          <p className="landing-section-index">04 / Trust boundary</p>
          <h2 id="boundary-title">Designed around what intelligence must never do alone.</h2>
        </header>
        <div className="landing-boundary-grid">
          <article>
            <span>FIP can</span>
            <ul>
              <li>surface and rank evidence for review</li>
              <li>compare rule and model signals</li>
              <li>produce citations and uncertainty</li>
              <li>measure model and system performance</li>
            </ul>
          </article>
          <article>
            <span>FIP cannot</span>
            <ul>
              <li>silently change an operational score</li>
              <li>declare fraud proven</li>
              <li>classify a case without a human</li>
              <li>block, freeze, or move funds</li>
            </ul>
          </article>
        </div>
      </section>

      <section className="landing-access" id="access">
        <div>
          <p className="landing-section-index">Controlled access</p>
          <h2>Bring your review process into the evidence record.</h2>
        </div>
        <p>
          Access is role-based and reviewed. Tell us how your team investigates financial risk;
          we will map the right evaluation path without opening operational authority by default.
        </p>
        <div>
          <Link className="landing-primary-action" href="/register">Request access<span aria-hidden="true">→</span></Link>
          <Link className="landing-secondary-action" href={entryHref}>{entryLabel}</Link>
        </div>
      </section>

      <footer className="landing-footer">
        <Link className="landing-identity" href="/"><span>FIP</span><strong>Financial Integrity Platform</strong></Link>
        <p>Decision support with evidence. Human authority by design.</p>
        <div><a href="#platform">Platform</a><a href="#boundary">Safeguards</a><Link href="/login">Secure entry</Link></div>
      </footer>
    </main>
  );
}
