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
    text: "Establish who is evaluating FIP and the financial-risk workflow in scope.",
  },
  {
    index: "02",
    title: "Define the responsibility",
    text: "Map analyst, evaluator, and administrator duties before any role is assigned.",
  },
  {
    index: "03",
    title: "Approve the boundary",
    text: "Activate only the access required for an agreed evaluation or operating role.",
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
          <p className="landing-section-index">Controlled registration</p>
          <h1>Access starts with a reviewed request.</h1>
          <p>
            FIP does not create open accounts for an investigation environment. The access desk
            first confirms the organization, intended responsibility, and evaluation boundary.
          </p>
          <div className="access-request-actions">
            <Link className="landing-primary-action" href="/login?support=access">
              Open access support <span aria-hidden="true">→</span>
            </Link>
            <Link className="landing-secondary-action" href="/">Return to overview</Link>
          </div>
          <small>
            The access desk prepares the request handoff. Account activation remains administrator controlled.
          </small>
        </div>

        <div className="access-request-register">
          <header><span>ACCESS / REQUEST</span><strong>Review sequence</strong></header>
          <ol>
            {accessStages.map((stage) => (
              <li key={stage.index}>
                <span>{stage.index}</span>
                <div><h2>{stage.title}</h2><p>{stage.text}</p></div>
              </li>
            ))}
          </ol>
          <footer>
            <span>Role-based access</span>
            <span>Administrator approval</span>
            <span>Auditable activation</span>
          </footer>
        </div>
      </section>
    </main>
  );
}
