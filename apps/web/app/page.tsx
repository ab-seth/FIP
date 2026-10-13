import type { Metadata } from "next";
import Link from "next/link";

import { getCurrentUser } from "@/lib/auth/server";

export const metadata: Metadata = {
  title: "FIP | Agentic AI for financial investigations",
  description:
    "A governed agentic AI platform for fraud detection, evidence-grounded investigation, model operations, and human review.",
};

const agentNetwork = [
  {
    index: "A01",
    title: "Intake Agent",
    text: "Validates transaction data, preserves its source, and creates the semantic feature snapshot every downstream agent receives.",
    output: "source + schema + features",
  },
  {
    index: "A02",
    title: "Risk Agent",
    text: "Runs deterministic policy signals alongside trusted ML evidence without allowing one system to silently replace another.",
    output: "rules + model comparison",
  },
  {
    index: "A03",
    title: "Evidence Agent",
    text: "Tests proposed claims against the case record, rejects unsupported assertions, and binds valid claims to exact citations.",
    output: "grounding + validation",
  },
  {
    index: "A04",
    title: "Briefing Agent",
    text: "Turns validated signals into an investigator-ready brief containing risk factors, uncertainties, and review prompts.",
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
    text: "Benchmarks, shadow evaluation, role controls, and human approval stand between generated intelligence and consequential action.",
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
          <a href="#ai-stack">AI stack</a>
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
            <span>Agentic fraud intelligence</span>
            <span>Evidence governed</span>
          </p>
          <h1>A team of AI agents for every financial investigation.</h1>
          <p className="landing-deck">
            FIP coordinates specialist agents across intake, risk, evidence, explanation, and
            model governance—combining rules, machine learning, and LLM reasoning while keeping
            final authority with a human investigator.
          </p>
          <div className="landing-actions">
            <Link className="landing-primary-action" href="/register">
              Request AI evaluation <span aria-hidden="true">→</span>
            </Link>
            <a className="landing-secondary-action" href="#demo">
              Watch the 51-second film
            </a>
          </div>
          <p className="landing-hero-note">
            Local or hosted models · Structured tools · Human authorization
          </p>
        </div>

        <div aria-label="Illustrative FIP agent orchestration trace" className="landing-agent-console">
          <header>
            <div>
              <span className="landing-agent-console-mark">FIP / AGENT RUN</span>
              <p>Illustrative orchestration trace</p>
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

      <section aria-labelledby="film-title" className="landing-film" id="demo">
        <header>
          <p className="landing-section-index">01 / Product film</p>
          <h2 id="film-title">Why the back office needs an agent network.</h2>
          <p>
            See how FIP reframes fragmented alerts, systems, and evidence as one coordinated
            investigation workflow.
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
            FIP replaces fragmented alert review with one traceable system that brings together
            AI assistance, evidence, and accountable human decisions.
          </p>
        </figure>
      </section>

      <section aria-labelledby="agents-title" className="landing-flow" id="agents">
        <header>
          <p className="landing-section-index">02 / Agent network</p>
          <h2 id="agents-title">One investigation. Five bounded agents.</h2>
          <p>
            Each specialist has a narrow responsibility, a defined evidence contract, and a
            handoff the next agent can inspect.
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
            FIP breaks investigation work into controlled responsibilities. Agents use governed
            tools, exchange structured evidence, and stop at explicit authority boundaries.
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

      <section className="landing-model-evidence" id="ai-stack">
        <div className="landing-model-statement">
          <p className="landing-section-index">04 / Hybrid AI stack</p>
          <h2>Bring the model. FIP governs the intelligence.</h2>
          <p>
            Connect local models such as Qwen through LM Studio or use an OpenAI-compatible hosted
            provider. FIP surrounds every completion with structured evidence, validation, and
            review controls.
          </p>
          <Link href="/register">
            Evaluate the AI runtime <span aria-hidden="true">→</span>
          </Link>
        </div>

        <div aria-label="FIP hybrid intelligence stack" className="landing-intelligence-stack">
          <header><span>INTELLIGENCE / STACK</span><strong>Provider-flexible</strong></header>
          <div className="landing-stack-sources">
            <article><span>01</span><strong>Policy rules</strong><small>deterministic</small></article>
            <article><span>02</span><strong>ML runtime</strong><small>trusted + shadow</small></article>
            <article><span>03</span><strong>LLM agents</strong><small>local + hosted</small></article>
          </div>
          <div className="landing-stack-gate">
            <span>VALIDATION GATE</span>
            <strong>Schema · citations · numerical claims · prohibited actions</strong>
          </div>
          <div className="landing-stack-output">
            <div><span>STRUCTURED OUTPUT</span><strong>Grounded investigation brief</strong></div>
            <div><span>AUTHORITY</span><strong>Human investigator</strong></div>
          </div>
          <footer><span>Provider identity recorded</span><span>Fallbacks remain visible</span></footer>
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

        <div aria-label="Illustrative agent activity ledger" className="landing-ledger-trace">
          <header><span>ILLUSTRATIVE ACTIVITY TRACE</span><strong>CASE / 00842</strong></header>
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
              <li>collect and compare investigation evidence</li>
              <li>invoke approved rules, models, and validators</li>
              <li>produce cited briefs with uncertainty</li>
              <li>recommend the next review step</li>
            </ul>
          </article>
          <article>
            <span>FIP agents cannot</span>
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
          <p className="landing-section-index">Controlled AI evaluation</p>
          <h2>Put the agent network inside a real review workflow.</h2>
        </div>
        <p>
          Tell us how your team investigates financial risk, which model environment it can use,
          and where human approval must remain. We will map the right evaluation boundary.
        </p>
        <div>
          <Link className="landing-primary-action" href="/register">
            Request evaluation <span aria-hidden="true">→</span>
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
