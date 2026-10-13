import type { Metadata } from "next";
import Link from "next/link";

import { getCurrentUser } from "@/lib/auth/server";

export const metadata: Metadata = {
  title: "FIP | AI fraud intelligence across the transaction lifecycle",
  description:
    "A governed AI platform for pre-authorization fraud detection, continuous transaction monitoring, and post-transaction investigation.",
};

const agentNetwork = [
  {
    index: "A01",
    title: "Intake Agent",
    text: "Validates user- and system-initiated transaction requests, posted events, alerts, and case data while preserving the source of every signal.",
    output: "source + schema + features",
  },
  {
    index: "A02",
    title: "Risk Agent",
    text: "Runs deterministic policy signals alongside trusted ML evidence at initiation and during ongoing monitoring without hiding either assessment.",
    output: "rules + model comparison",
  },
  {
    index: "A03",
    title: "Evidence Agent",
    text: "Tests real-time risk signals and post-transaction findings against available evidence, rejecting unsupported claims and binding valid ones to their sources.",
    output: "grounding + validation",
  },
  {
    index: "A04",
    title: "Briefing Agent",
    text: "Turns validated signals into decision context or an investigator-ready brief containing risk factors, uncertainty, and review prompts.",
    output: "cited case brief",
  },
  {
    index: "A05",
    title: "Model Guardian",
    text: "Tracks datasets, training runs, shadow results, evaluation gates, and every decision that changes model trust status.",
    output: "lineage + evaluation",
  },
] as const;

const runtimePrinciples = [
  {
    index: "01",
    title: "Bounded tools",
    text: "Agents work through explicit platform capabilities, schemas, and permissions—not unrestricted system access.",
    note: "Controlled action surface",
  },
  {
    index: "02",
    title: "Shared evidence memory",
    text: "Every handoff uses structured case state with source references instead of relying on an opaque conversation history.",
    note: "Case memory, not chat memory",
  },
  {
    index: "03",
    title: "Hybrid intelligence",
    text: "Deterministic rules, governed ML models, and LLM reasoning contribute distinct signals that remain independently visible.",
    note: "No single hidden score",
  },
  {
    index: "04",
    title: "Observable reasoning",
    text: "Agent outputs expose citations, numerical checks, uncertainty, rejected claims, provider identity, and version history.",
    note: "Every output can be challenged",
  },
  {
    index: "05",
    title: "Authority gates",
    text: "Model evaluation, role controls, and human approval stand between generated intelligence and consequential action.",
    note: "Autonomy remains bounded",
  },
] as const;

