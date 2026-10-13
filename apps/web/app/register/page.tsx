import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth/server";

export const metadata: Metadata = {
  title: "FIP | Request controlled access",
  description: "Request reviewed access to the Financial Integrity Platform.",
};

const accessStages = [
  {
    index: "01",
    title: "Identify the organization",
    text: "Establish who is evaluating FIP and the financial-risk investigation in scope.",
  },
  {
    index: "02",
    title: "Define the agent workflow",
    text: "Select the specialist agents, model environment, evidence sources, and human responsibilities to evaluate.",
  },
  {
    index: "03",
    title: "Approve the AI boundary",
    text: "Activate only the models, tools, data access, and operating roles approved for the evaluation.",
  },
] as const;

export default async function RegisterPage() {
  if (await getCurrentUser()) {
    redirect("/workspace");
  }

  return (
    <main className="access-page">
      <header className="access-page-header">
        <Link aria-label="Return to FIP overview" className="landing-identity" href="/">
          <span>FIP</span>
          <strong>Financial Integrity Platform</strong>
        </Link>
        <Link className="access-page-login-link" href="/login">
          Already assigned? <strong>Sign in</strong>
        </Link>
      </header>

      <section className="access-request-layout">
        <div className="access-request-copy">
          <p className="landing-section-index">Controlled AI evaluation</p>
          <h1>Evaluate the agent network inside a trusted boundary.</h1>
          <p>
            FIP does not open self-service access to financial investigations or connected AI
            providers. The access desk first confirms the organization, intended workflow, model
            environment, and human authority boundary.
          </p>
          <div className="access-request-actions">
            <Link className="landing-primary-action" href="/login?support=access">
              Open access support <span aria-hidden="true">→</span>
            </Link>
            <Link className="landing-secondary-action" href="/">Return to overview</Link>
          </div>
          <small>
            The access desk prepares the evaluation handoff. Models, tools, and account activation
            remain administrator controlled.
          </small>
        </div>

        <div className="access-request-register">
          <header><span>AI EVALUATION / REQUEST</span><strong>Review sequence</strong></header>
          <ol>
            {accessStages.map((stage) => (
              <li key={stage.index}>
                <span>{stage.index}</span>
                <div><h2>{stage.title}</h2><p>{stage.text}</p></div>
              </li>
            ))}
          </ol>
          <footer>
            <span>Provider scoped</span>
            <span>Human approved</span>
            <span>Audit recorded</span>
          </footer>
        </div>
      </section>
    </main>
  );
}