const traceEvents = [
  {
    id: "EVT-001",
    agent: "Intake Agent",
    action: "Transaction normalized; source and 14 semantic fields sealed.",
    proof: "source.8ab3",
  },
  {
    id: "EVT-002",
    agent: "Risk Agent",
    action: "Three policy signals compared with the trusted model assessment.",
    proof: "risk.v1",
  },
  {
    id: "EVT-003",
    agent: "Evidence Agent",
    action: "Two unsupported claims rejected before the brief was accepted.",
    proof: "grounding.v3",
  },
  {
    id: "EVT-004",
    agent: "Briefing Agent",
    action: "Cited case brief routed to the human investigation queue.",
    proof: "brief.03",
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
          <a href="#agents">Agents</a>
          <a href="#integration">Integration</a>
          <a href="#boundary">Safeguards</a>
        </nav>
        <div className="landing-entry">
          <Link className="landing-text-link" href="/register">
            Request access
          </Link>
          <Link className="landing-entry-link" href={entryHref}>
            {entryLabel}
            <span aria-hidden="true">↗</span>
          </Link>
        </div>
      </header>

      <section className="landing-hero landing-agent-hero">
        <div className="landing-hero-copy">
          <p className="landing-kicker">
            <span>Transaction lifecycle intelligence</span>
            <span>Evidence governed</span>
          </p>
          <h1>AI fraud intelligence before and after a transaction.</h1>
          <p className="landing-deck">
            FIP connects user- and system-initiated transactions, risk signals, posted activity,
            and case evidence to specialist AI agents—supporting intervention before authorization
            as well as monitoring and investigation after transactions occur.
          </p>
          <div className="landing-actions">
            <Link className="landing-primary-action" href="/register">
              Plan an integration <span aria-hidden="true">→</span>
            </Link>
            <a className="landing-secondary-action" href="#product-film">
              Watch the 51-second film
            </a>
          </div>
          <p className="landing-hero-note">
            Pre-authorization signals · Continuous monitoring · Post-transaction investigation
          </p>
        </div>

        <div aria-label="FIP agent orchestration workflow" className="landing-agent-console">
          <header>
            <div>
              <span className="landing-agent-console-mark">FIP / AGENT RUN</span>
              <p>Investigation orchestration</p>
            </div>
            <span className="landing-agent-live"><i /> Coordinating</span>
          </header>

          <div className="landing-agent-input">
            <span>CASE / 00842</span>
            <strong>Cross-border card-not-present transaction</strong>
            <small>USD 300 · source sealed</small>
          </div>

          <div className="landing-agent-supervisor">
            <span>SUPERVISOR</span>
            <strong>Investigation orchestrator</strong>
            <small>Routes evidence, not authority</small>
          </div>

          <div className="landing-agent-grid">
            <article className="is-complete">
              <header><span>A01</span><em>Complete</em></header>
              <strong>Intake Agent</strong>
              <p>Schema verified</p>
              <small>14 features written</small>
            </article>
            <article className="is-active">
              <header><span>A02</span><em>Active</em></header>
              <strong>Risk Agent</strong>
              <p>Signals compared</p>
              <small>rules + trusted model</small>
            </article>
            <article className="is-complete">
              <header><span>A03</span><em>Complete</em></header>
              <strong>Evidence Agent</strong>
              <p>Claims grounded</p>
              <small>2 claims rejected</small>
            </article>
            <article className="is-queued">
              <header><span>A04</span><em>Queued</em></header>
              <strong>Briefing Agent</strong>
              <p>Review brief</p>
              <small>awaiting final evidence</small>
            </article>
          </div>

          <footer>
            <div><span>HUMAN GATE</span><strong>Final case classification</strong></div>
            <em>Required</em>
          </footer>
        </div>
      </section>

      <section aria-labelledby="film-title" className="landing-film" id="product-film">
        <header>
          <p className="landing-section-index">01 / Product film</p>
          <h2 id="film-title">Why fraud operations need an agent network.</h2>
          <p>
            See how FIP connects fragmented signals, systems, and evidence from transaction
            initiation through investigation.
          </p>
        </header>
        <figure>
          <video
            aria-describedby="film-summary"
            aria-label="FIP agentic fraud intelligence product film"
            controls
            playsInline
            poster="/media/fip-demo-poster.jpg"
            preload="metadata"
          >
            <source src="/media/fip-demo.mp4" type="video/mp4" />
            Your browser does not support embedded video.
          </video>
          <figcaption>
            <span>FIP / Product film</span>
            <span>00:51 · Sound available</span>
          </figcaption>
          <p id="film-summary">
            FIP creates one traceable fraud-intelligence workflow across transaction screening,
            ongoing monitoring, evidence, and accountable human decisions.
          </p>
        </figure>
      </section>

      <section aria-labelledby="agents-title" className="landing-flow" id="agents">
        <header>
          <p className="landing-section-index">02 / Agent network</p>
          <h2 id="agents-title">From transaction intent to investigation record.</h2>
          <p>
            Agents can assemble decision context as a transaction is initiated, monitor activity
            after posting, and build an evidence-grounded record when investigation is required.
          </p>
        </header>
        <ol className="landing-agent-network">
          {agentNetwork.map((agent) => (
            <li key={agent.index}>
              <span>{agent.index}</span>
              <h3>{agent.title}</h3>
              <p>{agent.text}</p>
              <small>{agent.output}</small>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="platform-title" className="landing-platform" id="platform">
        <div className="landing-platform-intro">
          <p className="landing-section-index">03 / Agent runtime</p>
          <h2 id="platform-title">More than a chatbot window.</h2>
          <p>
            FIP fits AI into the way institutions screen, monitor, and investigate transactions.
            Agents use approved tools, exchange structured evidence, and stop at explicit policy
            and authority boundaries.
          </p>
        </div>
        <ol className="landing-capability-list">
          {runtimePrinciples.map((principle) => (
            <li key={principle.index}>
              <span>{principle.index}</span>
              <div>
                <h3>{principle.title}</h3>
                <p>{principle.text}</p>
              </div>
              <small>{principle.note}</small>
            </li>
          ))}
        </ol>
      </section>

      <section className="landing-model-evidence" id="integration">
        <div className="landing-model-statement">
          <p className="landing-section-index">04 / Institutional integration</p>
          <h2>Connect the intelligence your institution already trusts.</h2>
          <p>
            FIP is designed to connect with approved data sources, risk models, policy rules, and
            authorization and case workflows. Every AI-generated contribution is bound to source
            evidence, validation policy, access controls, and accountable review.
          </p>
          <Link href="/register">
            Plan your integration <span aria-hidden="true">→</span>
          </Link>
        </div>

        <div aria-label="FIP institutional integration architecture" className="landing-intelligence-stack">
          <header><span>INTELLIGENCE / CONTROL PLANE</span><strong>Environment-aware</strong></header>
          <div className="landing-stack-sources">
            <article><span>01</span><strong>Transaction activity</strong><small>requests + posted events</small></article>
            <article><span>02</span><strong>Risk intelligence</strong><small>rules + approved models</small></article>
            <article><span>03</span><strong>Decision operations</strong><small>controls + case queues</small></article>
          </div>
          <div className="landing-stack-gate">
            <span>GOVERNANCE GATE</span>
            <strong>Evidence · policy · access · model quality · prohibited actions</strong>
          </div>
          <div className="landing-stack-output">
            <div><span>OPERATIONAL OUTPUT</span><strong>Grounded investigation record</strong></div>
            <div><span>DECISION AUTHORITY</span><strong>Your investigation team</strong></div>
          </div>
          <footer><span>Model and source lineage recorded</span><span>Degraded modes remain visible</span></footer>
        </div>
      </section>

      <section aria-labelledby="ledger-title" className="landing-agent-ledger" id="evidence">
        <div className="landing-agent-ledger-copy">
          <p className="landing-section-index">05 / Agent observability</p>
          <h2 id="ledger-title">Every agent leaves a receipt.</h2>
          <p>
            An agent should never disappear behind its answer. FIP records what it received, which
            tool it used, what it produced, what validation rejected, and who accepted the handoff.
          </p>
          <div className="landing-ledger-proof">
            <span>Append-only</span><span>Actor identified</span><span>Checksum linked</span>
          </div>
        </div>

        <div aria-label="Agent activity record" className="landing-ledger-trace">
          <header><span>AGENT ACTIVITY RECORD</span><strong>CASE / 00842</strong></header>
          <ol>
            {traceEvents.map((event) => (
              <li key={event.id}>
                <span>{event.id}</span>
                <div><strong>{event.agent}</strong><p>{event.action}</p></div>
                <code>{event.proof}</code>
              </li>
            ))}
          </ol>
          <footer><span>Chain integrity</span><strong>Verified</strong><code>4AD.F3D.F79.A94</code></footer>
        </div>
      </section>

      <section aria-labelledby="boundary-title" className="landing-boundary" id="boundary">
        <header>
          <p className="landing-section-index">06 / Trust boundary</p>
          <h2 id="boundary-title">AI that knows where its authority ends.</h2>
        </header>
        <div className="landing-boundary-grid">
          <article>
            <span>FIP agents can</span>
            <ul>
              <li>evaluate user- and system-initiated transaction context</li>
              <li>route risk signals to institution-approved controls</li>
              <li>monitor posted activity for emerging patterns</li>
              <li>build cited investigation records with uncertainty</li>
            </ul>
          </article>
          <article>
            <span>FIP agents cannot</span>
            <ul>
              <li>independently approve or decline a transaction</li>
              <li>override institutional policy or access controls</li>
              <li>declare fraud proven</li>
              <li>block, freeze, or move funds</li>
            </ul>
          </article>
        </div>
      </section>

      <section className="landing-access" id="access">
        <div>
          <p className="landing-section-index">Integration planning</p>
          <h2>Bring governed AI into your transaction-risk operation.</h2>
        </div>
        <p>
          Tell us how transactions are initiated and authorized, how posted activity is monitored,
          how investigations move, and where human authority belongs. We will map FIP to that
          operating model.
        </p>
        <div>
          <Link className="landing-primary-action" href="/register">
            Plan an integration <span aria-hidden="true">→</span>
          </Link>
          <Link className="landing-secondary-action" href={entryHref}>{entryLabel}</Link>
        </div>
      </section>

      <footer className="landing-footer">
        <Link className="landing-identity" href="/">
          <span>FIP</span><strong>Financial Integrity Platform</strong>
        </Link>
        <p>Agentic intelligence with evidence. Human authority by design.</p>
        <div><a href="#agents">Agents</a><a href="#boundary">Safeguards</a><Link href="/login">Secure entry</Link></div>
      </footer>
    </main>
  );
}
